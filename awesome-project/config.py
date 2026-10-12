"""Application settings, read from the environment.

This is the single source of truth for the database URL, shared by
`database.py`, `alembic/env.py` and the app itself — so those three can never
drift apart.

Values come from real environment variables, or from a `.env` file next to
`pyproject.toml`. See `.env.example`.
"""

from __future__ import annotations

import secrets
from functools import lru_cache

from pydantic import Field, field_validator
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

    # ---- app ------------------------------------------------------------
    app_title: str = "Cargo Inspection API"
    app_version: str = "2.0.0"

    # Allowed browser origins. Never "*" in production: any website could then
    # call this API from a user's browser.
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://localhost:5173",
        ]
    )

    # ---- auth ------------------------------------------------------------
    # Signs session tokens. MUST be overridden in production via the
    # environment; the generated fallback is only for local development.
    jwt_secret: str = Field(
        default_factory=lambda: secrets.token_urlsafe(48)
    )
    jwt_expires_hours: int = 12
    # Set true once the app is served over HTTPS, so the cookie is not sent
    # in the clear.
    cookie_secure: bool = True

    # Connection pool sizing.
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800

    # ---- cargo detection (SAM + YOLO) ------------------------------------
    # Off by default. The detector needs a second interpreter holding ~5.5 GB
    # of torch/ultralytics/open3d, so it cannot be imported here — it runs as a
    # subprocess. With this false, the /detect endpoints return 503 and nothing
    # on the upload path changes.
    detection_enabled: bool = False

    # The detection project's virtualenv interpreter, NOT this app's.
    detection_python: str = (
        r"C:\Users\Abhijeet\Desktop\AI-Driven Cargo Detection\.venv\Scripts\python.exe"
    )

    # Folder holding Revamping.ipynb, models/ and images/.
    detection_project_dir: str = r"C:\Users\Abhijeet\Desktop\AI-Driven Cargo Detection"

    # SAM + YOLO on CPU runs 16-45 s per image, and the first call in a fresh
    # process pays model loading on top. 300 s leaves headroom without letting a
    # hung process pin a request worker indefinitely.
    detection_timeout: int = 300

    # Guard against two requests writing the same runner output directory. The
    # notebook's cells are not reentrant.
    detection_max_concurrency: int = 1

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        """Accept both a JSON list and a plain comma-separated string."""
        if isinstance(v, str) and not v.strip().startswith("["):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    """Cached so the environment is parsed once per process."""
    return Settings()