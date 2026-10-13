# PostgreSQL — Manual Command Reference

Copy-paste commands for controlling PostgreSQL and the API on this machine.

> **The one thing to know:** starting and stopping a Windows service requires an
> **Administrator** PowerShell. Everything else — checking status, connecting,
> running queries — works as a normal user.
>
> Open one with: <kbd>Win</kbd>+<kbd>X</kbd> → *Terminal (Admin)*, or
> right-click PowerShell → *Run as administrator*.

---

## The service

| | |
|---|---|
| Name | `postgresql-x64-17` |
| Startup type | `Automatic` — starts on Windows boot |
| Data directory | `C:\Program Files\PostgreSQL\17\data` |
| Binaries | `C:\Program Files\PostgreSQL\17\bin` |
| Logs | `C:\Program Files\PostgreSQL\17\data\log\` |
| Port | 5432 |

---

## Status and health

These work **without admin**.

```powershell
# service status
Get-Service postgresql-x64-17

# is it actually accepting connections (the real health check)
& "C:\Program Files\PostgreSQL\17\bin\pg_isready.exe" -h 127.0.0.1 -p 5432
# -> 127.0.0.1:5432 - accepting connections
```

| Output | Meaning |
|---|---|
| `accepting connections` | healthy, start the API |
| `no response` | server down or starting |
| `no attempt` | nothing listening on port 5432 |

---

## Start, stop, restart

**Admin required.**

```powershell
# one at a time
Start-Service   postgresql-x64-17
Stop-Service    postgresql-x64-17
Restart-Service postgresql-x64-17

# start and wait until it is actually up
Start-Service postgresql-x64-17
(Get-Service postgresql-x64-17).WaitForStatus("Running", [TimeSpan]::FromSeconds(30))
```

### Without admin

If you get `Cannot open postgresql-x64-17 service on computer '.'` or
`Access is denied`, you are in a normal shell. Use either:

**Services console** — <kbd>Win</kbd>+<kbd>R</kbd> → `services.msc` → find
`postgresql-x64-17` → right-click → Start / Stop.

**Launch an elevated shell from here:**

```powershell
Start-Process powershell -Verb RunAs -ArgumentList "-NoExit", "-Command", `
  "Get-Service postgresql-x64-17"
```

That triggers a UAC prompt — click *Yes* — and opens an Administrator window.

---

## Change the startup type

**Admin required.**

```powershell
Set-Service -Name postgresql-x64-17 -StartupType Automatic   # start on boot
Set-Service -Name postgresql-x64-17 -StartupType Manual      # manual only
Set-Service -Name postgresql-x64-17 -StartupType Disabled    # never
```

Current setting is `Automatic`.

---

## Connect with psql

`psql` is **not** on `PATH`, so either use the full path each time or add it once
per shell session.

```powershell
# full path every time
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" -h 127.0.0.1 -p 5432 -U postgres -d awesome_project

# or add to PATH for this session
$env:PATH += ";C:\Program Files\PostgreSQL\17\bin"
psql -h 127.0.0.1 -p 5432 -U postgres -d awesome_project

# set the password once per session to avoid the prompt
$env:PGPASSWORD = "postgres"
```

### One-liners

```powershell
$env:PGPASSWORD = "postgres"
$psql = "C:\Program Files\PostgreSQL\17\bin\psql.exe"

# list databases
& $psql -h 127.0.0.1 -U postgres -d postgres -c "\l"

# list tables in the app database
& $psql -h 127.0.0.1 -U postgres -d awesome_project -c "\dt"

# describe a table
& $psql -h 127.0.0.1 -U postgres -d awesome_project -c "\d users"

# row counts
& $psql -h 127.0.0.1 -U postgres -d awesome_project -c `
  "select (select count(*) from users) users,
          (select count(*) from addresses) addresses,
          (select count(*) from inspections) inspections"

# current schema version
& $psql -h 127.0.0.1 -U postgres -d awesome_project -tAc `
  "select version_num from alembic_version"

# server version
& $psql -h 127.0.0.1 -U postgres -d postgres -tAc "select version()"
```

### Useful psql meta-commands

Once inside `psql`:

| Command | Does |
|---|---|
| `\l` | list databases |
| `\dt` | list tables |
| `\d tablename` | describe a table |
| `\du` | list roles |
| `\conninfo` | show the current connection |
| `\q` | quit |

---

## Create / reset the database

```powershell
cd C:\Users\Abhijeet\Desktop\FastAPI\awesome-project

# create if missing + apply migrations (safe to re-run)
.venv\Scripts\python.exe scripts\setup_postgres.py --password postgres

# DROP and rebuild from scratch — DELETES ALL DATA
.venv\Scripts\python.exe scripts\setup_postgres.py --reset --password postgres
```

Neither needs admin — they connect as the `postgres` role over TCP.

---

## Migrations

```powershell
cd C:\Users\Abhijeet\Desktop\FastAPI\awesome-project

.venv\Scripts\python.exe -m alembic current      # what revision is applied
.venv\Scripts\python.exe -m alembic check        # do models match the schema?
.venv\Scripts\python.exe -m alembic upgrade head # apply everything
.venv\Scripts\python.exe -m alembic downgrade -1 # roll back one step
.venv\Scripts\python.exe -m alembic downgrade base
.venv\Scripts\python.exe -m alembic history      # the revision graph
```

---

## The API server

Not a Windows service — a foreground process. <kbd>Ctrl</kbd>+<kbd>C</kbd> stops it.

```powershell
cd C:\Users\Abhijeet\Desktop\FastAPI\awesome-project

# run with auto-reload
.venv\Scripts\python.exe -m uvicorn main:app --reload

# different port
.venv\Scripts\python.exe -m uvicorn main:app --port 8010

# backgrounded
Start-Process .venv\Scripts\python.exe `
    -ArgumentList "-m uvicorn main:app --port 8010" -WindowStyle Hidden

# stop a backgrounded one
Get-Process python | Where-Object { $_.Path -like "*FastAPI*" } | Stop-Process -Force
```

---

## Logs

```powershell
# PostgreSQL
Get-ChildItem "C:\Program Files\PostgreSQL\17\data\log\*.log" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1 | Get-Content -Tail 30

# API (in the terminal you started it from)
```

---

## When the server is down

The app still **imports** — SQLAlchemy creates engines lazily, so the failure only
shows up on the first request:

```text
sqlalchemy.exc.OperationalError: (psycopg.OperationalError)
connection to server at "127.0.0.1", port 5432 failed: Connection refused
```

Fix:

```powershell
Start-Service postgresql-x64-17    # admin shell
```

---

## Order of operations

```text
1. PostgreSQL    automatic at boot; Start-Service if you stopped it
2. migrations    setup_postgres.py — first run only
3. API           uvicorn main:app --reload
```

---

## Quick diagnostics

| Symptom | Check | Fix |
|---|---|---|
| `Connection refused` | `pg_isready` | start the service (admin) |
| `Access is denied` | — | you need an Administrator shell |
| `password authentication failed` | — | password is `postgres` |
| `database "awesome_project" does not exist` | `\l` | run `setup_postgres.py` |
| `relation "users" does not exist` | `\dt` | `alembic upgrade head` |
| app hangs on startup | — | add `?connect_timeout=10` to `DATABASE_URL` |
| port 5432 busy | `Get-NetTCPConnection -LocalPort 5432` | stop the other PostgreSQL |