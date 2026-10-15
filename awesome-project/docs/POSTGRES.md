# PostgreSQL — Step-by-Step Guide

This project runs on **PostgreSQL only**. SQLite has been removed: there is no
`app.db`, no SQLite branch in `app/database/database.py`, and no cross-database migration
script. The database is created empty and populated only by the API.

---

## Current state

| Piece | Value |
|---|---|
| Server | PostgreSQL 17.11 |
| Windows service | `postgresql-x64-17` (auto-start) |
| Database | `awesome_project` |
| Role / password | `postgres` / `postgres` |
| Host / port | `localhost:5432` |
| Driver | `psycopg` 3.3.6 |
| Schema | `0002_create_inspections` (head) |
| Tables | `users`, `addresses`, `inspections`, `alembic_version` |

---

## How the connection is wired

The single most important structural change: there is **one** connection string,
and everything reads it.

```text
.env  ──DATABASE_URL──>  app/core/config.py  (Settings)
                              │
                              ├──>  app/database/database.py   builds the engine
                              │
                              └──>  alembic/env.py imports that same engine
```

So `alembic upgrade head` and the running app always target the same database.
Previously the URL was written in both `app/database/database.py` and `alembic.ini`, which
meant editing one could silently point the app and the migrations at different
databases. `alembic.ini` no longer contains `sqlalchemy.url` at all.

---

## One-time setup (already done on this machine)

If you are on a clean machine, do these once.

### 1. Install PostgreSQL

```powershell
winget install --id PostgreSQL.PostgreSQL.17 --exact
```

The installer takes several minutes and can appear to hang while it works —
wait for it. It registers the service `postgresql-x64-17` and sets the
`postgres` password to `postgres`.

Verify:

```powershell
Get-Service postgresql-x64-17
```

### 2. Install the Python dependencies

```powershell
cd C:\Users\Abhijeet\Desktop\FastAPI\awesome-project
uv sync
```

This installs `psycopg[binary]`, `pydantic-settings`, `python-multipart` and
`sqlalchemy` alongside FastAPI and Alembic.

### 3. Create the `.env` file

```powershell
Copy-Item .env.example .env
```

`.env` contains:

```ini
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/awesome_project?connect_timeout=10
SQL_ECHO=false
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=10
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=1800
```

| Variable | Meaning |
|---|---|
| `DATABASE_URL` | connection string. `+psycopg` is SQLAlchemy's dialect name for psycopg 3 |
| `SQL_ECHO` | log every SQL statement |
| `DB_POOL_SIZE` | persistent pooled connections |
| `DB_MAX_OVERFLOW` | extra connections allowed above the pool size |
| `DB_POOL_TIMEOUT` | seconds to wait for a free connection before erroring |
| `DB_POOL_RECYCLE` | recycle connections after this many seconds (avoids stale ones) |

`?connect_timeout=10` matters. Without it, a stopped server makes the app **hang**
on startup instead of failing with a clear error.

---

## Service lifecycle

There are two services in play: the **PostgreSQL** server (a Windows service) and
the **FastAPI** dev server (a foreground process).

### PostgreSQL — Windows service `postgresql-x64-17`

Its startup type is `Automatic`, so **it starts by itself when Windows boots**.
In practice you rarely need to touch it.

```powershell
# status (works as a normal user)
Get-Service postgresql-x64-17

# is it actually accepting connections?
& "C:\Program Files\PostgreSQL\17\bin\pg_isready.exe" -h 127.0.0.1 -p 5432
# -> 127.0.0.1:5432 - accepting connections
```

**Start / stop — these need an Administrator shell.** Right-click PowerShell →
*Run as administrator*, then:

```powershell
Start-Service postgresql-x64-17     # start
Stop-Service  postgresql-x64-17     # stop
Restart-Service postgresql-x64-17   # restart
```

From the Services console instead: `services.msc` → find `postgresql-x64-17` →
Start / Stop / Restart.

> **Why the elevated shell matters.** `Get-Service` only *reads* the service
> manager, so it works for any user. `Start-Service` / `Stop-Service` *control*
> it, and a normal shell fails with
> `Cannot open postgresql-x64-17 service on computer '.'`. That is not a bug in
> your setup — it is Windows refusing an unprivileged request.

