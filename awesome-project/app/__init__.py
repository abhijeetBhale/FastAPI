"""The application package.

Everything that runs inside the process lives here; the repository root keeps
only what is *about* the project rather than part of it — `main.py` (the ASGI
entry point), `alembic/`, `detector/`, `docs/`, `scripts/`, `static/`,
`storage/` and `tests/`.

The layers, and the direction dependencies are allowed to point:

    api/v1/endpoints   HTTP: routing, status codes, request/response shapes
      -> services      business rules and database writes
        -> models      SQLAlchemy tables (one class per table)
        -> database    engine, session factory, declarative Base

`core/` holds what every layer may import (settings, password/token handling,
global exception handlers) and depends on nothing but the standard library and
third-party packages. `schemas/` are the Pydantic contracts and are read by
both the endpoints and the services. `middleware/` runs before routing, so it
sees requests the routers never do.
"""
