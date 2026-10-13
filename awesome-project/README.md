# User-Address API (FastAPI)

A layered REST API for managing users and their addresses, built with FastAPI,
SQLAlchemy, Pydantic, Alembic, and PostgreSQL.

The project follows a strict four-layer split so that HTTP concerns, validation,
business rules, and database access stay separable:

```text
HTTP Layer        -> routers/
Validation Layer  -> schemas/
Business Layer    -> services/
Data Layer        -> models/ + database.py
Database          -> PostgreSQL (via psycopg 3)
```

---

## Table of contents

1. [Project layout](#project-layout)
2. [Technology stack](#technology-stack)
3. [How the layers fit together](#how-the-layers-fit-together)
4. [Flow charts](#flow-charts)
   - [Startup flow](#startup-flow)
   - Request lifecycle](#request-lifecycle)
   - `POST /users/` sequence](#post-users-sequence)
   - `POST /addresses/` with ownership check](#post-addresses-with-ownership-check)
   - `PUT` partial update flow](#put-partial-update-flow)
   - Error handling flow](#error-handling-flow)
5. [Data model](#data-model)
6. [API reference](#api-reference)
7. [Migrations (Alembic)](#migrations-alembic)
8. [Cargo detection (SAM + YOLO)](#cargo-detection-sam--yolo)
9. [Running the project](#running-the-project)
10. [Dependency notes](#dependency-notes)
11. [Roadmap / next steps](#roadmap--next-steps)

### Companion documents

| Document | Covers |
|---|---|
| [`Flow.md`](Flow.md) | How every request moves through the layers, end to end |
| [`DETECTION.md`](DETECTION.md) | The SAM/YOLO cargo pipeline, and why it is a subprocess |
| [`POSTGRES.md`](POSTGRES.md) | Database setup on Windows |
| [`Alembic.md`](Alembic.md) | Migrations, autogenerate internals, batch mode |
| [`Working.md`](Working.md) | The detection pipeline itself (cells, models, datasets) |

---

## Project layout

```text
awesome-project/
├── main.py                 # FastAPI app, CORS, router registration, root route
├── config.py               # Settings; single source of DATABASE_URL
├── database.py             # Engine, session factory, Base, get_db dependency
├── pyproject.toml          # uv project definition (source of truth)
├── requirements.txt        # legacy pip pins (see Dependency notes)
├── uv.lock                 # resolved dependency graph
├── alembic.ini             # Alembic config (URL now lives in config.py)
├── static/index.html       # Upload UI (details -> image -> output)
├── scripts/                # PostgreSQL setup helpers
├── alembic/
│   ├── env.py              # Uses the app's engine; autogenerate metadata
│   └── versions/
│       ├── 0001_initial.py         # users + addresses tables
│       └── 0002_create_inspections.py  # inspections table
├── models/                 # SQLAlchemy ORM tables
│   ├── user.py
│   └── address.py
├── schemas/
│   ├── requests/           # Pydantic inbound models
│   │   ├── user.py         # UserCreate, UserUpdate
│   │   └── address.py      # AddressCreate
│   └── responses/          # Pydantic outbound models
│       ├── user.py         # UserResponse
│       └── address.py      # AddressResponse
├── services/               # Business logic and DB operations
│   ├── user_service.py
│   └── address_service.py
└── routers/                # HTTP endpoints
    ├── user.py
    └── address.py
```

Related docs in this repo:

- `ARCHITECTURE_FLOW.md` — layer-by-layer reference and Mermaid diagrams.
- `working_deps_libs.md` — full pinned dependency inventory.
- `Initial_Notes.txt` — raw notes on FastAPI, Pydantic, Starlette, Uvicorn.

---

## Technology stack

| Layer | Technology | Version (uv.lock) | Role in this project |
|---|---|---:|---|
| Web framework | **FastAPI** | 0.142.2 | App object, `APIRouter`, `Depends`, `HTTPException`, `response_model`, auto OpenAPI docs |
| ASGI foundation | **Starlette** | 1.7.0 | Routing, middleware pipeline, CORS, lifespan events. `FastAPI` subclasses `Starlette`, so every Starlette feature is available |
| Server | **Uvicorn** | 0.54.0 | ASGI server that actually accepts sockets and calls the app. Not a framework — it does no path routing |
| HTTP parser | **httptools** | 0.8.0 | High-speed HTTP/1.1 parsing used by Uvicorn (via `uvicorn[standard]`) |
| Event loop | **uvloop** | 0.23.0 | Faster asyncio event loop implementation used by Uvicorn |
| Validation | **Pydantic** | 2.13.5 | Request/response schemas, `model_dump()`, `EmailStr`, `from_attributes` |
| Email validation | **email-validator** | 2.3.0 | Backs `pydantic.EmailStr` |
| ORM | **SQLAlchemy** | 2.1.1 | `DeclarativeBase`, `Mapped`/`mapped_column`, `relationship`, `Session`, query engine |
| Migrations | **Alembic** | 1.20.0 | Versioned schema changes, `upgrade`/`downgrade` |
| Templating for migrations | **Mako** | 1.4.3 | Renders revision scripts from `script.py.mako` |
| Database | **PostgreSQL** | 17.11 | System of record. Local service `postgresql-x64-17` |
| PostgreSQL driver | **psycopg** | 3.3.6 | DBAPI driver + adapter for SQLAlchemy (`postgresql+psycopg`) |
| Settings | **pydantic-settings** | 2.15.0 | Reads `DATABASE_URL` from env / `.env` |
| File uploads | **python-multipart** | 0.0.32 | Backs `UploadFile` / `Form` on `/inspections/` |
| Package/env manager | **uv** | — | Creates `.venv`, resolves `uv.lock`, runs scripts |
| Language | **Python** | 3.12.10 (env), `>=3.12` required | Type hints drive validation and docs |
| ASGI reload (dev) | **watchfiles** | 1.3.0 | File watching for `--reload` |
| API docs UI | **Swagger UI** / ReDoc | bundled | Served at `/docs` and `/redoc` from the generated OpenAPI schema |
| Test client | **httpx** | 0.28.1 | Used by `fastapi.testclient.TestClient` |

### How the pieces relate

```text
Uvicorn (ASGI server)
  └── calls
FastAPI (framework)  ──inherits──>  Starlette (HTTP/routing core)
  ├── Pydantic        (validation, serialization, JSON Schema -> OpenAPI)
  └── SQLAlchemy      (ORM)  ──>  PostgreSQL (via psycopg 3)
Alembic (migrations) ──uses──>   SQLAlchemy + Mako
```

---

## How the layers fit together

### `main.py` — composition root

Creates the app, installs CORS middleware, imports the routers, mounts them, and
serves `GET /`. Nothing else lives here.

```python
app = FastAPI(title="User-Address API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], ...)
app.include_router(user_router)
app.include_router(address_router)
```

### `config.py` + `database.py` — data layer foundation

`config.py` reads `DATABASE_URL` from the environment or `.env`; `database.py`
builds the engine from it. `alembic/env.py` imports that same engine, so the app
and the migrations can never point at different databases.

```python
# config.py
settings = get_settings()          # DATABASE_URL from env / .env

# database.py
engine = create_engine(settings.database_url, pool_pre_ping=True, pool_size=5, ...)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

`get_db` is a generator dependency. FastAPI opens one session per request and
guarantees `db.close()` runs after the response is produced. See
[POSTGRES.md](POSTGRES.md) for the full setup.

### `models/` — table definitions

`User` and `Address` inherit `Base`, so importing them registers their tables on
`Base.metadata` (which is exactly what `alembic/env.py` reads for autogenerate).
`users.id` is the parent of `addresses.user_id`, joined by
`relationship(back_populates=...)` on both sides, with
`cascade="all, delete-orphan"` so deleting a user deletes their addresses.

### `schemas/` — validation boundary

| Schema | Direction | Used by |
|---|---|---|
| `UserCreate` | inbound | `POST /users/` |
| `UserUpdate` | inbound | `PUT /users/{user_id}` (all fields optional) |
| `AddressCreate` | inbound | `POST /addresses/` |
| `UserResponse` | outbound | every `/users/` response |
| `AddressResponse` | outbound | every `/addresses/` response |

`model_config = {"from_attributes": True}` lets Pydantic read straight off SQLAlchemy
ORM instances instead of dicts.

### `services/` — business layer

Plain classes, one per aggregate. The session is injected through the constructor
(`UserService(db)`), so services never import the engine or open connections
themselves. Rules that live here: duplicate-email rejection, referenced-user
existence check, existence-or-`None` returns, and the commit/refresh pairs.

### `routers/` — HTTP layer

Endpoints hold no business logic. They resolve the service, translate `None` into
`404` and `ValueError` into `400`, and declare `response_model` so the response is
validated and documented.

---

## Flow charts

### Startup flow

```mermaid
flowchart TD
    A[uv run uvicorn main:app --reload] --> B[Uvicorn imports main:app]
    B --> C[import fastapi]
    C --> C1[FastAPI class inherits Starlette]
    C1 --> C2[Pydantic schemas available]
    B --> D[import database]
    D --> D0[import config -> Settings from env/.env]
    D0 --> D1[create_engine postgresql+psycopg, pooled]
    D1 --> D2[sessionmaker -> SessionLocal]
    D2 --> D3[DeclarativeBase -> Base]
    B --> E[import routers.user / routers.address]
    E --> F[import models.user / models.address]
    F --> G[Tables registered on Base.metadata]
    E --> H[import schemas + services]
    H --> I[APIRouter objects created with prefixes]
    B --> J[FastAPI app = FastAPI]
    J --> K[CORSMiddleware added to middleware stack]
    K --> L[include_router user then address]
    L --> M[GET / root endpoint registered]
    M --> N[App ready on port 8000]
```

### Request lifecycle

What happens between a socket accepting bytes and JSON leaving the process:

```mermaid
flowchart TD
    S[HTTP request arrives] --> U[Uvicorn httptools parses request]
    U --> ASGI[ASGI scope/receive/send built]
    ASGI --> MW[CORSMiddleware checks Origin, adds headers]
    MW --> RT[Starlette Router matches path + method]
    RT --> NOT{Path matched?}
    NOT -->|No| NF[404 Not Found]
    NOT -->|Yes| EP[Endpoint function called]
    EP --> DEP[Resolve Depends: get_db -> new Session]
    DEP --> VAL[Pydantic validates path, query and body]
    VAL --> OK{Valid?}
    OK -->|No| E422[422 Unprocessable Entity + error detail]
    OK -->|Yes| FN[Endpoint body: instantiate service with db]
    FN --> SVC[Service method runs business rules]
    SVC --> ORM[SQLAlchemy emits SQL over psycopg]
    ORM --> ROW[Row mapped to ORM object]
    ROW --> RESP[response_model filters + serializes ORM object]
    RESP --> CLOSE[get_db finally: db.close]
    CLOSE --> SER[Uvicorn writes status + JSON body]
    SER --> DONE[Client receives response]
```

### `POST /users/` sequence

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant R as routers/user.py
    participant S as UserCreate (Pydantic)
    participant D as get_db()
    participant US as UserService
    participant M as User model
    participant DB as PostgreSQL

    C->>R: POST /users/ {"name":"Asha","email":"asha@example.com"}
    R->>S: validate body
    alt invalid email or missing name
        S-->>C: 422 validation error
    end
    R->>D: resolve dependency
    D->>DB: open connection
    D-->>R: Session
    R->>US: UserService(db)
    R->>US: create_user(user_data)
    US->>DB: SELECT * FROM users WHERE email = ?
    alt email already registered
        US-->>R: ValueError
        R-->>C: 400 Bad Request
    end
    US->>M: User(**user_data.model_dump())
    US->>DB: db.add + COMMIT
    DB-->>US: generated id
    US->>DB: db.refresh -> server defaults
    US-->>R: User ORM object
    R->>R: response_model UserResponse
    R-->>C: 201 Created + UserResponse JSON
    D->>DB: db.close (finally)
```

### `POST /addresses/` with ownership check

```mermaid
flowchart TD
    A[POST /addresses/] --> B[AddressCreate validates email_address + user_id]
    B --> C[get_db provides Session]
    C --> D[AddressService db .create_address]
    D --> E{SELECT User WHERE id = user_id}
    E -->|not found| F[raise ValueError]
    F --> G[Router catches -> 400 Bad Request]
    E -->|found| H[Address model instance built]
    H --> I[db.add + db.commit + db.refresh]
    I --> J[AddressResponse serializes via from_attributes]
    J --> K[201 Created to client]
```

### `PUT` partial update flow

```mermaid
flowchart TD
    A[PUT /users/1] --> B[UserUpdate validates: name?, email?, is_active?]
    B --> C[get_db provides Session]
    C --> D[UserService.update_user]
    D --> E{SELECT User WHERE id = 1}
    E -->|None| F[Router raises 404]
    E -->|found| G["model_dump(exclude_unset=True) keeps only sent fields"]
    G --> H[setattr each field on the ORM object]
    H --> I[db.commit + db.refresh]
    I --> J[UserResponse -> 200 OK]
```

Note: `exclude_unset=True` is what makes this a partial update. Fields the client
omits are left untouched rather than reset to `None`.

### Error handling flow

```mermaid
flowchart TD
    A[Endpoint runs] --> B{What failed?}
    B -->|Body/path validation| C[FastAPI raises RequestValidationError -> 422]
    B -->|Service returns None| D[Router raises HTTPException 404]
    B -->|Service raises ValueError| E[Router converts to 400]
    B -->|Unexpected exception| F[500 unhandled -> stack trace in server log]
    C --> G[JSON: detail with field locations]
    D --> G
    E --> G
    F --> G
```

---

## Data model

```mermaid
erDiagram
    USERS ||--o{ ADDRESSES : "has many"
    USERS {
        int  id PK "indexed, autoincrement"
        str  name "max 50, NOT NULL"
        str  email UK "max 100, unique + indexed"
        bool is_active "default True"
    }
    ADDRESSES {
        int id PK "indexed, autoincrement"
        str email_address "max 100, NOT NULL"
        int user_id FK "-> users.id"
    }
```

- One `User` has many `Address` rows; every `Address` belongs to exactly one `User`.
- Deleting a user cascades to their addresses (`cascade="all, delete-orphan"`).
- Both `id` columns are indexed; `users.email` is unique and indexed.

---

## API reference

Base URL `http://127.0.0.1:8000`.

| Method | Path | Body | Success | Notes |
|---|---|---|---|---|
| `GET` | `/` | – | 200 | Health message |
| `GET` | `/users/` | – | 200 | Query: `skip` (0), `limit` (100) |
| `GET` | `/users/{user_id}` | – | 200 | 404 if missing |
| `POST` | `/users/` | `UserCreate` | 201 | 400 if email already registered |
| `PUT` | `/users/{user_id}` | `UserUpdate` | 200 | Partial; 404 if missing |
| `DELETE` | `/users/{user_id}` | – | 204 | Cascades to addresses; 404 if missing |
| `GET` | `/addresses/` | – | 200 | Query: `skip` (0), `limit` (100) |
| `GET` | `/addresses/{address_id}` | – | 200 | 404 if missing |
| `POST` | `/addresses/` | `AddressCreate` | 201 | 400 if `user_id` does not exist |
| `DELETE` | `/addresses/{address_id}` | – | 204 | 404 if missing |

Interactive docs: `/docs` (Swagger UI), `/redoc` (ReDoc), `/openapi.json` (raw schema).

Example payloads:

```jsonc
// POST /users/
{ "name": "Asha", "email": "asha@example.com" }

// PUT /users/1
{ "is_active": false }

// POST /addresses/
{ "email_address": "asha.home@example.com", "user_id": 1 }
```

---

## Migrations (Alembic)

Schema is never created by app startup. It is owned by Alembic.

```mermaid
flowchart LR
    A[Edit model in models/] --> B["alembic revision --autogenerate -m 'msg'"]
    B --> C[Alembic diffs model metadata vs DB]
    C --> D[Review the generated script in alembic/versions]
    D --> E["alembic upgrade head"]
    E --> F[PostgreSQL schema updated]
    F --> G[Restart or let --reload pick it up]
```

`alembic/env.py` imports `Base` plus every model and assigns
`target_metadata = Base.metadata`, which is what makes autogenerate aware of each
table. `compare_type=True` catches column type changes as well.

It also imports the **app's engine** from `database.py`, so migrations always
target the same database as the app. `alembic.ini` carries no `sqlalchemy.url`.

Current revision: `0002_create_inspections` (head).

- `0001_initial` — `users`, `addresses`, indexes, FK constraint
- `0002_create_inspections` — `inspections`

See [POSTGRES.md](POSTGRES.md) for the full runbook.

---

## Cargo detection (SAM + YOLO)

A signed-in user can run cargo detection on their own submission:

```powershell
# is the detector usable?
Invoke-RestMethod http://127.0.0.1:8000/portal/detection/availability -WebSession $s

# run it — blocks 16-45 s on CPU
Invoke-RestMethod -Method Post http://127.0.0.1:8000/portal/submissions/16/detect -WebSession $s
```

The pipeline (SAM ViT-B + a cargo-tuned YOLO-OBB detector) lives in a separate
project as a Jupyter notebook, in a virtualenv with torch, ultralytics,
segment-anything, transformers and Open3D — about 5.5 GB. Those cannot be merged
into this app's environment, so the detector runs as a **subprocess** and the two
sides meet at a JSON file.

| Endpoint | Who | Purpose |
|---|---|---|
| `GET /portal/detection/availability` | user | Whether the detector can run, and why not |
| `POST /portal/submissions/{id}/detect` | owner | Run detection (cached; `?force=true` to re-run) |
| `GET /portal/submissions/{id}/detection` | owner | Last stored result |
| `GET /portal/submissions/{id}/detection/overlay` | owner | Annotated PNG |
| `GET /admin/submissions/{id}/detection` | admin | Any result, read-only |

**It reports what is visible, not what it weighs.** The pipeline's measurement
stage returns *relative* volume from normalised camera intrinsics, so
`volume_m3` and `estimated_weight_kg` stay `null` rather than holding
dimensionless numbers in metrically-named columns.

Enable it in `.env` (only the interpreter lives outside this repo — the
pipeline and weights are vendored in `detector/`):

```ini
DETECTION_ENABLED=true
DETECTION_PYTHON=C:\path\to\AI-Driven Cargo Detection\.venv\Scripts\python.exe
```

Then verify the paths without starting the server:

```powershell
.venv\Scripts\python.exe -m services.detection
```

Full detail — including how notebook cells are executed, the three outcomes a
caller must distinguish, and the known false positives — is in
**[DETECTION.md](DETECTION.md)**.

---

## Running the project

Full step-by-step runbook: **[POSTGRES.md](POSTGRES.md)**.

```powershell
cd C:\Users\Abhijeet\Desktop\FastAPI\awesome-project

# 1. dependencies
uv sync

# 2. connection string (once)
Copy-Item .env.example .env

# 3. start PostgreSQL
powershell -ExecutionPolicy Bypass -File scripts\start_postgres.ps1

# 4. create the database + apply migrations (first run only)
uv run python scripts\setup_postgres.py

# 5. run the API
uv run uvicorn main:app --reload
```

Then open:

- UI — <http://127.0.0.1:8000/ui/>
- Swagger — <http://127.0.0.1:8000/docs>

Start over from an empty database at any time:

```powershell
uv run python scripts\setup_postgres.py --reset --password postgres
```

Smoke test:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/
# {"message":"API is running","ui":"/ui/"}
```

> `database.py` builds the engine but never calls `Base.metadata.create_all()`.
> If you skip the setup script, queries fail with `relation "users" does not exist`.

---

## Dependency notes

Two dependency descriptions exist and they are **not** aligned:

| Package | `uv.lock` (active) | `requirements.txt` |
|---|---:|---:|
| fastapi | 0.142.2 | 0.115.0 |
| sqlalchemy | 2.1.1 | 2.0.35 |
| pydantic | 2.13.5 | 2.9.0 |
| alembic | 1.20.0 | 1.20.0 |
| uvicorn | 0.54.0 | 0.30.0 |

`pyproject.toml` + `uv.lock` are the source of truth; the `.venv` in this repo was
built from them. `requirements.txt` is a legacy pip path and should be regenerated
from `uv.lock` (for example `uv export`) if pip installs still need to work.

---

## Roadmap / next steps

Ordered roughly by value:

1. Add `get_user_service()` / `get_address_service()` dependencies so routers stop
   constructing services inline.
2. Replace string `ValueError`s with typed custom exceptions and a global handler,
   so routers do not repeat try/except blocks.
3. Validate pagination bounds (`skip >= 0`, `1 <= limit <= 100` via `Query`).
4. Move CORS origins into `config.py` too, and stop defaulting to
   `allow_origins=["*"]`. (The database URL is already done.)
5. Add tests: router tests with `TestClient` against a scratch PostgreSQL schema,
   plus service unit tests.
6. Stop tracking the compiled `__pycache__/*.pyc` files that are already in git.
7. Add authentication and authorization before exposing mutating routes publicly.
8. Serve uploaded images from object storage (S3) rather than the local disk, so
   the API can run on more than one machine.