**Scripted check — works either way:**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_postgres.ps1
```

It reports the status, and if the server happens to be down it tells you the
exact elevated command to run instead of failing cryptically. Exit codes:

| Code | Meaning |
|---:|---|
| `0` | running and accepting connections |
| `2` | not running, and this shell is not elevated |
| `3` | running but not yet accepting connections |

### What a stopped server looks like

The engine is created lazily, so **importing the app still succeeds** — the
failure appears on the first query:

```text
sqlalchemy.exc.OperationalError:
(psycopg.OperationalError) connection to server at "127.0.0.1",
port 5432 failed: Connection refused
```

### PostgreSQL logs

```text
C:\Program Files\PostgreSQL\17\data\log\
```

Tail the latest file when diagnosing:

```powershell
Get-ChildItem "C:\Program Files\PostgreSQL\17\data\log\*.log" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1 | Get-Content -Tail 20
```

### FastAPI — foreground process

Not a Windows service. It runs in your terminal and stops when you press
<kbd>Ctrl</kbd>+<kbd>C</kbd>.

```powershell
# run it
.venv\Scripts\python.exe -m uvicorn main:app --reload

# a different port
.venv\Scripts\python.exe -m uvicorn main:app --port 8010

# background (for scripts/tests)
Start-Process .venv\Scripts\python.exe `
    -ArgumentList "-m uvicorn main:app --port 8010" -WindowStyle Hidden

# stop a backgrounded one
Get-Process python | Where-Object { $_.Path -like "*FastAPI*" } | Stop-Process -Force
```

`--reload` restarts the app when a file changes, so leave it on while developing.

### Correct order

```text
1. PostgreSQL   (automatic at boot, or Start-Service if you stopped it)
2. migrations   (first run only)
3. FastAPI
```

Starting FastAPI before PostgreSQL is fine to *attempt* — the app will import —
but every request will fail until the server is up.

---

## Everyday use

### Step 1 — check/start the server

```powershell
cd C:\Users\Abhijeet\Desktop\FastAPI\awesome-project
powershell -ExecutionPolicy Bypass -File scripts\start_postgres.ps1
```

### Step 2 — create the database (first run only)

```powershell
.venv\Scripts\python.exe scripts\setup_postgres.py
```

It prompts for the `postgres` password, creates `awesome_project` if it does not
exist, and applies all migrations. Safe to re-run — an existing database is left
alone.

Non-interactive equivalent:

```powershell
.venv\Scripts\python.exe scripts\setup_postgres.py --password postgres
```

### Step 3 — run the API

```powershell
.venv\Scripts\python.exe -m uvicorn main:app --reload
```

Stop it with <kbd>Ctrl</kbd>+<kbd>C</kbd>.

### Step 4 — open it

```text
UI          http://127.0.0.1:8000/ui/
Swagger UI  http://127.0.0.1:8000/docs
```

---

## Starting completely fresh

To wipe the database and rebuild the schema from nothing — **this deletes all
data**:

```powershell
.venv\Scripts\python.exe scripts\setup_postgres.py --reset --password postgres
```

What it does:

1. Terminates any other sessions on `awesome_project`
2. `DROP DATABASE awesome_project`
3. `CREATE DATABASE awesome_project`
4. Runs `alembic upgrade head` from `base`, so both revisions replay
5. Prints the resulting table list

Confirmed result — every table empty, schema at head:

```text
 users | addresses | inspections |     schema_version
-------+-----------+-------------+-------------------------
     0 |         0 |           0 | 0002_create_inspections
```

Primary keys restart at 1 because the sequences are recreated with the database.

---

## Verifying it is working

### The app is talking to PostgreSQL

```powershell
.venv\Scripts\python.exe -c "import database; print(database.engine.dialect.driver)"
# -> psycopg
```

### Migrations are current and match the models

```powershell
.venv\Scripts\python.exe -m alembic current
# -> 0002_create_inspections (head)

.venv\Scripts\python.exe -m alembic check
# -> No new upgrade operations detected.
```

