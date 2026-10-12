"""Application settings, read from the environment.

This is the single source of truth for the database URL, shared by
`database.py`, `alembic/env.py` and the app itself — so those three can never
drift apart.

Values come from real environment variables, or from a `.env` file next to
`pyproject.toml`. See `.env.example`.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # connect_timeout keeps a stopped server from hanging the app on startup
    # instead of failing fast with a clear error.
    database_url: str = (
        "postgresql+psycopg://postgres:postgres@localhost:5432/awesome_project"
        "?connect_timeout=10"
    )

    # Echo every SQL statement to the log. Keep False outside debugging.
    sql_echo: bool = False

    # Connection pool sizing.
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800


@lru_cache
def get_settings() -> Settings:
    """Cached so the environment is parsed once per process."""
    return Settings()