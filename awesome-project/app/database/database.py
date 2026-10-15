"""The database connection: engine, session factory, and the `get_db` dependency.

The `Base` every model inherits and the shared `utcnow()` clock live in
`base.py` — a module that declares tables needs those two and nothing else, so
it should not have to import (and construct) an engine to get them.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings

settings = get_settings()

# The URL comes from config (env var or .env) — never hardcoded here.
SQLALCHEMY_DATABASE_URL = settings.database_url

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    echo=settings.sql_echo,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_recycle=settings.db_pool_recycle,
)

# Session factory — each request gets its own session
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# FastAPI dependency: yields a DB session per request
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()