`alembic check` is the important one: it diffs your models against the live
PostgreSQL schema and fails if they have drifted. It is worth putting in CI.

### Inspect the database directly

`psql` is not on `PATH`, so use the full path:

```powershell
$env:PGPASSWORD = "postgres"
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" -h localhost -U postgres -d awesome_project -c "\dt"
```

Or add it to `PATH` for the session:

```powershell
$env:PATH += ";C:\Program Files\PostgreSQL\17\bin"
psql -h localhost -U postgres -d awesome_project -c "\dt"
```

Useful queries:

```sql
\d users                       -- columns and types
\l                             -- list databases
\dt                            -- list tables
SELECT version_num FROM alembic_version;
```

### Round-trip through the API

```powershell
# create
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/users/ `
  -ContentType "application/json" `
  -Body '{"name":"Test User","email":"test@example.com"}'

# read
Invoke-RestMethod http://127.0.0.1:8000/users/
```

---

## Schema

Created by two migrations, applied in order.

```text
0001_initial              users + addresses tables, indexes, FK
0002_create_inspections   inspections table
```

`alembic_version` tracks the position:

```text
base → 0001_initial → 0002_create_inspections (head)
```

Roll back one step:

```powershell
.venv\Scripts\python.exe -m alembic downgrade -1
```

Roll all the way back:

```powershell
.venv\Scripts\python.exe -m alembic downgrade base
```

Roll forward again:

```powershell
.venv\Scripts\python.exe -m alembic upgrade head
```

> Never add a `--reset` to a deployment pipeline. Deployments should always use
> `upgrade head`, so migrations actually run.

---

## What the models produce on PostgreSQL

SQLAlchemy types are dialect-neutral, so the same revision files apply to both
backends. On PostgreSQL they render as:

| Model type | PostgreSQL column |
|---|---|
| `Mapped[int]` + `primary_key=True` | `integer` + a `SERIAL` sequence |
| `Mapped[str]` + `String(n)` | `character varying(n)` |
| `Mapped[bool]` | `boolean` (true `BOOLEAN`, not `smallint`) |
| `Mapped[datetime]` + `DateTime` | `timestamp without time zone` |
| `Mapped[Optional[int]]` | `integer`, nullable |

`inspections.image_url` is a Python `@property`, not a column, so it has no
database representation on either backend.

---

## Troubleshooting

### `connection to server at "localhost", port 5432 failed: Connection refused`

The service is not running. Start it from an **Administrator** PowerShell:

```powershell
Start-Service postgresql-x64-17
```

Or run `services.msc` and start it from the console. See
[Service lifecycle](#service-lifecycle) for why the elevated shell is needed.

### `password authentication failed for user "postgres"`

Wrong password in `.env`. Fix `DATABASE_URL` to match, or reset it:

```powershell
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" -U postgres -d postgres
ALTER USER postgres PASSWORD 'postgres';
```

### `database "awesome_project" does not exist`

Run the setup script — the engine is created lazily, so the app imports fine
until the first query.

```powershell
.venv\Scripts\python.exe scripts\setup_postgres.py --password postgres
```

### `relation "users" does not exist`

The database exists but migrations were never applied.

```powershell
.venv\Scripts\python.exe -m alembic upgrade head
```

### The app hangs instead of erroring on startup

`connect_timeout` is missing from `DATABASE_URL`. Add `?connect_timeout=10`.

### `alembic check` reports pending operations

Your models changed without a matching migration:

```powershell
.venv\Scripts\python.exe -m alembic revision --autogenerate -m "describe change"
# review the generated file
.venv\Scripts\python.exe -m alembic upgrade head
```

### Changing the password or host later

Edit `DATABASE_URL` in `.env` only. No code changes — the app, Alembic and the
setup script all read the same variable.

---

## Moving to a hosted database later

RDS, Neon, Supabase or any managed PostgreSQL need one change:

```ini
DATABASE_URL=postgresql+psycopg://user:pass@host:5432/dbname?connect_timeout=10
```

Then run `alembic upgrade head` against it. No code changes. The only thing to
check is that your provider allows connections from your machine's IP, and that
`sslmode` is handled if required (`?sslmode=require`).