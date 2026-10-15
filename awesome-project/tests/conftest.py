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
# No test may call the real OpenAI Decisions API: it costs money, needs a
# key, and would make the suite depend on the network. Real env vars win over
# `.env` in pydantic-settings, so this setdefault pins the feature off even
# when a developer's `.env` has it switched on. Individual tests re-enable it
# with monkeypatch and a stubbed `decide`.
os.environ.setdefault("OPENAI_DECISION_ENABLED", "false")
os.environ.setdefault("OPENAI_API_KEY", "")

import pytest  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

# The app's own base-path constant, so every request in the suite is built from
# the same value the routes are registered with (see `app/api/v1/__init__.py`).
from app.api.v1 import API_PREFIX  # noqa: E402

TEST_URL = os.environ["DATABASE_URL"]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="session", autouse=True)
def _isolated_image_storage(tmp_path_factory):
    """Point the service's image directory at a throwaway folder.

    Every other part of a test is rolled back: the database transaction is, so
    rows and audit entries vanish. The image *file* is not, because it is
    written straight to disk. Without this, each run leaves one file per upload
    behind in the real `storage/inspections/` — which is how that directory
    reached 1,442 orphaned files with only 2 live rows.

    Redirecting the directory is better than cleaning up afterwards: nothing is
    created in the first place, so a crashed run cannot leave litter either.
    """
    import app.services.inspection_service as inspection_service

    sandbox = tmp_path_factory.mktemp("inspection-images")
    previous = inspection_service.STORAGE_DIR
    inspection_service.STORAGE_DIR = sandbox
    try:
        yield sandbox
    finally:
        inspection_service.STORAGE_DIR = previous


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
    """TestClient bound to the same rolled-back session.

    The RBAC middleware reads `app.state.session_factory` directly, so it must
    be pointed at the test transaction too — otherwise it would open its own
    connection and not see any of the test's uncommitted rows.
    """
    from fastapi.testclient import TestClient

    from app.database import database
    import main

    def override_get_db():
        try:
            yield db
        finally:
            pass

    main.app.dependency_overrides[database.get_db] = override_get_db
    previous_factory = getattr(main.app.state, "session_factory", None)
    main.app.state.session_factory = lambda: db

    with TestClient(main.app, raise_server_exceptions=False) as c:
        yield c

    main.app.dependency_overrides.clear()
    main.app.state.session_factory = previous_factory


@pytest.fixture
def admin_client(db):
    """A client signed in as an administrator.

    The cross-user `/inspections/...` routes are RBAC-protected, so any test
    exercising those needs this rather than the plain `client`.
    """
    from fastapi.testclient import TestClient

    from app.database import database
    import main
    from app.models.user import User
    def override_get_db():
        try:
            yield db
        finally:
            pass

    main.app.dependency_overrides[database.get_db] = override_get_db
    previous_factory = getattr(main.app.state, "session_factory", None)
    main.app.state.session_factory = lambda: db

    db.add(User(name="Admin", email="admin@example.com",
                role="admin",
                password_hash=__import__(
                    "app.core.security", fromlist=["hash_password"]
                ).hash_password("quay-crane-42")))
    db.commit()

    with TestClient(main.app, raise_server_exceptions=False) as c:
        r = c.post(API_PREFIX + "/auth/login",
                    json={"email": "admin@example.com", "password": "quay-crane-42"})
        assert r.status_code == 200, r.text
        yield c

    main.app.dependency_overrides.clear()
    main.app.state.session_factory = previous_factory


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