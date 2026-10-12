"""Pytest fixtures.

Every test runs against a real PostgreSQL database named `*_test`, created once
per session and rolled back between tests via nested transactions.

A scratch *database* (not an in-memory SQLite) matters here: the schema uses
PostgreSQL-specific features — JSONB, partial indexes, functional unique
indexes — that SQLite cannot express, so an in-memory substitute would not test
the code that actually runs.
"""

from __future__ import annotations

import os

# Must be set before `config` is imported anywhere.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/awesome_project_test",
)
os.environ.setdefault("SQL_ECHO", "false")

import pytest  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

TEST_URL = os.environ["DATABASE_URL"]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="session", autouse=True)
def _database():
    """Create the test database and apply every migration."""
    admin_url = TEST_URL.rsplit("/", 1)[0] + "/postgres"
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")

    with admin.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS awesome_project_test WITH (FORCE)"))
        conn.execute(text("CREATE DATABASE awesome_project_test"))
    admin.dispose()

    cfg = Config(os.path.join(ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(ROOT, "alembic"))
    command.upgrade(cfg, "head")

    yield

    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS awesome_project_test WITH (FORCE)"))
    admin.dispose()


@pytest.fixture
def db():
    """A session whose changes are rolled back after the test."""
    engine = create_engine(TEST_URL)
    connection = engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)

    try:
        yield Session()
    finally:
        # A test that hits an IntegrityError has already invalidated the
        # transaction; rolling it back again would warn.
        if transaction.is_active:
            transaction.rollback()
        connection.close()
        engine.dispose()


@pytest.fixture
def client(db):
    """TestClient bound to the same rolled-back session."""
    from fastapi.testclient import TestClient

    import database
    import main

    def override_get_db():
        try:
            yield db
        finally:
            pass

    main.app.dependency_overrides[database.get_db] = override_get_db
    with TestClient(main.app, raise_server_exceptions=False) as c:
        yield c
    main.app.dependency_overrides.clear()


@pytest.fixture
def png_bytes():
    """A tiny valid PNG, 8x8."""

    def _make(width: int = 8, height: int = 8, rgb=(10, 120, 200)) -> bytes:
        import struct
        import zlib

        def chunk(tag: bytes, body: bytes) -> bytes:
            return (
                struct.pack(">I", len(body))
                + tag
                + body
                + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)
            )

        raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b"")
        )

    return _make