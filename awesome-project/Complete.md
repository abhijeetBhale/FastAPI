# Complete Project Documentation — AI Cargo Inspection & Lifting Plan Platform

> **Repository:** `awesome-project` · **API version:** `2.0.0` · **Schema head:** `0012_ai_decision`
> **Last reviewed against the code:** 2026-10-15
>
> This is the single consolidated reference for the project. It merges what the
> code actually does with the existing documents (`README.md`,
> `Technical_Document.md`, `Understanding_Document.md`, everything in `docs/`)
> and the two real HSE-F003 lifting plans (see
> [`Lifting_Plan_Reference.md`](Lifting_Plan_Reference.md)). Where an older
> document and the code disagree, **this file follows the code**, and §18 lists
> each disagreement.

---

## Table of contents

1. [What the project is](#1-what-the-project-is)
2. [Golden rule and scope](#2-golden-rule-and-scope)
3. [Users and roles](#3-users-and-roles)
4. [End-to-end workflow](#4-end-to-end-workflow)
5. [Technology stack](#5-technology-stack)
6. [Architecture](#6-architecture)
7. [Repository layout](#7-repository-layout)
8. [Configuration (.env)](#8-configuration-env)
9. [Security: authentication and RBAC](#9-security-authentication-and-rbac)
10. [API reference](#10-api-reference)
11. [Response and error conventions](#11-response-and-error-conventions)
12. [Data model and migrations](#12-data-model-and-migrations)
13. [Business logic (services)](#13-business-logic-services)
14. [Cargo detection pipeline (YOLO + SAM)](#14-cargo-detection-pipeline-yolo--sam)
15. [AI decision (OpenAI Decisions API)](#15-ai-decision-openai-decisions-api)
16. [Lifting plan generator](#16-lifting-plan-generator)
17. [Web portal (static UI)](#17-web-portal-static-ui)
18. [Known gaps, inconsistencies and stale docs](#18-known-gaps-inconsistencies-and-stale-docs)
19. [Running, testing and operations](#19-running-testing-and-operations)
20. [Assumptions (plain language)](#20-assumptions-plain-language)
21. [Roadmap](#21-roadmap)
22. [Glossary](#22-glossary)
23. [Document index](#23-document-index)

---

## 1. What the project is

A web platform for **port cargo lifting operations**. A crane holds a load in
the air; before the lift someone has to answer: *what is it, how big is it, how
heavy is it, and how should it be rigged?* Today a person estimates this by eye
and fills in a paper **lifting plan** (form HSE-F003).

The platform:

1. Lets users **register, sign in and upload photos** of a cargo load, with
   cargo type, notes and tags. Each upload is a **submission** (`inspection`
   in the database).
2. Runs **computer vision** (a custom YOLO-OBB detector plus Meta's SAM
   segmenter) to find the load, outline only the material (not the net,
   straps, chain, hook or crane), and produce a marked-up **overlay** image.
3. Can optionally ask an **AI decision model** (OpenAI `POST /v1/decisions`)
   whether cargo is visible and whether it matches the declared type, and
   **auto-approve** when it is confident.
4. Lets **administrators review**: approve, reject, bulk-decide, soft-delete,
   restore, purge, manage roles, and read the audit trail.
5. Generates a **draft lifting plan** (Markdown or JSON) in the layout of
   HSE-F003. It fills only what was observed or can be estimated from a stated
   assumption, and leaves every engineering and safety field blank.

The client proposal (`docs/AI-Based Cargo Identification _ NewGene.md`)
describes the long-term vision: a handheld Android app, a React dashboard, and
AI used for the 5–10% of unusual loads, with a supervisor always approving.
What this repository delivers today is the **FastAPI backend, the vendored
detection pipeline, and a vanilla-JS portal**.

---

## 2. Golden rule and scope

> **The system reports what it saw and suggests a starting point. It never
> decides whether a lift is safe. A person always decides and signs off.**

Every lifting-plan field falls into one of four categories
(`docs/LIFTING_PLAN_AI_SCOPE.md`):

| Category | Meaning | Tag in output | Examples |
|---|---|---|---|
| **A — Observed** | Directly seen in the photo | `[AI]` | Description, object count, pixel box, confidence |
| **B — Estimated** | Calculated from one stated reference | `[AI-ESTIMATE]` | Length/height in metres, weight from density |
| **B2 — Theoretical** | Idealised geometry, stated assumptions | `[AI-THEORETICAL]` | Centre of gravity, hook point, 2-leg sling angle |
| **C — Engineering judgement** | Never filled by AI; always blank | — | Lift method, routine/non-routine, crane, boom, radius, counterweight, capacity, gear, safety factor, signatures |

> An invented number on a safety document is worse than a blank space.

---

## 3. Users and roles

| Actor | System role | What they do |
|---|---|---|
| Visitor | none | Health/landing page, register, log in, read API docs |
| Site worker / registered user | `user` | Upload 1 photo per submission with cargo type, notes, tags; see own submissions, image, detection, lifting plan; withdraw own submission |
| Supervisor / reviewer | `admin` | See all submissions, review queue, approve/reject (single or bulk), edit, soft-delete, restore, purge, see detection results |
| Lifting engineer | *(outside the system)* | Takes the draft lifting plan, fills in Category C, signs |
| Manager / office | `admin` | Stats, per-user summaries, audit log, user role management |

### Permissions (`app/services/rbac.py`)

| Permission | user | admin |
|---|:-:|:-:|
| `submissions:create` | ✅ | ✅ |
| `submissions:read:own` | ✅ | ✅ |
| `submissions:update:own` | ✅ | ✅ |
| `submissions:withdraw:own` | ✅ | ✅ |
| `users:read:own` | ✅ | ✅ |
| `submissions:read:any` | | ✅ |
| `submissions:review:any` | | ✅ |
| `submissions:delete:any` | | ✅ |
| `submissions:restore:any` | | ✅ |
| `users:read:any` | | ✅ |
| `users:manage` | | ✅ |
| `audit:read` | | ✅ |

- An unknown role stored in the database is treated as `user`, the least privilege.
- Users may set only `draft` or `submitted` (`SELF_ASSIGNABLE_STATUSES`).
- In practice, admin routes check only `submissions:read:any`, `users:manage` and `audit:read`. Review, delete and restore are all gated by `submissions:read:any`.

The first admin is created with `scripts/create_admin.py` (see §19).

---

## 4. End-to-end workflow

```mermaid
flowchart TD
    A[User registers / logs in] --> B[Upload photo + cargo type + notes + tags<br/>POST /api/v1/portal/submissions]
    B --> C[Image validated: PNG/JPEG/WebP/GIF, ≤10 MB<br/>stored in storage/inspections/]
    C --> D[Row created: status draft or submitted]
    D --> E{OPENAI_DECISION_ENABLED?}
    E -- no --> F[decision_status = not_run]
    E -- yes --> G[POST /v1/decisions with image + rubric]
    G -->|both gates ≥ 0.8 and status = submitted| H[Auto-approved<br/>status_note records the reason]
    G -->|low confidence / error| I[Stays submitted → manual review]
    D --> J[User or API client triggers detection<br/>POST …/submissions/{id}/detect]
    J --> K[Subprocess: YOLO-OBB + SAM, 16–45 s on CPU]
    K --> L[detected / no_cargo / error + overlay PNG]
    L --> M[GET …/lifting-plan?ref_m=&ref_px=<br/>Draft HSE-F003 in Markdown/JSON]
    I --> N[Admin review queue]
    F --> N
    N --> O[Approve / Reject with note, audited]
    M --> P[Lifting engineer completes Category C fields and signs]
```

### Submission status lifecycle

```text
          (user, at creation only)
 [draft] ───────────────┐
 [submitted] ◄──────────┘
      │
      ├── AI auto-approve (submitted only, confidence ≥ threshold) ──► [approved]
      │
      └── admin approve / reject ──► [approved] / [rejected]
                    (admin may move between any statuses except to the same one → 409)
 Soft delete: deleted_at set (hidden) ──► admin restore / purge (hard delete)
```

### Key points

- **Detection is not automatic.** It runs only when someone calls
  `POST /api/v1/portal/submissions/{id}/detect`. The UI has no Detect button
  yet (§17).
- **Users cannot edit a submission after creating it.** There is no portal
  update route. They can only withdraw it (soft delete). Admins can `PATCH`
  any field.
- **Auto-approval** sets `status=approved` and `reviewed_at`, but leaves
  `reviewed_by` NULL.

---

## 5. Technology stack

### 5.1 Backend (versions from `uv.lock`)

| Layer | Technology | Version | Role |
|---|---|---|---|
| Language | Python | 3.12.10 (`>=3.12`) | Type hints drive validation and docs |
| Web framework | FastAPI | 0.142.2 | Routing, dependency injection, OpenAPI 3.1 |
| ASGI core | Starlette | 1.7.0 | Middleware, static files, lifespan |
| Server | Uvicorn (+uvloop, httptools) | 0.54.0 | ASGI server |
| Validation | Pydantic v2 + email-validator | 2.13.5 | Request/response schemas |
| Settings | pydantic-settings | 2.15.0 | `.env` / environment loading |
| ORM | SQLAlchemy | 2.1.1 | `DeclarativeBase`, `Mapped`, `selectinload` |
| Database | PostgreSQL | 17 (service `postgresql-x64-17`) | System of record; JSONB, partial and functional indexes |
| Driver | psycopg 3 (binary) | 3.3.6 | `postgresql+psycopg://` |
| Migrations | Alembic (+ Mako) | 1.20.0 | 12 linear revisions |
| Auth | PyJWT | 2.15.1 | HS256 session tokens |
| Password hashing | stdlib `hashlib` PBKDF2-HMAC-SHA256 | — | 260,000 iterations, 16-byte salt |
| Uploads | python-multipart | 0.0.32 | `UploadFile`/`Form` |
| HTTP client | httpx | 0.28.1 | OpenAI calls and `TestClient` |
| Env manager | uv | — | `.venv`, `uv.lock` |
| Tests | pytest 9.1.1, PyYAML 6.0.3 | dev group | 322 tests against real PostgreSQL |

`pyproject.toml` + `uv.lock` are the source of truth. `requirements.txt` is a
**stale** legacy pin list: for example it pins `fastapi==0.115.0` and
`sqlalchemy==2.0.35`, which conflict with pyproject. Regenerate it with
`uv export` if pip installs are needed.

### 5.2 Detection environment (separate virtualenv, about 5.5 GB)

| Library | Purpose |
|---|---|
| PyTorch / torchvision | Model runtime |
| Ultralytics (YOLO11 / YOLO-OBB) | Cargo detector (`cargo_obb_best.pt`) |
| segment-anything (SAM 1 ViT-B) | Mask segmentation (SAM 3 attempted; falls back) |
| OpenCV, NumPy, SciPy, scikit-image, Shapely | Image processing, geometry |
| transformers (Depth-Anything small) | Depth maps (notebook cells 16–19; **not run by the API**) |
| Open3D, Plotly | Point cloud and volume (cells 20–22; **not run by the API**) |
| Matplotlib (`Agg`), Pillow, tqdm | Overlays, progress |

### 5.3 Other components

| Component | Technology |
|---|---|
| Portal | Single `static/index.html`, vanilla HTML/CSS/JS, no build step, served at `/ui/` |
| API docs | Swagger UI (`/docs`, method-sorted), ReDoc (`/redoc`), `/openapi.json` |
| AI decision | OpenAI `POST /v1/decisions`, model `gpt-6-luna`, called with httpx |
| Planned (proposal only) | React dashboard, Android handheld app (React Native/Flutter), cloud object storage |

### 5.4 Why this stack

- **FastAPI + Pydantic:** one type annotation validates the input, serialises
  the output and documents the API.
- **PostgreSQL:** relational integrity, JSONB for detection and decision
  payloads, and partial indexes for the queues.
- **Detection as a subprocess:** the ML environment is about 5.5 GB against
  about 120 MB for the app and cannot be merged. Isolation also means a
  detector crash never takes down the API.
- **AI decision as an optional gate:** if it fails, the submission falls back
  to manual review.
- **Static portal:** zero build tooling, served by the API itself.

---

## 6. Architecture

### 6.1 Layers

```text
HTTP layer        app/api/v1/endpoints/   (routing, status codes, no business logic)
Validation layer  app/schemas/            (Pydantic requests/ and responses/)
Business layer    app/services/           (rules, transactions, audit)
Data layer        app/models/ + app/database/
Database          PostgreSQL 17 via psycopg 3
External          detector subprocess · OpenAI Decisions API · local disk storage/
```

### 6.2 Runtime diagram

```text
 Browser portal (/ui) · Swagger (/docs) · curl
                 │  JSON / multipart, cookie or Bearer
                 ▼
 Uvicorn ─► RequestContext ─► Authentication ─► RoleAuthorization ─► CORS ─► Router
             (X-Request-ID,    (JWT from cookie   (admin paths:        │
              timing)           or Bearer)         role read from DB)  ▼
                                                       Endpoints ─► Services
                                                                     │   │   │
                     ┌───────────────────────────────────────────────┘   │   └─────────────┐
                     ▼                                                   ▼                 ▼
             SQLAlchemy ─► PostgreSQL                    Detector subprocess        OpenAI /v1/decisions
                                                         (detector/.ipynb cells)    (httpx, retries)
                                                                 │
                                                                 ▼
                                                     storage/detection/…
```

### 6.3 Startup (`main.py`)

1. Load settings and configure INFO logging.
2. Create `FastAPI(title="Cargo Inspection API", version="2.0.0", lifespan=…)`
   with the built-in `/docs` disabled.
3. Register in this order: `CORSMiddleware`, exception handlers,
   `install_middlewares()`, the `/api/v1` router, the unversioned health
   router, `/ui` static mount, a custom `/docs` (operations sorted GET → POST
   → PUT → PATCH → DELETE), and `GET /`.
4. On startup the lifespan logs the app version, the DB host (credentials
   stripped) and the CORS origins. **The schema is never created at startup;
   Alembic owns it.**

### 6.4 Middleware execution order (outermost first)

1. **`RequestContextMiddleware`:** assigns `X-Request-ID` (incoming or a new
   12-character hex value), measures time, and sets the `X-Request-ID` and
   `X-Response-Time-ms` headers.
2. **`AuthenticationMiddleware`:** protects `/api/v1/portal/*` and
   `/api/v1/admin/*` (segment-aware matching).
   - Reads the `session_token` cookie first, then `Authorization: Bearer`.
   - Missing or invalid token → 401 problem with `code=authentication_required` and header `X-Auth: required`.
3. **`RoleAuthorizationMiddleware`:** on `/api/v1/admin/*` it reads
   `role, is_active` **from the database on every request**, so a demotion
   takes effect immediately.
   - Not an admin → 403 `insufficient_role` with a `your_role` member.
   - User gone or inactive → 401.
4. **`CORSMiddleware`:** innermost (see the CORS caveat in §18).
5. **Route dependencies** then enforce permissions and ownership. Another
   user's record returns **404, never 403**, so existence is not leaked.

---

## 7. Repository layout

```text
awesome-project/
├── main.py                     ASGI entry: app, middleware, routers, /docs, /ui, GET /
├── app/
│   ├── api/v1/
│   │   ├── __init__.py         API_PREFIX = "/api/v1"
│   │   ├── api.py              Router aggregation (auth, portal, detection, lifting_plan, admin)
│   │   └── endpoints/          admin.py · auth.py · detection.py · health.py · inspection.py · lifting_plan.py
│   ├── core/                   config.py (Settings) · security.py (PBKDF2, JWT, cookie) · exceptions.py (RFC 9457)
│   ├── database/               base.py (Base, utcnow) · database.py (engine, SessionLocal, get_db)
│   ├── middleware/             context.py · auth.py · rbac.py · __init__.py (install order)
│   ├── models/                 user · inspection · cargo_type · tag · inspection_tag · audit_log · idempotency_key
│   ├── schemas/                requests/ · responses/ · envelope · errors · validators
│   ├── services/               audit · auth · detection · health · idempotency · inspection ·
│   │                           lifting_plan · openai_decision · query · rbac · user
│   └── utils/                  (empty package)
├── alembic/ + alembic.ini      Migrations 0001 → 0012
├── detector/                   Vendored pipeline: Revamping.ipynb, models/cargo_obb_best.pt (+ SAM ckpt, not in git)
├── scripts/                    detect_runner.py · create_admin.py · setup_postgres.py · start_postgres.ps1 ·
│                               regen_openapi.py · cell10_probe*.py (debug probes)
├── static/index.html           Cargo Portal UI
├── storage/                    (gitignored) inspections/ uploads · detection/run_*/ · detection/overlays/
├── tests/                      10 test modules, 322 tests
├── docs/                       17 design/ops documents (see §23)
├── images/                     Screenshots of the two reference HSE-F003 lifting plans
├── cell_9_clean.py             Copy of notebook CELL 2 (misnamed; see §18)
├── cargo_output_visualizations/ Leftover overlay sample
├── Technical_Document.md       Tech-focused overview
├── Understanding_Document.md   Plain-language guide
├── Lifting_Plan_Reference.md   HSE-F003 analysis mapped to the system
├── Complete.md                 ← this file
├── README.md                   (partly stale; see §18)
├── pyproject.toml · uv.lock · requirements.txt (stale) · .env.example
└── Initial_Notes.txt           Personal study notes on FastAPI/Pydantic/Starlette/Uvicorn
```

---

## 8. Configuration (.env)

Configuration is loaded by `app/core/config.py` (`Settings`, cached with
`lru_cache`) from environment variables or `.env`. Field names are
case-insensitive.

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://postgres:postgres@localhost:5432/awesome_project?connect_timeout=10` | Shared by the app, the engine and Alembic |
| `SQL_ECHO` | `false` | Log SQL statements |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` / `DB_POOL_TIMEOUT` / `DB_POOL_RECYCLE` | 5 / 10 / 30 s / 1800 s | Connection pool (`pool_pre_ping=True`) |
| `APP_TITLE` / `APP_VERSION` | `Cargo Inspection API` / `2.0.0` | OpenAPI metadata |
| `CORS_ORIGINS` | `localhost:8000`, `127.0.0.1:8000`, `localhost:5173` | JSON list or comma-separated |
| `JWT_SECRET` | random value per process | **Must be set in production**, otherwise every restart logs everyone out |
| `JWT_EXPIRES_HOURS` | 12 | Session lifetime |
| `COOKIE_SECURE` | `true` | HTTPS-only cookie. Set `false` for local HTTP (`.env.example` does this) |
| `DETECTION_ENABLED` | `false` | Turns on the YOLO+SAM subprocess |
| `DETECTION_PYTHON` | path to the detection venv's `python.exe` | Interpreter with torch, ultralytics, etc. |
| `DETECTION_PROJECT_DIR` | `""` (use the vendored `detector/`) | Notebook and models folder |
| `DETECTION_TIMEOUT` | 300 s | Per run |
| `DETECTION_MAX_CONCURRENCY` | 1 | Notebook cells are not re-entrant; keep at 1 |
| `OPENAI_DECISION_ENABLED` | `false` | AI decision on upload |
| `OPENAI_API_KEY` | `""` | Required when enabled |
| `OPENAI_DECISION_MODEL` | `gpt-6-luna` | The only model `/v1/decisions` accepts |
| `OPENAI_DECISION_TIMEOUT` | 15 s (connect timeout 5 s) | A timeout is recorded as an error and the submission goes to manual review |
| `OPENAI_DECISION_MIN_CONFIDENCE` | 0.8 | Auto-approve threshold (inclusive) |

`APP_TITLE`, `APP_VERSION` and `CORS_ORIGINS` are not listed in `.env.example`.

---

## 9. Security: authentication and RBAC

| Aspect | Implementation |
|---|---|
| Password hashing | PBKDF2-HMAC-SHA256, 260,000 iterations, 16-byte salt. Stored as `pbkdf2_sha256$<iter>$<salt_b64>$<hash_b64>`. Compared with `hmac.compare_digest` |
| Password policy | 8–128 characters, at least one letter and one digit, not in a 20-entry common-password list |
| Session token | JWT HS256: `{sub, email, jti, iat, exp}`. **No role claim**; the role is always read from the DB |
| Transport | `session_token` cookie (`HttpOnly`, `SameSite=Strict`, `Secure` per config, `path=/`). Bearer header also accepted (Swagger "Authorize") |
| Token in body? | Never. Login and register only set the cookie |
| Enumeration defence | The same message for an unknown email and a wrong password. A dummy hash is checked for unknown users so timing matches |
| Failed logins | Audited as `login_failed`. **No rate limiting** (gap) |
| Ownership | Another user's resource → 404 |
| Admin gate | Middleware (role from DB) plus route permission dependency |
| Path traversal | Overlay paths are confined to `storage/detection/overlays/` |
| XSS (portal) | `escapeHtml()` on interpolated values |

---

## 10. API reference

Everything versioned lives under **`/api/v1/{auth|portal|admin}/…`**: kebab-case
segments, snake_case path parameters. These stay unversioned by design: `/`,
`/health`, `/health/ready`, `/docs`, `/redoc`, `/openapi.json` and `/ui`. The full
OpenAPI is generated into `docs/API_CONVENTIONS.md` §9 by
`scripts/regen_openapi.py`; `tests/test_api_contract.py` fails if the two drift.

Legend: **Pub** = public · **U** = any signed-in user (owner scope) · **A** = admin.

### 10.1 Auth — `/api/v1/auth`

| Method | Path | Auth | Body | Success | Errors |
|---|---|---|---|---|---|
| POST | `/register` | Pub | `{name 1–50, email, phone?, password 8–128}` | 201 + cookie + `Location: /api/v1/auth/me`, `{user, expires_in_hours}` | 409 duplicate email, 422 weak password |
| POST | `/login` | Pub | `{email, password}` | 200 + cookie | 401 generic / "no password yet" |
| POST | `/logout` | Pub | — | 200, cookie cleared | — |
| GET | `/me` | U | — | `{user, permissions[], is_admin}` | 401 |
| POST | `/set-password` | U | `{password}` | 200 + reissued cookie | 400 already set, 422 weak |
| POST | `/change-password` | U | `{current_password, new_password}` | 200 | 400 wrong current, 422 weak |

`user` = `{id, name, email, phone, role, created_at, inspection_count, has_password}`.

### 10.2 Portal — `/api/v1/portal`

| Method | Path | Auth | Request | Response |
|---|---|---|---|---|
| GET | `/cargo-types` | U | — | Cargo types sorted by label |
| GET | `/summary` | U | — | `{total, stats, cargo_types, has_any}` for the caller |
| GET | `/submissions` | U | `page`, `per_page` (default 6, 1–100), `cargo_type`, `status`, `tag`, `search`, `sort` (default `-created_at`) | Paginated envelope |
| POST | `/submissions` | U | multipart: `cargo_type`*, `status` (draft/submitted), `notes`, `tags` (CSV), `image`*; optional `Idempotency-Key` header | 201 + `Location`; replay returns the stored response with `Idempotent-Replay: true` |
| GET | `/submissions/{id}` | U | — | Submission, or 404 |
| DELETE | `/submissions/{id}` | U | — | 204 (idempotent soft delete) |
| GET | `/submissions/{id}/image` | U | — | Original image file |
| GET | `/detection/availability` | U | — | `{enabled, available, reason, timeout_seconds, supports_measurement:false}` |
| POST | `/submissions/{id}/detect` | U + `submissions:create` | Optional `{"force": true}` | 200 result. Cached unless `force`. 404 missing image · 502 pipeline failed · 503 disabled/busy · 504 timeout |
| GET | `/submissions/{id}/detection` | U | — | Stored result (never starts a run) |
| GET | `/submissions/{id}/detection/log` | U | — | `{inspection_id, returncode, stdout_tail}` |
| GET | `/submissions/{id}/detection/overlay` | U | — | Overlay PNG |
| GET | `/submissions/{id}/lifting-plan` | U | `ref_m` & `ref_px` (both or neither, >0), `format=markdown\|json` | Markdown file download or JSON envelope. 422 if detection is `not_run`, `no_cargo` or `error`, or if only one ref value is given |

### 10.3 Admin — `/api/v1/admin`

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/submissions` | read:any | Filters: `user_id`, `cargo_type`, `status`, `tag`, `search`, `include_deleted`, `sort`; `per_page` default 20 |
| POST | `/submissions` | read:any | Create on behalf of a user (by `name`/`email`, created if unknown); any status; idempotency supported |
| GET | `/submissions/pending` | read:any | `status=submitted`, oldest first |
| GET | `/submissions/summary` | read:any | Per-user counts and weight totals |
| GET | `/submissions/orphaned-users` | read:any | Users with no live submissions |
| GET | `/submissions/{id}` | read:any | `include_deleted` optional |
| POST | `/submissions/{id}/approve` | read:any | Body `{note ≤300}`; 409 if already approved |
| POST | `/submissions/{id}/reject` | read:any | Same; 409 if already rejected |
| POST | `/submissions/bulk` | read:any | `{ids[1–200], action: approve\|reject, note?}`; each id committed independently |
| PATCH | `/submissions/{id}` | read:any | Partial: status, status_note, notes, cargo_type, volume_m3, estimated_weight_kg, tags |
| GET | `/submissions/{id}/detection` | read:any | Read-only, includes deleted |
| GET | `/submissions/{id}/detection/overlay` | read:any | PNG |
| GET | `/submissions/{id}/image` | read:any | File |
| POST | `/submissions/{id}/restore` | read:any | Undo soft delete |
| DELETE | `/submissions/{id}` | read:any | Soft delete, 204, idempotent |
| DELETE | `/submissions/{id}/purge` | read:any | Hard delete row and image |
| GET | `/stats` | read:any | `{stats, by_status, by_cargo, users, admins}` |
| GET | `/audit` | audit:read | Filters `entity_type`, `action`; `per_page` default 50 |
| GET | `/cargo-types` | read:any | List |
| GET | `/users` | users:manage | Paginated |
| GET | `/users/{id}` | users:manage | Adds `inspection_count` |
| PATCH | `/users/{id}` | users:manage | `{role: user\|admin}`; 400 if an admin tries to demote themselves |

### 10.4 Health and root

| Method | Path | Response |
|---|---|---|
| GET | `/` | `{message:"API is running", api:"/api/v1", ui:"/ui/", docs:"/docs", health:"/health"}` |
| GET | `/health` | Liveness: `{status, service, version, timestamp}`; no DB access |
| GET | `/health/ready` | Readiness: `SELECT 1` → `{status, database:"up", latency_ms}` or 503 |

Totals: **38 paths / 44 operations** under the API, plus the unversioned routes.

---

## 11. Response and error conventions

Detailed in `docs/API_CONVENTIONS.md`.

### Success envelope

```json
{
  "data": { "...": "..." },
  "meta": { "pagination": { "page": 1, "per_page": 20, "total": 57, "total_pages": 3 } },
  "links": { "self": "/api/v1/portal/submissions?page=1&per_page=20", "next": "...", "last": "..." }
}
```

- `meta` and `links` appear only when non-empty. Null fields are removed;
  empty `[]` and `{}` are kept.
- Datetimes are ISO-8601 UTC with a `Z` suffix. Stored values are naive UTC.
- `links`: `self` always; `next`/`prev` when they exist; `first`/`last` when
  there is more than one page.
- Pagination: `page ≥ 1`, `per_page` 1–100. Above 100 returns 422.

### Error body — RFC 9457 (`application/problem+json`)

```json
{
  "type": "https://api.example.com/problems/validation-error",
  "title": "Validation Error",
  "status": 422,
  "detail": "email: value is not a valid email address",
  "errors": [{ "field": "email", "message": "value is not a valid email address" }],
  "code": "duplicate_email"
}
```

| Source | Status | Notes |
|---|---|---|
| Validation | 422 | `errors[]` per field; `detail` is the first three joined |
| Auth middleware | 401 | `code=authentication_required`, header `X-Auth: required` |
| RBAC | 403 | `code=insufficient_role`, `your_role` |
| Unique email `IntegrityError` | 409 | `code=duplicate_email` |
| Foreign key violation | 409 | `code=missing_reference` |
| Other constraint | 409 | `code=constraint_violation` |
| Wrong method | 405 | `Allow` header rebuilt from the OpenAPI paths |
| Other `SQLAlchemyError` | 503 | — |
| Unhandled exception | 500 | Includes a `request_id` |

### Other conventions

- **Idempotency:** the `Idempotency-Key` header on submission creates. The
  stored response is replayed for 24 h.
- **HTTP methods:** mutations never take query parameters; options go in the
  body (e.g. `{"force": true}`, `{"note": "…"}`).
- **Field naming:** snake_case; units in key names (`volume_m3`,
  `estimated_weight_kg`, `elapsed_seconds`); geometry as `{x, y, w, h}` rects.

---

## 12. Data model and migrations

### 12.1 Entity relationships

```mermaid
erDiagram
    USERS ||--o{ INSPECTIONS : owns
    USERS ||--o{ INSPECTIONS : reviews
    CARGO_TYPES ||--o{ INSPECTIONS : classifies
    INSPECTIONS ||--o{ INSPECTION_TAGS : has
    TAGS ||--o{ INSPECTION_TAGS : labels
    USERS ||--o{ AUDIT_LOG : acts
    USERS {
        int id PK
        string name
        string email "unique on lower(email)"
        string phone "digits only"
        bool is_active
        string role "user|admin (CHECK)"
        string password_hash
        datetime password_set_at
        datetime last_login_at
        datetime created_at
    }
    INSPECTIONS {
        int id PK
        int user_id FK
        int reviewed_by FK
        datetime reviewed_at
        int cargo_type_id FK
        string status "draft|submitted|approved|rejected"
        string status_note
        string notes
        float volume_m3
        float estimated_weight_kg
        jsonb detection_result
        datetime detected_at
        string detection_overlay
        jsonb decision_result
        datetime decided_at
        string image_filename
        string image_original_name
        string image_content_type
        int image_size_bytes
        int image_width
        int image_height
        datetime created_at
        datetime updated_at
        datetime deleted_at "soft delete"
    }
    CARGO_TYPES {
        int id PK
        string slug UK
        string label
        float density_kg_m3
        string description
    }
    TAGS {
        int id PK
        string name UK
        string colour
        datetime created_at
    }
    INSPECTION_TAGS {
        int inspection_id PK
        int tag_id PK
    }
    AUDIT_LOG {
        int id PK
        int actor_user_id FK
        string action
        string entity_type
        int entity_id
        jsonb detail
        datetime created_at
    }
    IDEMPOTENCY_KEYS {
        string key PK
        string endpoint
        int status_code
        jsonb response
        datetime created_at
        datetime expires_at
    }
```

### 12.2 Seeded cargo types (migration 0007)

| slug | label | density kg/m³ |
|---|---|---|
| `scrap-steel` | Scrap steel | 7850 |
| `thermal-coal` | Thermal coal | 800 |
| `construction-gravel` | Construction gravel | 1700 |
| `agricultural-grain` | Agricultural grain | 750 |
| `other` | Other | — (fallback for unknown slugs) |

> These bulk-material types do not match the cargo in the real port lifting
> plans (containers, boom lifts, gen sets, drums, nets, IBCs …). See
> [`Lifting_Plan_Reference.md`](Lifting_Plan_Reference.md) §6.

### 12.3 Notable indexes and constraints

- `uq_users_email_lower`: unique functional index on `lower(email)`.
- `ck_users_role`, `ck_inspections_status`: CHECK constraints.
- Partial indexes on live rows (`deleted_at IS NULL`):
  - `ix_inspections_created_at_live`
  - `ix_inspections_pending_review` (`status='submitted'`)
  - `ix_inspections_detected_at`
  - `ix_inspections_decided_at`
- `ix_users_password_hash` is partial (`WHERE password_hash IS NOT NULL`).
- `inspection_tags` cascades on delete from both sides.
- `ix_audit_log_entity` on `(entity_type, entity_id)`.

### 12.4 Derived fields on `Inspection`

| Field | Values |
|---|---|
| `detection_status` | `not_run` · `error` · `detected` · `no_cargo` |
| `decision_status` | `not_run` · `ok` · `error` |
| `ai_recommendation` | `approve` · `review` |
| `ai_answers` | Answers from `decision_result` |
| `cargo_object_count` | Object count from `detection_result` |
| `cargo_label`, `density_kg_m3` | From the linked cargo type |

### 12.5 Migration history (linear)

| # | Revision | Change |
|---|---|---|
| 1 | `0001_initial` | `users` + `addresses` (original scaffold) |
| 2 | `0002_create_inspections` | `inspections` with free-text name/email/cargo_type + image columns |
| 3 | `0003_link_inspections_to_users` | `user_id` FK (backfilled by email), drop name/email |
| 4 | `0004_add_phone_drop_addresses` | `users.phone`; drop `addresses` |
| 5 | `0005_email_lower_unique` | De-duplicate users; unique `lower(email)` |
| 6 | `0006_status_soft_delete` | `status`, `status_note`, `updated_at`, `deleted_at`, CHECK, partial index |
| 7 | `0007_cargo_types_lookup` | `cargo_types` lookup + seed; `cargo_type_id` FK |
| 8 | `0008_tags_audit_and_idempotency` | `tags`, `inspection_tags`, `audit_log`, `idempotency_keys`, weight/volume columns, `users.created_at` |
| 9 | `0009_user_credentials` | `password_hash`, `password_set_at`, `last_login_at`, `is_admin` |
| 10 | `0010_roles_and_reviews` | `role` replaces `is_admin`; `reviewed_by`, `reviewed_at`; pending-review index |
| 11 | `0011_detection_results` | `detection_result` JSONB, `detected_at`, `detection_overlay` |
| 12 | `0012_ai_decision` | `decision_result` JSONB, `decided_at` |

Every revision has a working `downgrade()`. `alembic/env.py` imports the
**app's engine**, so app and migrations can never target different databases;
`alembic.ini` has no `sqlalchemy.url`.

---

## 13. Business logic (services)

| Service | Responsibilities |
|---|---|
| `auth_service` | Register (case-insensitive unique email, password policy), authenticate (timing-safe, audited), set/change password |
| `inspection_service` | See the breakdown below |
| `query` | `paginate()`: `COUNT(*)` subquery plus offset/limit; clamps `limit` to 1–100 |
| `idempotency_service` | Look up and store responses by `(key, endpoint)`; 24 h retention; expired rows are deleted on lookup |
| `audit_service` | `record()` adds an `AuditLog` row inside the caller's transaction |
| `rbac` | Roles, permission sets, dependency factories (`require_permission` …) |
| `detection` | Subprocess orchestration, semaphore, timeout, overlay persistence, run cleanup (§14) |
| `openai_decision` | Rubric, HTTP call with retries, recommendation (§15) |
| `lifting_plan` | Builds the plan dict and renders Markdown (§16) |
| `health_service` | `SELECT 1` with latency |
| `user_service` | User CRUD and deactivation. **Mostly unused by routes** |

**`inspection_service` in detail**

- **Upload validation:** PNG, JPEG, WebP or GIF; at most 10 MB; not empty.
  Width and height are parsed from the file header without an imaging
  library.
- **Storage:** files are saved as `storage/inspections/<uuid4hex><ext>`.
- **Create:** resolves or creates the user by email, resolves the cargo type
  (falling back to `other`), and gets or creates tags.
- **Listing:** filters by user, cargo type, status, tag and search (ILIKE on
  notes, file name, user name and email). Sorting is whitelisted to
  `created_at`, `updated_at`, `status` and `id`. Related rows are loaded with
  `selectinload`, so there are no N+1 queries.
- **Delete and restore:** soft delete, restore, and hard delete (which also
  removes the image file).
- **Aggregates:** `stats()`, `summary_by_user()`, and users with no
  submissions (NOT EXISTS).
- **AI decision:** `_apply_ai_decision()` runs after the create commits and
  **never raises**.

**Audit actions**

| Entity | Actions |
|---|---|
| Users | `register`, `login`, `login_failed`, `set_password`, `set_role`, `create`, `update`, `deactivate` |
| Inspections | `create`, `update`, `soft_delete`, `restore`, `hard_delete`, `approved`, `rejected`, `ai_decision` |

---

## 14. Cargo detection pipeline (YOLO + SAM)

### 14.1 Why a subprocess

The ML stack (torch, ultralytics, segment-anything, transformers, Open3D) needs
about 5.5 GB and conflicts with the app's environment. The API therefore
launches a separate interpreter, and the two sides communicate only through a
JSON file. A detector failure never affects uploads.

```text
POST /detect
  └─ app/services/detection.py
       ├─ checks: enabled? interpreter exists? Revamping.ipynb exists? runner exists?
       ├─ non-blocking semaphore (max 1) → 503 "Detection Busy"
       └─ $DETECTION_PYTHON scripts/detect_runner.py --image <abs> --out-dir storage/detection/run_<ts>_<hex>
              env: CARGO_PROJECT_DIR, MPLBACKEND=Agg, CARGO_DEBUG=0, CARGO_PROGRESS=0
            └─ executes notebook cells 2, 4, 7, 8, 8b, 8c, 9, 10 in one namespace
               (CELL 3 file picker replaced by image_paths=[image]; %/! magics stripped)
            └─ parses CELL 10 stdout with regexes → result.json + overlay.png
       ├─ overlay copied to storage/detection/overlays/inspection_<id>_<hex>.png
       ├─ result saved to inspections.detection_result (JSONB)
       └─ cleanup_runs(keep=20)
```

### 14.2 Pipeline stages (notebook `detector/Revamping.ipynb`)

| Step | Cells | What happens |
|---|---|---|
| 1. Select | 3 | 1–3 images. The API passes exactly one |
| 2. Quality | 5 | Blur (Laplacian), brightness, resolution report *(not run by the API)* |
| 3. Models | 7 | YOLO weights in priority order: `cargo_yolo11_best.pt` → **`cargo_obb_best.pt`** (in use) → `yolo11m.pt` (COCO fallback). SAM 3 is attempted and falls back to **SAM 1 ViT-B** (`sam_vit_b_01ec64.pth`, ~358 MB, downloaded on first run) |
| 4. Detect | 8, 8b | YOLO inference, suspended-load clustering, ground-detection rejection, exclusion zones |
| 5. Prompt | 8c | Dynamic load-region estimate, then box/point prompts for SAM |
| 6. Segment | 9 | Crop/upscale → SAM multimask → weighted ranking → reject the net → tight box and OBB |
| 7. Judge | 10 | Acceptance gate, then the overlay is drawn (orange mask, red box) |
| 8. Measure | 11–28 | Pixel geometry, reference scale, Depth-Anything depth, Open3D volume, density × volume weight. **Not executed by the API** |

**Cargo taxonomy** (8 classes, from a Roboflow dataset)

| Role | Classes |
|---|---|
| Targets | `Cargo-Box`, `Wooden-Plate` |
| Envelope (fallback only) | `Cargo-Detection` |
| Excluded | `Net`, `Strap`, `Chain`, `Crane`, `Hook` |

### 14.3 Key thresholds

| Stage | Constant | Value |
|---|---|---|
| YOLO confidence (custom taxonomy / COCO fallback) | `CARGO_CONF_ZIP_TAXONOMY` / `CARGO_CONF_COCO_FALLBACK` | 0.30 / 0.15 |
| Minimum box | `MIN_CARGO_BOX_PX` / `MIN_CARGO_AREA_FRACTION` | 12 px / 0.2% of frame |
| SAM 3 confidence | `SAM3_CONF_THRESHOLD` | 0.20 |
| SAM auto-mask (fallback) | `POINTS_PER_SIDE` / `PRED_IOU_THRESH` / `STABILITY_THRESH` | 12 / 0.82 / 0.88 |
| Ranking weights | SAM / IoU / fill / exclusion | 5.0 / 4.0 / 2.0 / 3.0 |
| **Acceptance gate** | `MIN_ACCEPT_SCORE` | **6.0** |
| | `MAX_ACCEPT_BOX_FRACTION` | **0.60** of frame |
| | `MAX_ACCEPT_BORDER_LEAK` | **0.12** (3-px border) |

### 14.4 Outcomes

| Outcome | HTTP | `detection_status` |
|---|---|---|
| Cargo accepted | 200 | `detected` |
| Candidates refused by the gate / no candidates | 200 | `no_cargo` (an honest "no confident cargo found") |
| Pipeline crashed (`ok:false`) | 502 (result still saved) | `error` |
| Disabled / interpreter missing / busy | 503 | unchanged |
| Timeout (300 s) | 504 | `error` (`timed_out:true`) |

**Result payload** (`data`):

- `detected`, `label`, `aggregate_score`
- `objects[]`: each object has `label`, `yolo_confidence`, `sam_score`, `mask_area_px`, `box`, and `models{yolo, sam}`
- `box`, `mask{area_ratio, border_leak}`
- `detector_origin`, `uses_zip_taxonomy`, `stage`, `timed_out`

`meta` holds the timing, the image size and the overlay link.

### 14.5 What it does *not* do

- **No metric volume or weight.** The measurement cells produce *relative*
  volume from normalised intrinsics, so `volume_m3` and
  `estimated_weight_kg` stay `null` rather than holding dimensionless
  numbers. Metres come only from the lifting-plan reference (`ref_m`/`ref_px`).
- **Known false positives.** Example: a man-and-dog photo. Retraining on a
  ship scene raised the crane false-positive confidence from 0.76 to 0.84
  (`detector/README.md`). Model quality on that scene is a data problem.
- Typical run time is **16–45 s on CPU**. One verified end-to-end run scored
  16.3 in 27 s.

### 14.6 Model training notes (`detector/README.md`, `docs/Working.md`)

- **Dataset:** `Cargo-Detection.v3i.yolov8-obb.zip`, 90 files / 18 scenes.
  Split by scene: validation share 0.30, seed 42, with a leakage guard.
- **Best weights:** `cargo_obb_retrain_batch2`, best epoch 7, val mAP50 0.502.
- **Proposal target:** about 500–800 images per category for a 50–60%
  accuracy PoC.
- **Re-vendoring:** copy the notebook and weights from the upstream project,
  then run `pytest tests/test_detection.py::TestRunnerContract -q`.

---

## 15. AI decision (OpenAI Decisions API)

| Item | Value |
|---|---|
| Endpoint | `POST https://api.openai.com/v1/decisions` (httpx, Bearer key) |
| Model | `gpt-6-luna` |
| When | Right after a submission is created (if enabled) |
| Input | Text `"Photo uploaded to a cargo inspection portal. Declared cargo type: {label}."` + image as a base64 data URL |
| Rubric v1 | `cargo_present` (predicate) · `cargo_type` (choice: containers, bulk, hazardous, other, none) · `matches_declaration` (predicate) |
| Decision | `approve` only if **both** `cargo_present` and `matches_declaration` probabilities are ≥ `OPENAI_DECISION_MIN_CONFIDENCE` (0.8, inclusive); otherwise `review` |
| Auto-approve | Only when the status is `submitted` (drafts are never auto-approved). Sets a `status_note` explaining why |
| Retries | 2 attempts. Retried: connect errors/timeouts, 429/500/502/503/504 (honours `Retry-After`, capped at 2 s). Read timeout fails immediately |
| Stored | `decision_result` JSONB: `{ok, model, rubric_version, recommendation, auto_approved, threshold, answers, usage}` or `{ok:false, error}`; `decided_at`; audit `ai_decision` |
| Failure | Never fails the upload. The submission stays in the manual review queue |

---

## 16. Lifting plan generator

`GET /api/v1/portal/submissions/{id}/lifting-plan?ref_m=1.2&ref_px=340&format=markdown`

Requires a stored detection with `detection_status = detected`. Nothing is
persisted; the plan is generated on each request. Output follows the
**HSE-F003** form layout used by the client (see
[`Lifting_Plan_Reference.md`](Lifting_Plan_Reference.md)).

### 16.1 Calculations (`app/services/lifting_plan.py`)

| Quantity | Formula | Tag |
|---|---|---|
| Description | `"{object_count} × {label} ({cargo label})"` | `[AI]` |
| Scale | `m_per_px = ref_m / ref_px` (only if both are given) | — |
| Length / height | `L = box_w_px × m_per_px`, `H = box_h_px × m_per_px` (2 dp) | `[AI-ESTIMATE]` |
| Width | **Always blank**; depth is not visible in one photo | — |
| Weight | `round(density × L × min(L,H) × H)`. W is assumed to equal the smaller visible dimension. Only if the cargo type has a density | `[AI-ESTIMATE]` + warning |
| Centre of gravity | Centre of the detected box (uniform mass assumed) | `[AI-THEORETICAL]` |
| 2-leg bridle | Half-span `w = box_w/2`, sling length `L = 2.0 × box_h`. If `L ≤ w`, no rigging is possible. Otherwise `r = √(L² − w²)`, hook at `(cog_x, top − r)`, angle from vertical `θ = atan(w/r)`, from horizontal `90° − θ` (pixel units) | `[AI-THEORETICAL]` |

### 16.2 What the output covers

| HSE-F003 section | Generated? |
|---|---|
| Part 1 – General information | ❌ Not rendered |
| Part 2 – Details of load | ✅ Description, dimensions (L, H), weight estimate, CoG/rigging sketch, method checkboxes left blank |
| Part 3 – Equipment / gears / load calculation | ⚪ Rendered as **blank** tables |
| Part 4 – Drawing / sketch | ✅ Link to the detection overlay + ASCII rigging sketch |
| Part 5 – Communication / personnel | ❌ Not rendered |
| Part 7 – Physical & environmental | ❌ Not rendered |
| Part 8 – Signatures | ❌ Not rendered |

The response is Markdown (`text/markdown`, downloaded as
`lifting-plan-{id}.md`) or JSON (`data` + `meta.generated_at`). The warning
constants `WARN_ESTIMATE_USED_PCT=75`, `WARN_ABSOLUTE_USED_PCT=90` and
`WARN_SAFETY_FACTOR=1.5` are defined but **not yet used**.
[`Lifting_Plan_Reference.md`](Lifting_Plan_Reference.md) §7 shows how they map
onto the form's load calculation.

---

## 17. Web portal (static UI)

`static/index.html` is served at **`/ui/`**. It is one file of vanilla JS that
talks to `/api/v1`.

| Area | Features | Endpoints |
|---|---|---|
| Boot / auth | Calls `/auth/me` on load; sign-in / register form; logout. httpOnly cookie, nothing stored client-side | `/auth/me`, `/auth/login`, `/auth/register`, `/auth/logout` |
| My submissions | Stat tiles (total, approved, rejected, kg); debounced search; cargo filter; card grid with images; pagination; withdraw | `/portal/summary`, `/portal/submissions`, `…/{id}/image`, `DELETE …/{id}` |
| Upload | Cargo dropdown with density; draft/submitted; tags; notes; drag-and-drop with preview; 10 MB client check; `Idempotency-Key` sent | `/portal/cargo-types`, `POST /portal/submissions` |
| Admin (if `is_admin`) | Stats; queue with search/status filter; approve/reject per card; bulk select; AI hint (`cargo_present` probability, recommendation) | `/admin/stats`, `/admin/submissions`, `…/approve`, `…/reject`, `…/bulk` |

The response wrapper understands both the success envelope and problem
documents, and shows 422 field errors inline.

**Not in the UI yet:**

- a detection trigger or result view
- the overlay viewer
- a lifting-plan download
- admin user management
- the audit log

All of these exist as API endpoints only.

---

## 18. Known gaps, inconsistencies and stale docs

### 18.1 Code behaviour worth knowing

1. **CORS order:** CORS is the innermost middleware. A cross-origin
   preflight to `/api/v1/portal|admin` without a cookie gets a 401, and 401
   and 403 responses carry no CORS headers. The comment in `main.py` claims
   the opposite. Same-origin use (`/ui`) is unaffected.
2. **Idempotency:**
   - Keys are not scoped per user.
   - The request body is not fingerprinted, so reusing a key with a
     different body replays the first response.
   - Two concurrent first requests can both execute.
   - The admin and portal endpoint strings differ by a trailing slash.
   - `purge_expired()` is never scheduled.
3. **Audit:**
   - `update`, `soft_delete`, `restore` and `hard_delete` record no actor.
   - `previous_status` on approve/reject is always null.
   - AI auto-approval leaves `reviewed_by` NULL.
4. **Admin create** is gated by `submissions:read:any`, not
   `submissions:create`.
5. **Purge** deletes the image but not the detection overlay file.
6. **Portal list:** an invalid `status` or `sort` raises an unhandled
   `ValueError` instead of returning 422 (the admin list handles it).
7. **Detection log:** `returncode` is synthesised, and `stdout.log` is only
   written on timeout, so the log tail is usually empty.
8. **`stats.pending`** counts drafts as well as submitted rows.
9. **Unhandled 500s** return a freshly generated `request_id`, not the
   `X-Request-ID` header value.
10. **Session lifetime:** `create_access_token` and `set_session_cookie`
    default to 12 h rather than reading `JWT_EXPIRES_HOURS` directly.
11. **Phone validation:** the register `phone` field is a plain string and
    is not normalised; user schemas do normalise phone numbers.
12. **Rendered lifting plan:** the "Centre of Gravity" block appears twice
    when rigging is available.
13. **No login rate limiting, no refresh tokens, local-disk storage only.**
    Running on more than one server needs shared or object storage.

### 18.2 Documents that disagree with the code

| Document | What is stale |
|---|---|
| `README.md` | Data model, examples and flow charts still describe the **User/Address** API. Says migration head is `0002`; it is `0012`. Main path is `-m services.detection`; should be `app.services.detection` |
| `docs/ARCHITECTURE_FLOW.md` | Original Users/Addresses scaffold on SQLite |
| `docs/Alembic.md` | Written for the SQLite era with `sqlalchemy.url` in `alembic.ini` |
| `docs/POSTGRES.md`, `POSTGRES_COMMANDS.md` | Schema at 0002 with an `addresses` table |
| `docs/Flow.md` | Written at 0010; mentions `/inspections/**` and `GET /users/` surfaces that no longer exist |
| `docs/openai_decision_api.md` | Says "not implemented" and calls the detector "YOLACT-style" |
| `docs/openai_decision_api_implementation.md` | Proposed design (SDK, enum columns, post-detection); what was built differs (httpx, JSONB, on upload) |
| `docs/working_deps_libs.md` | Omits psycopg, pydantic-settings, pyjwt and httpx |
| `docs/LIFTING_PLAN.md` | Describes a UI button that is not built; has mojibake |
| Several docs | Reference non-existent paths such as `app/services/services/…`, `app/api/v1/endpoints/routers/…` |
| Test counts in docs | 53 / 150 / 248 / 284. Actual is **322** total, 56 for detection |
| `Technical_Document.md` | Lists the following as user features, but none are implemented: automatic detection on upload, editing a draft or resubmitting, catalogue management, user activate/deactivate in the UI, and volume estimation by vision |
| `cell_9_clean.py` | Byte-identical to notebook **CELL 2**, not CELL 9 |
| `requirements.txt` | Pins conflict with `pyproject.toml` |
| `.gitignore` | Does not cover root `cargo_output_visualizations/` or `detector/datasets/`. `__pycache__/*.pyc` files are already committed |

---

## 19. Running, testing and operations

### 19.1 First-time setup (Windows / PowerShell)

```powershell
cd C:\Users\Abhijeet\Desktop\FastAPI\awesome-project
uv sync                                                    # 1. dependencies
Copy-Item .env.example .env                                # 2. config (set JWT_SECRET!)
powershell -ExecutionPolicy Bypass -File scripts\start_postgres.ps1   # 3. PostgreSQL 17
uv run python scripts\setup_postgres.py                    # 4. create DB + alembic upgrade head
uv run python scripts\create_admin.py --email admin@example.com --name Admin --password <pw>  # 5. first admin
uv run uvicorn main:app --reload                           # 6. run
```

Then open the portal at <http://127.0.0.1:8000/ui/> and Swagger at
<http://127.0.0.1:8000/docs>.

### 19.2 Enabling detection

```ini
DETECTION_ENABLED=true
DETECTION_PYTHON=C:\path\to\AI-Driven Cargo Detection\.venv\Scripts\python.exe
```

Check the paths without starting the server:
`.venv\Scripts\python.exe -m app.services.detection`. Make sure
`detector/models/sam_vit_b_01ec64.pth` exists, or let cell 7a download it.

### 19.3 Scripts

| Script | Purpose |
|---|---|
| `scripts/setup_postgres.py [--reset] [--password]` | Create or reset the DB and run migrations; idempotent |
| `scripts/start_postgres.ps1` | Check/start the `postgresql-x64-17` service. Exit 0 OK · 1 missing/failed · 2 not elevated · 3 not accepting |
| `scripts/create_admin.py` | `--email --name --password --role`, `--demote`, `--list`. Uses the API's password rules and writes an audit entry |
| `scripts/detect_runner.py` | Headless detector, run by the API in the ML venv |
| `scripts/regen_openapi.py` | Regenerate `docs/API_CONVENTIONS.md` §9 after route changes |
| `scripts/cell10_probe*.py` | Debug probes for the CELL 10 acceptance gate (`_full` matches the real pipeline, including CELL 9) |

### 19.4 Migrations

```powershell
uv run alembic revision --autogenerate -m "describe change"   # review the script!
uv run alembic upgrade head
uv run alembic downgrade -1
uv run python scripts\setup_postgres.py --reset --password postgres   # start over
```

### 19.5 Tests

```powershell
.venv\Scripts\python.exe -m pytest tests/ -q
```

- **Database:** tests run against real PostgreSQL. A session fixture drops
  and recreates `awesome_project_test` and runs `alembic upgrade head`. Each
  test runs inside a transaction that is rolled back.
- **External services:** OpenAI is forced off, and image storage is
  redirected to a temp directory.

| File | Tests | Focus |
|---|---:|---|
| `test_api_contract.py` | 26 | `/api/v1` prefix, method rules, links resolve, docs ↔ OpenAPI sync |
| `test_auth_portal.py` | 52 | Hashing, register/login, cookie, isolation, uploads, idempotency |
| `test_bug_regressions.py` | 20 | Pagination bounds, case-insensitive email, 405 `Allow`, ISO UTC |
| `test_detection.py` | 56 | Availability, outcomes 200/502/503/504, caching, `force`, path traversal, runner contract |
| `test_docs_auth.py` | 20 | Bearer scheme in OpenAPI; cookie beats header |
| `test_lifting_plan.py` | 24 | 422 refusals, Markdown/JSON, calibration, weight, rigging geometry |
| `test_openai_decision.py` | 19 | Rubric, threshold gate, auto-approve, failure fallback |
| `test_query_patterns.py` | 36 | No N+1, filters, sort whitelist, soft delete, aggregates, audit |
| `test_rbac.py` | 50 | Permissions, 401/403, review flow, self-approval blocked |
| `test_ui_contract.py` | 19 | Every JSON path `index.html` reads |
| **Total** | **322** | |

### 19.6 Storage layout (gitignored)

```text
storage/
├── inspections/<uuid>.<ext>                       uploaded images
├── detection/run_<YYYYMMDD_HHMMSS>_<hex>/         per-run result.json, overlay.png (last 20 kept)
├── detection/overlays/inspection_<id>_<hex>.png   persisted overlays
└── tested_images/                                 probe/debug outputs
```

---

## 20. Assumptions (plain language)

Condensed from `Understanding_Document.md`.

| # | Assumption | If wrong |
|---|---|---|
| A1 | One true reference size is supplied (`ref_m`/`ref_px`) | 10% ruler error ≈ 30% volume/weight error |
| A2 | Weight = volume × typical density, an estimate only | Overloading risk if trusted as certified |
| A3 | Depth (W) cannot be measured from one photo; it is left blank or assumed to be the smaller visible side | Odd shapes are mis-estimated |
| A4 | The first photo is the main one | Use the best, front-facing, well-lit photo |
| A5 | Weight is cargo-as-seen (net, pallet and slings included) | The engineer subtracts tare |
| A6 | Load hangs freely and is fully visible | Cropping or ground contact breaks detection |
| A7 | Photos are clear, lit and large enough | Honest "no cargo" rather than a guess |
| A8 | CoG assumes uniform mass and a standard 2-leg sling | Lopsided loads shift the true CoG |
| A9 | The operator picks the correct cargo type | Wrong density means a wrong weight |
| A10 | Catalogue density is typical, not measured | Sample critical lifts |
| A11 | The fallback YOLO (COCO) is general, not cargo-tuned | Treat fallback results with caution |
| A12 | People own crane, method and go/no-go | Never auto-filled |
| A13 | Storage, hosting and retraining are ongoing costs | Budget for operations, not only setup |

Running costs (from the proposal): hosting, compute for vision, storage
growth, maintenance, retraining for new cargo types, and app-store accounts.
The vision models are open source, so there is **no per-photo AI fee**; the
optional OpenAI decision step is the only metered call. The timeline is kept
in the shared planning sheet
([AI-Cargo-Project-Timeline](https://docs.google.com/spreadsheets/d/1cFk0qRtuzduAzVEXRNuuwc5FzKoXi0fjxX9oodNa39M/edit?usp=sharing)).

---

## 21. Roadmap

Suggested order:

1. **Fix the CORS middleware order** and route `ValueError` to 422 on the
   portal list.
2. **Portal UI for detection and the lifting plan:** Detect button, overlay
   view, reference-size input, and "Download lifting plan".
3. **Align the cargo catalogue with port cargo:** containers, boom lifts, gen
   sets, drums, nets, IBCs. Add per-type typical weight ranges where density
   does not apply (see `Lifting_Plan_Reference.md`).
4. **Load-calculation helper:** when the engineer enters crane capacity (a)
   and hook/gear weight (c), compute total weight (d), SF = a/d and
   utilisation = d/a. Wire up the unused `WARN_*` constants (SF < 1.5,
   utilisation > 75% / 90%).
5. **Render Parts 1, 5, 7 and 8** of HSE-F003 as blank sections so the draft
   is a complete form.
6. **Idempotency:** scope keys per user, add a request hash, return 422/409
   on mismatch, schedule `purge_expired()`.
7. **Audit:** record the actor and previous status everywhere.
8. **Security:** login rate limiting, refresh tokens, a mandatory `JWT_SECRET`
   in production.
9. **Storage:** object storage (S3-compatible) for multi-instance
   deployment; remove overlays on purge.
10. **Detection quality:** more training data per scene; run the measurement
    cells once metric calibration is reliable; async jobs (`202 Accepted`)
    instead of 16–45 s blocking calls.
11. **Housekeeping:**
    - Refresh the stale docs listed in §18.2.
    - Regenerate `requirements.txt`.
    - Untrack `__pycache__`.
    - Rename `cell_9_clean.py`.
12. **Client vision:** React dashboard and Android handheld app on top of
    this API.

---

## 22. Glossary

| Term | Meaning |
|---|---|
| Submission / Inspection | One upload: photo + cargo type + notes + tags + status |
| Overlay | Copy of the photo with the detected mask (orange) and box (red) drawn on it |
| YOLO-OBB | "You Only Look Once" detector with oriented bounding boxes |
| SAM | Meta's Segment Anything Model: outlines an object from a box or point prompt |
| Acceptance gate | CELL 10 rule: score ≥ 6.0, box ≤ 60% of frame, border leak ≤ 0.12 |
| CoG | Centre of gravity |
| SWL | Safe working load |
| SF | Safety factor = crane lifting capacity ÷ total load |
| HSE-F003 | The client's lifting-plan form |
| RFC 9457 | Standard JSON format for HTTP error responses |
| Idempotency key | Client-generated header so retries do not create duplicates |
| Soft delete | Hide a row via `deleted_at` instead of removing it |
| JSONB | PostgreSQL binary JSON column |

---

## 23. Document index

| Document | Audience | Status |
|---|---|---|
| `Complete.md` (this) | Everyone | **Current** |
| `Lifting_Plan_Reference.md` | Engineers, product, client | **Current**: HSE-F003 analysis |
| `Technical_Document.md` | Technical stakeholders | Mostly current (see §18.2) |
| `Understanding_Document.md` | Non-technical stakeholders | Current |
| `docs/API_CONVENTIONS.md` | API consumers | Current; §9 auto-generated |
| `docs/API_METHOD_AUDIT.md` | Developers | Current |
| `docs/API_VERSIONING_PLAN.md` | Developers | Implemented record |
| `docs/DETECTION.md` | Developers | Current (minor path/count drift) |
| `docs/LIFTING_PLAN.md`, `LIFTING_PLAN_AI_SCOPE.md` | Developers, client | Current design; the UI part is not built |
| `docs/Final_Working.md` | Client | Current |
| `docs/AI-Based Cargo Identification _ NewGene.md` | Client | Proposal / vision |
| `docs/Working.md` | ML developers | Upstream notebook guide |
| `docs/Flow.md` | Developers | Partly stale (at 0010) |
| `docs/POSTGRES.md`, `POSTGRES_COMMANDS.md` | Ops | Commands OK; schema section stale |
| `docs/Alembic.md`, `ARCHITECTURE_FLOW.md`, `working_deps_libs.md`, `openai_decision_api*.md` | — | Stale / historical |
| `README.md` | Newcomers | Partly stale |
| `detector/README.md` | ML developers | Current |

---

*End of Complete.md*
