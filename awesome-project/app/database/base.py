"""The declarative `Base` every model inherits, and the shared UTC clock.

Kept apart from `app/database/database.py`, so a module that only declares
tables does
not have to import (and therefore construct) an engine to do it. That matters
for Alembic: `alembic/env.py` imports `Base.metadata` to autogenerate, and the
migration scripts must not open a connection just to read the schema.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import DeclarativeBase


# Base class for all SQLAlchemy models
class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    """Naive UTC now — the one clock every column default and timestamped
    write uses.

    The `DateTime` columns are timezone-naive, so aware values must not reach
    them: psycopg would cast through the session timezone and shift the stored
    instant. Storing UTC-naive and rendering with a `Z` suffix in the API
    (`schemas.responses.envelope.iso_utc`) gives the ISO 8601 UTC contract in
    `docs/API_CONVENTIONS.md` §6 without a schema migration.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
