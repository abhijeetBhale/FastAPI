from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from config import get_settings

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


# FastAPI dependency: yields a DB session per request
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()