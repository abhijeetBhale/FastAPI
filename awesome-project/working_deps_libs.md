# Working Dependencies and Libraries

## Python Version

| Source | Version |
|---|---|
| Project requirement | Python `>=3.12` |
| Active uv environment | Python `3.12.10` |

The project does not define an upper Python version limit. The `uv.lock` file contains resolution markers for Python versions below `3.13`, Python `3.13`, and Python `3.14` or newer.

## Direct Project Dependencies

These are declared in `pyproject.toml`:

| Package | Declared requirement | Locked version | Purpose |
|---|---:|---:|---|
| `alembic` | `>=1.20.0` | `1.20.0` | SQLAlchemy database migrations |
| `fastapi[standard]` | `>=0.142.2` | `0.142.2` | Web API framework and standard tooling |

## Application Libraries Used Directly

These libraries are imported by the application code or used by its configuration:

| Package | Current uv-locked version | Used for |
|---|---:|---|
| `fastapi` | `0.142.2` | API routes, dependencies, HTTP exceptions, response models |
| `sqlalchemy` | `2.1.1` | Database engine, sessions, ORM models, relationships |
| `pydantic` | `2.13.5` | Request and response schema validation |
| `email-validator` | `2.3.0` | Validation for `EmailStr` fields |
| `alembic` | `1.20.0` | Database schema migrations |
| `uvicorn` | `0.54.0` | ASGI development and production server |

## Complete uv.lock Package List

These versions are resolved in the current `uv.lock` file. Transitive dependencies are included here because they are installed as part of the working environment.

| Package | Locked version |
|---|---:|
| `agent-detector` | `2.0.0` |
| `alembic` | `1.20.0` |
| `annotated-doc` | `0.0.5` |
| `annotated-types` | `0.8.0` |
| `anyio` | `4.15.1` |
| `certifi` | `2026.7.22` |
| `click` | `8.5.0` |
| `colorama` | `0.4.6` |
| `detect-installer` | `0.2.1` |
| `dnspython` | `2.8.0` |
| `email-validator` | `2.3.0` |
| `fastapi` | `0.142.2` |
| `fastapi-cli` | `0.0.32` |
| `fastapi-cloud-cli` | `0.26.0` |
| `fastar` | `0.12.0` |
| `googleapis-common-protos` | `1.75.5` |
| `h11` | `0.16.0` |
| `httpcore` | `1.0.9` |
| `httptools` | `0.8.0` |
| `httpx` | `0.28.1` |
| `idna` | `3.20` |
| `jinja2` | `3.1.6` |
| `mako` | `1.4.3` |
| `markdown-it-py` | `4.2.0` |
| `markupsafe` | `3.0.3` |
| `mdurl` | `0.1.2` |
| `opentelemetry-api` | `1.45.0` |
| `opentelemetry-exporter-http-transport` | `0.66b0` |
| `opentelemetry-exporter-otlp-common` | `0.66b0` |
| `opentelemetry-exporter-otlp-proto-common` | `1.45.0` |
| `opentelemetry-exporter-otlp-proto-http` | `1.45.0` |
| `opentelemetry-proto` | `1.45.0` |
| `opentelemetry-sdk` | `1.45.0` |
| `opentelemetry-semantic-conventions` | `0.66b0` |
| `protobuf` | `7.36.2` |
| `pydantic` | `2.13.5` |
| `pydantic-core` | `2.46.5` |
| `pydantic-extra-types` | `2.11.1` |
| `pydantic-settings` | `2.15.0` |
| `pygments` | `2.21.0` |
| `python-dotenv` | `1.2.4` |
| `python-multipart` | `0.0.32` |
| `pyyaml` | `6.0.3` |
| `rich` | `15.0.0` |
| `rich-toolkit` | `0.20.5` |
| `rignore` | `0.8.1` |
| `sentry-sdk` | `2.71.0` |
| `shellingham` | `1.5.4` |
| `sqlalchemy` | `2.1.1` |
| `starlette` | `1.7.0` |
| `typer` | `0.27.2` |
| `typing-extensions` | `4.16.0` |
| `typing-inspection` | `0.4.4` |
| `urllib3` | `2.8.0` |
| `uvicorn` | `0.54.0` |
| `uvloop` | `0.23.0` |
| `watchfiles` | `1.3.0` |
| `websockets` | `17.1` |

## `requirements.txt` Pins

The current `requirements.txt` contains a separate, older set of exact pins:

| Package | `requirements.txt` pin |
|---|---:|
| `fastapi` | `0.115.0` |
| `uvicorn[standard]` | `0.30.0` |
| `sqlalchemy` | `2.0.35` |
| `alembic` | `1.20.0` |
| `pydantic[email]` | `2.9.0` |

## Dependency Source of Truth

This project currently has two dependency descriptions:

- `pyproject.toml` and `uv.lock` are used by uv commands such as `uv run` and `uv sync`.
- `requirements.txt` contains separate exact pins for pip-based installation.

The versions are not fully aligned. For example:

```text
uv.lock:          FastAPI 0.142.2, SQLAlchemy 2.1.1, Pydantic 2.13.5
requirements.txt: FastAPI 0.115.0, SQLAlchemy 2.0.35, Pydantic 2.9.0
```

For reproducible uv-based development, use `pyproject.toml` together with `uv.lock`. If pip installation is also required, update `requirements.txt` to match the selected source of truth.

## Installation Commands

Using uv:

```powershell
uv sync
uv run uvicorn main:app --reload
```

Using pip and `requirements.txt`:

```powershell
pip install -r requirements.txt
uvicorn main:app --reload
```

## Main Dependency Flow

```text
FastAPI
  -> Starlette
  -> Pydantic
  -> Uvicorn and standard server tools

Alembic
  -> SQLAlchemy
  -> Mako

Application code
  -> FastAPI
  -> SQLAlchemy
  -> Pydantic
  -> Alembic
```
