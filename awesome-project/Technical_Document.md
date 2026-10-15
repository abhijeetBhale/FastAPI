# Technical Document — AI Cargo Inspection & Lifting Plan Platform

> **Version:** 2.0.0 · **Last reviewed:** 2026-10-15 · **Audience:** Technical stakeholders and engineers

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture](#2-architecture)
3. [Technology Stack](#3-technology-stack)
4. [Dependencies & Libraries](#4-dependencies--libraries)
5. [User Flows & State Machines](#5-user-flows--state-machines)
6. [API Layer](#6-api-layer)
7. [Security & Authentication](#7-security--authentication)
8. [Data Model](#8-data-model)
9. [Detection Pipeline — YOLO + SAM](#9-detection-pipeline--yolo--sam)
10. [AI Decision Gate — OpenAI](#10-ai-decision-gate--openai)
11. [Lifting Plan Generator](#11-lifting-plan-generator)
12. [Configuration Reference](#12-configuration-reference)
13. [Testing](#13-testing)
14. [Known Limitations & Roadmap](#14-known-limitations--roadmap)

---

## 1. Project Overview

The platform automates the front-end of port cargo lifting operations. Before any heavy lift, a safety document called a **lifting plan** (form HSE-F003) must be filled in. Historically this is done manually, by eye, on site. This system replaces the estimation and form-drafting work with a computer-vision pipeline while keeping all safety decisions firmly with a human engineer.

### What it delivers today

| Capability | Status |
|---|---|
| User registration, login, role-based access control | ✅ Live |
| Cargo image upload with type, notes, tags | ✅ Live |
| YOLO-OBB + SAM cargo detection (subprocess) | ✅ Live (enabled via `.env`) |
| OpenAI rubric-based auto-approval | ✅ Live (enabled via `.env`) |
| HSE-F003 lifting plan draft (Markdown / JSON) | ✅ Live |
| Admin review queue, bulk actions, audit log | ✅ Live |
| Vanilla-JS browser portal | ✅ Live (at `/ui/`) |
| React dashboard, Android app | ❌ Proposal only |

### Golden rule

> The system reports what it saw and suggests a starting point. It never decides whether a lift is safe. A person always decides and signs off.

---

## 2. Architecture

### 2.1 Layer diagram

```text
HTTP layer         app/api/v1/endpoints/     Routing, status codes, no business logic
Validation layer   app/schemas/              Pydantic request / response models
Business layer     app/services/             Rules, transactions, audit
Data layer         app/models/ + app/database/
Database           PostgreSQL 17 via psycopg 3
External           Detector subprocess  ·  OpenAI Decisions API  ·  Local disk storage/
```

### 2.2 Runtime diagram

```text
 Browser (/ui)  ·  Swagger (/docs)  ·  curl / API client
          │  JSON / multipart, httpOnly cookie or Bearer token
          ▼
 Uvicorn (uvloop + httptools)
          │
          ▼
 RequestContextMiddleware   →  assigns X-Request-ID, measures response time
          │
          ▼
 AuthenticationMiddleware   →  validates JWT from cookie or Authorization: Bearer
          │                     missing / invalid  →  401
          ▼
 RoleAuthorizationMiddleware  →  on /admin/*: reads role from DB on every request
          │                       not admin  →  403 · user gone/inactive  →  401
          ▼
 CORSMiddleware   (innermost — see §14 for the CORS ordering caveat)
          │
          ▼
 Router  →  Endpoint  →  Service layer
                              │              │                │
                              ▼              ▼                ▼
                        PostgreSQL    Detector subprocess   OpenAI /v1/decisions
                        (SQLAlchemy)  (detect_runner.py)   (httpx, retries)
                                           │
                                           ▼
                                   storage/detection/…
```

### 2.3 Startup sequence (`main.py`)

1. Load settings (`pydantic-settings` from `.env` / environment).
2. Configure INFO logging.
3. Instantiate `FastAPI(title, version, lifespan=…)` with built-in `/docs` disabled.
4. Register, in order: `CORSMiddleware`, exception handlers, `install_middlewares()`, `/api/v1` router, unversioned health router, `/ui` static mount, custom `/docs` (operations sorted GET→POST→PUT→PATCH→DELETE), `GET /`.
5. On startup: log app version and DB host (credentials stripped). Schema is never auto-created — Alembic owns it.

---

## 3. Technology Stack

### 3.1 Application environment (~120 MB)

| Layer | Technology | Version | Role |
|---|---|---|---|
| Language | Python | 3.12.10 (≥3.12) | Type hints drive validation and docs |
| Web framework | FastAPI | 0.142.2 | Routing, DI, OpenAPI 3.1 |
| ASGI core | Starlette | 1.7.0 | Middleware, static files, lifespan |
| ASGI server | Uvicorn (+ uvloop, httptools) | 0.54.0 | Event loop and HTTP parsing |
| Validation | Pydantic v2 | 2.13.5 | Request/response schemas, JSON schema |
| Settings | pydantic-settings | 2.15.0 | `.env` / environment loading |
| ORM | SQLAlchemy | 2.1.1 | `DeclarativeBase`, `Mapped`, `selectinload` |
| Database | PostgreSQL | 17 | JSONB, partial/functional indexes, transactions |
| DB driver | psycopg 3 (binary) | 3.3.6 | `postgresql+psycopg://` async-compatible |
| Migrations | Alembic (+ Mako) | 1.20.0 | 12 linear revisions, working `downgrade()` |
| Auth tokens | PyJWT | 2.15.1 | HS256, `{sub, email, jti, iat, exp}` |
| Password hashing | stdlib `hashlib` PBKDF2-HMAC-SHA256 | — | 260,000 iterations, 16-byte salt |
| File uploads | python-multipart | 0.0.32 | `UploadFile` / `Form` parsing |
| HTTP client | httpx | 0.28.1 | OpenAI calls and `TestClient` in tests |
| Env manager | uv | — | Deterministic `.venv`, `uv.lock` |
| Tests | pytest | 9.1.1 | 322 tests against real PostgreSQL |

### 3.2 Detection environment (~5.5 GB, separate virtualenv)

| Library | Version / Notes | Purpose |
|---|---|---|
| PyTorch / torchvision | 2.10 + cu128 | Model runtime (CPU or GPU) |
| Ultralytics (YOLO11) | — | YOLO-OBB cargo detector |
| segment-anything | SAM 1 ViT-B (`sam_vit_b_01ec64.pth`, ~358 MB) | Mask segmentation; SAM 3 attempted but falls back |
| OpenCV | — | Image I/O, preprocessing |
| NumPy / SciPy | — | Numerical geometry |
| scikit-image | — | Morphological ops on masks |
| Shapely | — | Polygon geometry |
| transformers (Depth-Anything small) | — | Depth estimation (cells 16–19, not run by API) |
| Open3D | — | Point-cloud volume (cells 20–22, not run by API) |
| Matplotlib (`Agg` backend) | — | Overlay drawing (no display required) |
| Pillow | — | Image loading and overlay export |
| tqdm | — | Progress bars (suppressed in API runs) |

> The two virtualenvs cannot be merged. The app needs ~120 MB; the detector needs ~5.5 GB and a CUDA-specific torch build. They communicate only through a JSON file on disk.

### 3.3 Other components

| Component | Technology |
|---|---|
| Portal UI | `static/index.html` — single-file vanilla HTML/CSS/JS, no build step |
| API docs | Swagger UI (`/docs`, operations sorted), ReDoc (`/redoc`), `/openapi.json` |
| AI decision | OpenAI `POST /v1/decisions`, model `gpt-6-luna`, httpx with retries |

---

## 4. Dependencies & Libraries

### 4.1 Production (`pyproject.toml`)

```toml
dependencies = [
    "alembic>=1.20.0",
    "fastapi[standard]>=0.142.2",   # includes uvicorn, pydantic, starlette
    "httpx>=0.28.0",                # OpenAI calls and TestClient
    "psycopg[binary]>=3.2.0",       # PostgreSQL driver
    "pydantic-settings>=2.5.0",     # .env loading
    "pyjwt>=2.15.1",                # JWT tokens
    "python-multipart>=0.0.20",     # multipart/form-data (file uploads)
    "sqlalchemy>=2.1.1",            # ORM
]
```

`fastapi[standard]` pulls in uvicorn, uvloop, httptools, email-validator, python-multipart and watchfiles transitively.

### 4.2 Development

```toml
[dependency-groups]
dev = [
    "pytest>=9.1.1",
    "pyyaml>=6.0",      # OpenAPI document read/write in tests and scripts
]
```

### 4.3 Detection virtualenv (not in `pyproject.toml`)

Maintained separately in the AI-Driven Cargo Detection project. Key packages: `torch`, `torchvision`, `ultralytics`, `segment-anything`, `opencv-python`, `numpy`, `scipy`, `scikit-image`, `shapely`, `transformers`, `open3d`, `matplotlib`, `pillow`, `tqdm`.

> **Note:** `requirements.txt` in this repo is stale (pins `fastapi==0.115.0`, `sqlalchemy==2.0.35`). Use `uv export` to regenerate it if pip installs are needed.

---

## 5. User Flows & State Machines

### 5.1 Actors and capabilities

| Actor | Role | Key permissions |
|---|---|---|
| Visitor | none | Register, log in, read health/landing/docs |
| Site worker | `user` | Create submissions, view own submissions and results, withdraw |
| Supervisor / reviewer | `admin` | View all submissions, approve/reject/bulk, edit, delete, restore |
| Manager / office | `admin` | Stats, audit log, user role management |
| Lifting engineer | (outside system) | Receives draft lifting plan, fills Category C fields, signs |

### 5.2 End-to-end submission flow

```text
User registers / logs in
        │
        ▼
Upload: POST /api/v1/portal/submissions
  • multipart: image (PNG/JPEG/WebP/GIF, ≤10 MB), cargo_type, status, notes, tags
  • Image dimensions parsed from header (no imaging library required)
  • Stored: storage/inspections/<uuid4hex>.<ext>
  • Row created: status = draft | submitted
        │
        ├──────────────────────────────────────────────────────┐
        ▼                                                       ▼
[OPENAI_DECISION_ENABLED = false]                   [OPENAI_DECISION_ENABLED = true]
decision_status = not_run                           POST /v1/decisions with image + rubric
                                                            │
                                                ┌───────────┴──────────────┐
                                                ▼                          ▼
                                    both gates ≥ 0.8                 low confidence / error
                                    + status = submitted             stays submitted
                                            │                        → manual review queue
                                            ▼
                                    Auto-approved (status=approved)
                                    status_note records the reason
        │
        ▼
[Detection: manual trigger only]
POST /api/v1/portal/submissions/{id}/detect
  • Checks: enabled? interpreter exists? notebook exists? runner exists?
  • Non-blocking semaphore (max 1) → 503 if busy
  • Subprocess: $DETECTION_PYTHON scripts/detect_runner.py --image <abs> --out-dir <run_dir>
  • 16–45 s on CPU (timeout: 300 s)
  • Outcome: detected / no_cargo / error + overlay PNG
        │
        ▼
GET /api/v1/portal/submissions/{id}/lifting-plan?ref_m=&ref_px=&format=markdown|json
  • Requires detection_status = detected
  • Returns HSE-F003 draft (Markdown download or JSON)
        │
        ▼
Lifting engineer: review, fill Category C fields, sign
```

### 5.3 Submission status lifecycle

```text
[draft] ──────────────────────────────────────────────────┐
                                                           │ user sets at creation
[submitted] ◄──────────────────────────────────────────────┘

[submitted]
   │
   ├── AI auto-approve (confidence ≥ 0.8, status = submitted) ──► [approved]
   │
   └── Admin: approve / reject
              │
              ▼
         [approved] / [rejected]

Any status:
   Soft delete → deleted_at set (hidden from normal queries)
   Admin restore → deleted_at = NULL
   Admin purge → hard delete (row + image file)

Note: admin may move between any statuses except to the same one → 409
      users may only set draft or submitted at creation
```

### 5.4 Detection status flow

```text
(never triggered)        → not_run
(ran, cargo found)       → detected       [200 ok:true detected:true]
(ran, nothing found)     → no_cargo       [200 ok:true detected:false]
(pipeline crashed)       → error          [502 ok:false]
(timeout)                → error          [504 timed_out:true]
(disabled / busy)        → unchanged      [503]
```

---

## 6. API Layer

### 6.1 Structure and conventions

- All versioned routes: `/api/v1/{auth|portal|admin}/…`
- Unversioned: `/`, `/health`, `/health/ready`, `/docs`, `/redoc`, `/openapi.json`, `/ui`
- Mutations never take query parameters; options go in the JSON body
- Kebab-case URL segments, snake_case path parameters and JSON fields
- Units in field names: `volume_m3`, `estimated_weight_kg`, `elapsed_seconds`
- Geometry as `{x, y, w, h}` rects

### 6.2 Success envelope

```json
{
  "data": { ... },
  "meta": { "pagination": { "page": 1, "per_page": 20, "total": 57, "total_pages": 3 } },
  "links": { "self": "...", "next": "...", "last": "..." }
}
```

### 6.3 Error body (RFC 9457)

```json
{
  "type": "https://api.example.com/problems/validation-error",
  "title": "Validation Error",
  "status": 422,
  "detail": "email: value is not a valid email address",
  "errors": [{ "field": "email", "message": "..." }],
  "code": "duplicate_email"
}
```

### 6.4 Route summary (44 operations across 38 paths)

| Group | Operations | Auth |
|---|---|---|
| `/api/v1/auth` | register, login, logout, me, set-password, change-password | Public / User |
| `/api/v1/portal` | cargo-types, summary, submissions CRUD, detection, lifting-plan | User (own) |
| `/api/v1/admin` | submissions CRUD + review + bulk, stats, audit, users, cargo-types | Admin |
| `/health`, `/health/ready`, `/` | liveness, readiness, root | Public |

---

## 7. Security & Authentication

### 7.1 Session tokens

- **JWT HS256:** payload `{sub, email, jti, iat, exp}`. No role claim — role is always read from the DB.
- **Transport:** `session_token` cookie (`HttpOnly`, `SameSite=Strict`, `Secure` per `COOKIE_SECURE` config, `path=/`). Bearer header also accepted for Swagger.
- **Lifetime:** 12 hours (`JWT_EXPIRES_HOURS`).
- **Logout:** clears the cookie. No server-side token store — a logout does not invalidate other sessions.

### 7.2 Password security

- PBKDF2-HMAC-SHA256, 260,000 iterations, 16-byte random salt.
- Stored as `pbkdf2_sha256$<iter>$<salt_b64>$<hash_b64>`.
- Compared with `hmac.compare_digest` (constant-time).
- Policy: 8–128 characters, ≥1 letter and ≥1 digit, not in a 20-entry common-password list.
- Unknown-email logins run a dummy hash check so timing matches a real lookup.

### 7.3 RBAC

- Middleware reads `role, is_active` from the database on every admin request (demotion takes immediate effect).
- Permission dependencies enforce fine-grained ownership: another user's resource → 404, never 403 (existence not leaked).
- Unknown DB role treated as `user` (least privilege).

### 7.4 Other security measures

| Concern | Implementation |
|---|---|
| Path traversal | Overlay paths confined to `storage/detection/overlays/` via `is_relative_to()` |
| XSS (portal) | `escapeHtml()` on all interpolated values |
| Enumeration defence | Same message for unknown email vs. wrong password |
| Idempotency | `Idempotency-Key` header on submission creates, stored 24 h |
| Login rate limiting | **Not implemented** (known gap) |
| Refresh tokens | **Not implemented** (known gap) |

---

## 8. Data Model

### 8.1 Entity summary

| Table | Key columns |
|---|---|
| `users` | `id`, `email` (unique on `lower(email)`), `role` (user/admin CHECK), `password_hash`, `is_active` |
| `inspections` | `id`, `user_id`, `cargo_type_id`, `status`, `detection_result` (JSONB), `decision_result` (JSONB), `detection_overlay`, `image_filename`, `deleted_at` |
| `cargo_types` | `id`, `slug` (UK), `label`, `density_kg_m3`, `description` |
| `tags` / `inspection_tags` | many-to-many join, cascade on delete |
| `audit_log` | append-only, `actor_user_id`, `action`, `entity_type`, `entity_id`, `detail` (JSONB) |
| `idempotency_keys` | `key` (PK), `endpoint`, `status_code`, `response` (JSONB), `expires_at` |

### 8.2 Seeded cargo types

| Slug | Label | Density kg/m³ |
|---|---|---|
| `scrap-steel` | Scrap steel | 7850 |
| `thermal-coal` | Thermal coal | 800 |
| `construction-gravel` | Construction gravel | 1700 |
| `agricultural-grain` | Agricultural grain | 750 |
| `other` | Other | — (fallback) |

### 8.3 Migration history (12 revisions, linear)

| Rev | Name | Change |
|---|---|---|
| 0001 | initial | `users` + `addresses` scaffold |
| 0002 | create_inspections | `inspections` with free-text fields + image columns |
| 0003 | link_inspections_to_users | `user_id` FK, email backfill, drop old columns |
| 0004 | add_phone_drop_addresses | `users.phone`, drop `addresses` |
| 0005 | email_lower_unique | Dedup users, unique `lower(email)` index |
| 0006 | status_soft_delete | `status`, `status_note`, `updated_at`, `deleted_at`, CHECK, partial index |
| 0007 | cargo_types_lookup | `cargo_types` table + seed, `cargo_type_id` FK |
| 0008 | tags_audit_and_idempotency | `tags`, `inspection_tags`, `audit_log`, `idempotency_keys`, weight/volume |
| 0009 | user_credentials | `password_hash`, `password_set_at`, `last_login_at`, `is_admin` |
| 0010 | roles_and_reviews | `role` replaces `is_admin`, `reviewed_by`, `reviewed_at`, pending-review index |
| 0011 | detection_results | `detection_result` JSONB, `detected_at`, `detection_overlay` |
| 0012 | ai_decision | `decision_result` JSONB, `decided_at` |

Every revision has a working `downgrade()`. `alembic/env.py` imports the app's engine, so app and migrations can never target different databases.

---

## 9. Detection Pipeline — YOLO + SAM

### 9.1 Why a subprocess

The ML environment is ~5.5 GB (torch, ultralytics, segment-anything, transformers, Open3D) and conflicts with the API's ~120 MB environment. Running the pipeline as a subprocess means:

- A detector crash never takes down the API.
- No CUDA version negotiation between the two environments.
- The two sides share exactly one file: `result.json`.

```text
FastAPI process                        Detection subprocess
──────────────────────────────         ─────────────────────────────────────
app/services/detection.py              scripts/detect_runner.py
  subprocess.run(DETECTION_PYTHON,  →    loads detector/Revamping.ipynb
                 detect_runner.py,        executes cells 2,4,7,8,8b,8c,9,10
                 --image, --out-dir)      in one shared namespace
                                          writes result.json + overlay.png
  reads result.json              ←
  copies overlay → storage/detection/overlays/
  saves to inspections.detection_result (JSONB)
```

### 9.2 Concurrency model

A threading semaphore (`DETECTION_MAX_CONCURRENCY=1`, default) ensures only one run executes at a time. The notebook cells share module-level state and write to a shared directory — two overlapping runs would race. A second request during a run receives **503 Detection Busy** immediately rather than corrupting the first run.

### 9.3 The notebook execution model

`detector/Revamping.ipynb` has 31 cells that share one global namespace. The runner executes a selected subset by compiling and `exec`-ing each cell's source into a single `dict`:

```python
namespace = {"__name__": "__main__"}
for cell in ("CELL 2", "CELL 4", "CELL 7", "CELL 8",
             "CELL 8b", "CELL 8c", "CELL 9", "CELL 10"):
    exec(compile(strip_magics(source[cell]), f"<{cell}>", "exec"), namespace)
```

Three adaptations are applied:
1. **Cell 3 (GUI file picker) is skipped.** `image_paths = [str(image)]` is injected directly.
2. **`OUTPUT_DIR` is redirected** to a unique per-run directory so concurrent runs (even if they bypass the semaphore) cannot clobber each other's overlays.
3. **Cells 12–28 are not run.** These cells perform depth estimation, point-cloud construction and volume/weight calculation — all require real metric calibration which is not yet available (see §9.7).

### 9.4 YOLO model — training and configuration

| Attribute | Value |
|---|---|
| Architecture | YOLO11 / YOLO-OBB (oriented bounding boxes) |
| Weights file | `detector/models/cargo_obb_best.pt` (~6 MB, in git) |
| Training dataset | `Cargo-Detection.v3i.yolov8-obb.zip`, 90 files / 18 scenes |
| Dataset split | Validation share 0.30, seed 42, scene-level leakage guard |
| Best run | `cargo_obb_retrain_batch2`, best epoch 7, val mAP50 **0.502** |
| Fallback weights | `yolo11m.pt` (COCO pre-trained, 80 general classes) |

**Cargo taxonomy — 8 classes**

| Role | Classes |
|---|---|
| Primary targets | `Cargo-Box`, `Wooden-Plate` |
| Envelope / fallback | `Cargo-Detection` |
| Explicitly excluded | `Net`, `Strap`, `Chain`, `Crane`, `Hook` |

**Confidence thresholds**

| Threshold | Constant | Value |
|---|---|---|
| Custom taxonomy (zip-trained OBB) | `CARGO_CONF_ZIP_TAXONOMY` | 0.30 |
| COCO fallback | `CARGO_CONF_COCO_FALLBACK` | 0.15 |
| Minimum box size | `MIN_CARGO_BOX_PX` | 12 px |
| Minimum area fraction | `MIN_CARGO_AREA_FRACTION` | 0.2% of frame |

**Retraining history**

| Date | Run | Notes |
|---|---|---|
| 2026-10-13 | `cargo_obb_retrain_ship1` (25 epochs) | +1 sample (red bags + yellow crane). Ship scene FP: 0.80→0.76. True load still missed. |
| 2026-10-13 | `cargo_obb_retrain_batch2` (25 epochs, best ep 7) | +4 hand-labeled scenes. val mAP50=0.502 (best to date). Ship crane FP *rose* 0.76→0.84 — data path exhausted for that scene. |

### 9.5 SAM model — configuration and fallback

| Attribute | Value |
|---|---|
| Target model | SAM 3 (attempted first; fails back — `sam3/` package is a source checkout, not installed) |
| In-use model | **SAM 1 ViT-B** (`sam_vit_b_01ec64.pth`, ~358 MB) |
| Download | `dl.fbaipublicfiles.com` on first run (not in git, too large) |
| SAM 3 confidence | `SAM3_CONF_THRESHOLD` = 0.20 |
| Auto-mask (fallback) | `POINTS_PER_SIDE=12`, `PRED_IOU_THRESH=0.82`, `STABILITY_THRESH=0.88` |

SAM is not used as a standalone detector. It receives the YOLO bounding box (or a dynamic load-region estimate) as a box/point prompt and produces a precise pixel mask of the cargo, excluding net and rigging.

### 9.6 Pipeline stages

| Stage | Notebook Cells | What happens |
|---|---|---|
| 1. Select | 3 | Image path injected (GUI replaced). API always passes exactly one image. |
| 2. Quality | 5 | Blur (Laplacian variance), brightness check, resolution report. *(Not run by API.)* |
| 3. Load models | 7 | YOLO weights loaded in priority order: `cargo_yolo11_best.pt` → `cargo_obb_best.pt` → `yolo11m.pt`. SAM 3 attempted; falls back to SAM 1 ViT-B. |
| 4. Detect | 8, 8b | YOLO inference on the full image. Suspended-load clustering groups detections. Ground-contact rejection and exclusion zones (`Net`, `Strap`, `Chain`, `Crane`, `Hook`) applied. |
| 5. Prompt SAM | 8c | Dynamic load-region estimate computed. Box and point prompts constructed and passed to SAM. |
| 6. Segment | 9 | Crop + upscale for resolution. SAM multi-mask inference. Masks ranked by weighted score (SAM quality × 5.0, IoU × 4.0, fill ratio × 2.0, exclusion penalty × 3.0). Net rejected. Tight bounding box and OBB computed from winning mask. |
| 7. Accept / reject | 10 | Acceptance gate applied (see §9.6.1). If accepted, orange mask + red box drawn on the overlay PNG. Verdict printed to stdout; `detect_runner.py` parses it with regexes and writes `result.json`. |
| 8. Measure | 11–28 | Depth-Anything depth map, Open3D point cloud, relative volume, density × volume weight. **Not run by the API** — see §9.7. |

**Acceptance gate (Cell 10)**

| Criterion | Threshold | Rejects if |
|---|---|---|
| Aggregate score | `MIN_ACCEPT_SCORE = 6.0` | score < 6.0 |
| Box fraction of frame | `MAX_ACCEPT_BOX_FRACTION = 0.60` | box > 60% of frame |
| Border leak | `MAX_ACCEPT_BORDER_LEAK = 0.12` | mask bleeds > 12% onto the 3 px border |

`border_leak` is a meaningful signal: suspended cargo does not touch the frame edge; sky and water masks do.

### 9.7 What the pipeline deliberately does not produce

The depth and volume cells use normalised camera intrinsics (`fx = fy = width`) and a hard-coded `REFERENCE_WIDTH_METERS = 2.0`. This makes the volume output *dimensionless* — a relative figure wearing a unit. Storing it as `volume_m3` would make it look authoritative. Until real metric calibration is available, `volume_m3` and `estimated_weight_kg` remain `null`. `supports_measurement: false` is returned in the availability response so callers know not to expect these fields.

### 9.8 Detection result payload

```json
{
  "ok": true,
  "detected": true,
  "label": "Cargo-Box",
  "aggregate_score": 16.3,
  "objects": [
    {
      "label": "Cargo-Box",
      "yolo_confidence": 0.83,
      "sam_score": 0.93,
      "mask_area_px": 17051,
      "box": [52, 287, 196, 459]
    }
  ],
  "box_fraction_of_frame": 0.10,
  "mask_area_ratio": 0.0682,
  "border_leak": 0.0,
  "detector_origin": "zip_trained_obb",
  "uses_zip_taxonomy": true,
  "elapsed_seconds": 27.0,
  "run_dir": "run_20261015_142301_a3f7b2c1"
}
```

### 9.9 Response semantics

| Situation | HTTP | `ok` | `detected` | `detection_status` |
|---|:---:|:---:|:---:|---|
| Cargo found and accepted | 200 | true | true | `detected` |
| Pipeline ran, nothing passed gate | 200 | true | false | `no_cargo` |
| Pipeline crashed | 502 | false | false | `error` |
| Disabled / interpreter missing / busy | 503 | — | — | unchanged |
| Run timed out (300 s) | 504 | — | — | `error` (timed_out: true) |
| Never triggered | 200 | false | false | `not_run` |

### 9.10 Storage

```text
storage/
├── inspections/<uuid>.<ext>                        uploaded originals (unchanged)
└── detection/
    ├── run_<YYYYMMDD_HHMMSS>_<hex>/               per-run: result.json, overlay.png
    │   (last 20 kept; older swept by cleanup_runs())
    └── overlays/inspection_<id>_<hex>.png          persisted overlays (never swept)
```

---

## 10. AI Decision Gate — OpenAI

### 10.1 Overview

When `OPENAI_DECISION_ENABLED=true`, an optional rubric-based evaluation is called immediately after a submission is created. A high-confidence result triggers automatic approval, bypassing the manual review queue. A low-confidence result or any failure falls back to manual review silently.

### 10.2 Call details

| Attribute | Value |
|---|---|
| Endpoint | `POST https://api.openai.com/v1/decisions` |
| Model | `gpt-6-luna` |
| Auth | `Authorization: Bearer <OPENAI_API_KEY>` via httpx |
| Timeout | 15 s total, 5 s connect |
| Retries | 2 attempts; retries: connect errors, 429/500/502/503/504 (honours `Retry-After`, capped 2 s); read timeout fails immediately |

### 10.3 Rubric (v1)

| Predicate | Type | Description |
|---|---|---|
| `cargo_present` | predicate (0.0–1.0) | Is cargo visible in the image? |
| `cargo_type` | choice | containers / bulk / hazardous / other / none |
| `matches_declaration` | predicate (0.0–1.0) | Does what is seen match the declared cargo type? |

### 10.4 Auto-approval logic

```text
IF cargo_present ≥ OPENAI_DECISION_MIN_CONFIDENCE (0.8)
   AND matches_declaration ≥ OPENAI_DECISION_MIN_CONFIDENCE (0.8)
   AND submission.status = "submitted"   (drafts are never auto-approved)
THEN
   status = approved
   status_note = "<rationale including thresholds and scores>"
   reviewed_by = NULL   (no human; known gap in audit)
   decision = "approve"
ELSE
   decision = "review"
   submission stays in manual review queue
```

### 10.5 Stored result (JSONB)

```json
{
  "ok": true,
  "model": "gpt-6-luna",
  "rubric_version": 1,
  "recommendation": "approve",
  "auto_approved": true,
  "threshold": 0.8,
  "answers": {
    "cargo_present": { "probability": 0.95 },
    "cargo_type": { "value": "bulk" },
    "matches_declaration": { "probability": 0.91 }
  },
  "usage": { ... }
}
```

On failure: `{"ok": false, "error": "<message>"}`. The upload always succeeds regardless.

---

## 11. Lifting Plan Generator

### 11.1 Overview

`GET /api/v1/portal/submissions/{id}/lifting-plan?ref_m=1.2&ref_px=340&format=markdown`

Requires `detection_status = detected`. Nothing is persisted — the plan is generated on each request. Output follows the HSE-F003 form layout.

Reference scale parameters `ref_m` (real-world size in metres) and `ref_px` (corresponding pixel length in the image) must both be provided or both omitted. If only one is given, the endpoint returns 422.

### 11.2 Calculation chain

| Quantity | Formula | Tag | Notes |
|---|---|---|---|
| Description | `"{count} × {label} ({cargo label})"` | `[AI]` | Directly observed |
| Scale factor | `m_per_px = ref_m / ref_px` | — | Only computed when both ref values given |
| Length | `L = box_width_px × m_per_px` | `[AI-ESTIMATE]` | |
| Height | `H = box_height_px × m_per_px` | `[AI-ESTIMATE]` | |
| Width | **Always blank** | — | Depth not visible in one photo |
| Weight | `round(density × L × min(L,H) × H)` | `[AI-ESTIMATE]` | W assumed = smaller visible dimension; only when cargo type has density |
| Centre of gravity | Centre of detected bounding box | `[AI-THEORETICAL]` | Assumes uniform mass distribution |
| Hook point | Top of box minus sling rise `r = √(sling_len² − half_span²)` | `[AI-THEORETICAL]` | Sling length = `2 × box_height` |
| Sling angle from vertical | `θ = atan(half_span / r)` | `[AI-THEORETICAL]` | Standard 2-leg bridle assumption |

### 11.3 Field categories

| Category | Tag | Meaning | Examples |
|---|---|---|---|
| A — Observed | `[AI]` | Directly seen in the photo | Description, object count, bounding box, confidence |
| B — Estimated | `[AI-ESTIMATE]` | Calculated from one stated reference | Length, height, weight |
| B2 — Theoretical | `[AI-THEORETICAL]` | Idealised geometry, stated assumptions | CoG, hook point, sling angle |
| C — Engineering judgement | (blank) | Never filled by AI | Crane, boom, radius, counterweight, capacity, gear, safety factor, signatures |

### 11.4 HSE-F003 section coverage

| Form section | Status |
|---|---|
| Part 1 – General information | ❌ Not rendered |
| Part 2 – Details of load (description, dimensions, weight, CoG/rigging sketch) | ✅ Generated |
| Part 3 – Equipment / gears / load calculation | ⚪ Rendered as blank tables |
| Part 4 – Drawing / sketch (overlay link + ASCII rigging diagram) | ✅ Generated |
| Part 5 – Communication / personnel | ❌ Not rendered |
| Part 7 – Physical & environmental | ❌ Not rendered |
| Part 8 – Signatures | ❌ Not rendered |

### 11.5 Output formats

- `format=markdown` (default): `text/markdown`, downloaded as `lifting-plan-{id}.md`
- `format=json`: success envelope with `data` dict and `meta.generated_at`

---

## 12. Configuration Reference

All settings loaded by `app/core/config.py` (`Settings`, `lru_cache`) from environment variables or `.env`. Field names are case-insensitive.

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://postgres:postgres@localhost:5432/awesome_project?connect_timeout=10` | Shared by app and Alembic |
| `SQL_ECHO` | `false` | Log SQL statements |
| `DB_POOL_SIZE` | 5 | Connection pool size |
| `DB_MAX_OVERFLOW` | 10 | Pool overflow |
| `DB_POOL_TIMEOUT` | 30 s | Pool acquisition timeout |
| `DB_POOL_RECYCLE` | 1800 s | Connection recycling |
| `JWT_SECRET` | random per process | **Must be set in production** — otherwise every restart logs everyone out |
| `JWT_EXPIRES_HOURS` | 12 | Session lifetime |
| `COOKIE_SECURE` | `true` | HTTPS-only cookie; set `false` for local HTTP |
| `CORS_ORIGINS` | `localhost:8000`, `127.0.0.1:8000`, `localhost:5173` | JSON list or comma-separated |
| `DETECTION_ENABLED` | `false` | Enable YOLO+SAM subprocess |
| `DETECTION_PYTHON` | — | Path to the detection venv's `python.exe` |
| `DETECTION_PROJECT_DIR` | `""` (use vendored `detector/`) | Notebook and models folder override |
| `DETECTION_TIMEOUT` | 300 s | Per-run timeout |
| `DETECTION_MAX_CONCURRENCY` | 1 | Keep at 1; notebook is not re-entrant |
| `OPENAI_DECISION_ENABLED` | `false` | Enable AI rubric gate on upload |
| `OPENAI_API_KEY` | `""` | Required when enabled |
| `OPENAI_DECISION_MODEL` | `gpt-6-luna` | Model used for `/v1/decisions` |
| `OPENAI_DECISION_TIMEOUT` | 15 s (connect 5 s) | Timeout → error, submission goes to manual review |
| `OPENAI_DECISION_MIN_CONFIDENCE` | 0.8 | Inclusive threshold for both predicates |

---

## 13. Testing

### 13.1 Test suite summary

322 tests across 10 modules, all running against real PostgreSQL (not SQLite, not mocks).

| File | Tests | Focus |
|---|---:|---|
| `test_api_contract.py` | 26 | `/api/v1` prefix, HTTP method rules, link resolution, docs ↔ OpenAPI sync |
| `test_auth_portal.py` | 52 | Hashing, register/login, cookie, isolation, uploads, idempotency |
| `test_bug_regressions.py` | 20 | Pagination bounds, case-insensitive email, 405 `Allow`, ISO UTC timestamps |
| `test_detection.py` | 56 | Availability, 200/502/503/504 outcomes, caching, `force`, path traversal, runner contract |
| `test_docs_auth.py` | 20 | Bearer scheme in OpenAPI; cookie beats header |
| `test_lifting_plan.py` | 24 | 422 refusals, Markdown/JSON output, calibration, weight, rigging geometry |
| `test_openai_decision.py` | 19 | Rubric, threshold gate, auto-approve, failure fallback |
| `test_query_patterns.py` | 36 | No N+1 queries, filters, sort whitelist, soft delete, aggregates, audit |
| `test_rbac.py` | 50 | Permissions, 401/403, review flow, self-approval blocked |
| `test_ui_contract.py` | 19 | Every JSON path that `index.html` reads |

### 13.2 Infrastructure

- A session fixture drops and recreates `awesome_project_test`, runs `alembic upgrade head`.
- Each test runs inside a rolled-back transaction — no residue between tests.
- OpenAI is forced off; image storage redirected to a temp directory.
- `TestRunnerContract` asserts the runner reads `CARGO_PROJECT_DIR`, runs only cells 7–10, and still parses the log — the notebook's subprocess contract is the tripwire.

### 13.3 Running

```powershell
.venv\Scripts\python.exe -m pytest tests/ -q
```

---

## 14. Known Limitations & Roadmap

### 14.1 Current limitations

| # | Issue | Impact |
|---|---|---|
| 1 | CORS middleware is innermost. Preflight to `/api/v1/*` without a cookie gets 401 with no CORS headers. Comment in `main.py` claims the opposite. | Blocks cross-origin browser clients |
| 2 | Detection is synchronous and blocking (16–45 s). No background task or async job queue. | Long HTTP holds; timeouts fail the client |
| 3 | One detection run at a time (semaphore). | Low throughput under concurrent usage |
| 4 | `volume_m3` / `estimated_weight_kg` always null. Depth cells not run (no metric calibration). | Lifting plan cannot include verified weight |
| 5 | Portal has no Detect button, overlay viewer, or lifting plan download. These exist as API only. | Users must use curl / Swagger |
| 6 | Invalid `status` or `sort` on portal list raises unhandled `ValueError` (admin list handles it). | 500 instead of 422 |
| 7 | Idempotency keys not scoped per user; no request hash; concurrent first requests can both execute; `purge_expired()` never scheduled. | Theoretical replay bugs |
| 8 | Audit: `update`, `soft_delete`, `restore`, `hard_delete` record no actor; AI auto-approval leaves `reviewed_by` NULL. | Audit gaps |
| 9 | No login rate limiting, no refresh tokens. | Brute-force and session-fixation exposure |
| 10 | Local disk storage only. Cannot run on more than one server. | Not horizontally scalable |
| 11 | `JWT_SECRET` defaults to a random value per process (no startup enforcement in production). | Every restart logs everyone out |
| 12 | SAM 3 is attempted but always falls back to SAM 1 ViT-B. | No improvement from SAM 3 until package is properly installed |
| 13 | False positives on non-cargo images (e.g. a man and a dog → `Cargo-Box` at 0.60 confidence). | Requires manual review or score threshold filtering |

### 14.2 Suggested roadmap

1. Fix the CORS middleware order and route `ValueError` to 422 on portal list.
2. Portal UI: Detect button, overlay viewer, reference-size input, lifting plan download.
3. Align cargo catalogue with real port cargo types (containers, boom lifts, gen sets, drums, IBCs).
4. Async detection jobs — `202 Accepted` + polling — instead of blocking HTTP.
5. Real metric calibration: run depth cells once intrinsics are known; populate `volume_m3` and `estimated_weight_kg`.
6. Load-calculation helper: safety factor and utilisation warnings using the defined `WARN_*` constants.
7. Render the remaining HSE-F003 sections (Parts 1, 5, 7, 8) as blank placeholders.
8. Idempotency: per-user key scoping, request hash, `purge_expired()` scheduler.
9. Audit: actor and previous status on every action.
10. Security: login rate limiting, refresh tokens, mandatory `JWT_SECRET` enforcement.
11. Object storage (S3-compatible) for multi-instance deployment; sweep overlays on purge.
12. More training data per scene; full scene variety for the cargo detector.
13. React dashboard and Android handheld app on top of this API.

---

*End of Technical_Document.md*
