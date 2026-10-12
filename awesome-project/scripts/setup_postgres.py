#!/usr/bin/env python
"""Create (or recreate) the PostgreSQL database and apply all migrations.

Normal run — creates the database if missing, then migrates:

    .venv\\Scripts\\python.exe scripts\\setup_postgres.py

Start completely fresh — drops the database first, losing all its data:

    .venv\\Scripts\\python.exe scripts\\setup_postgres.py --reset

The script is idempotent: re-running without `--reset` is harmless.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path
from urllib.parse import quote as urlquote

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import get_settings  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def quote_ident(name: str) -> str:
    """Quote an identifier for PostgreSQL (escape embedded double quotes)."""
    return '"' + name.replace('"', '""') + '"'


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create the PostgreSQL database and apply migrations."
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="DROP the database first, then recreate it empty.",
    )
    parser.add_argument(
        "--password",
        help=(
            "Superuser password. Omit to be prompted, or set PGPASSWORD. "
            "Needed for non-interactive runs."
        ),
    )
    args = parser.parse_args()

    settings = get_settings()
    url = make_url(settings.database_url)

    if url.get_backend_name() != "postgresql":
        print(f"DATABASE_URL is {url.get_backend_name()}, not PostgreSQL.")
        print("Set DATABASE_URL in .env to a postgresql+psycopg:// URL first.")
        return 1

    db_user = url.username or "postgres"
    db_password = url.password or ""
    db_host = url.host or "localhost"
    db_port = url.port or 5432
    db_name = url.database or "awesome_project"

    admin_password = (
        args.password
        or os.environ.get("PGPASSWORD")
        or getpass.getpass("Password for the 'postgres' superuser: ")
    )
    if not admin_password:
        print("No password supplied; cannot continue.")
        return 1

    print(f"Database : {db_name}")
    print(f"Role     : {db_user}")
    print(f"Server   : {db_host}:{db_port}")
    print()

    # Connect to the always-present `postgres` database to manage the target.
    # URL-encode the credentials — these go in a connection URL, not SQL, so
    # SQL identifier quoting must NOT be applied here.
    admin = create_engine(
        "postgresql+psycopg://"
        f"{urlquote(db_user, safe='')}:{urlquote(admin_password, safe='')}"
        f"@{db_host}:{db_port}/postgres",
        isolation_level="AUTOCOMMIT",  # CREATE/DROP DATABASE cannot run in a txn
    )

    try:
        with admin.connect() as conn:
            print("[1/3] connected to the 'postgres' database")

            if args.reset:
                exists = conn.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :n"),
                    {"n": db_name},
                ).scalar()
                if exists:
                    # Evict other sessions; DROP fails otherwise.
                    conn.execute(
                        text(
                            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                            "WHERE datname = :n AND pid <> pg_backend_pid()"
                        ),
                        {"n": db_name},
                    )
                    conn.execute(text(f"DROP DATABASE {quote_ident(db_name)}"))
                    print(f"      DROPPED database '{db_name}' (all data lost)")
                else:
                    print(f"      database '{db_name}' did not exist")

            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"),
                {"n": db_name},
            ).scalar()
            if not exists:
                conn.execute(text(f"CREATE DATABASE {quote_ident(db_name)}"))
                print(f"      created database '{db_name}'")
            else:
                print(f"      database '{db_name}' already exists")

        admin.dispose()

        # Step 2: verify the app's own connection string works.
        print("\n[2/3] verifying the app connection string")
        app_engine = create_engine(settings.database_url)
        with app_engine.connect() as conn:
            ver = conn.execute(text("SELECT version()")).scalar()
            print(f"      {ver.split(',')[0]}")
        app_engine.dispose()

        # Step 3: apply every migration from scratch.
        print("\n[3/3] applying Alembic migrations")
        from alembic import command
        from alembic.config import Config

        cfg = Config(str(ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(ROOT / "alembic"))
        command.upgrade(cfg, "head")

        with create_engine(settings.database_url).connect() as conn:
            tables = [
                r[0] for r in conn.execute(
                    text(
                        "SELECT tablename FROM pg_tables "
                        "WHERE schemaname='public' ORDER BY tablename"
                    )
                )
            ]
        print(f"      tables now present: {', '.join(tables)}")

    except Exception as exc:
        print(f"\nFAILED: {type(exc).__name__}: {exc}")
        print("\nCheck that:")
        print("  - the service is running:")
        print("      Get-Service postgresql-x64-17 | Start-Service postgresql-x64-17")
        print("  - the password in --password / PGPASSWORD is correct")
        print(f"  - {db_host}:{db_port} is reachable")
        return 1

    print("\nDone. Start the API:")
    print("  .venv\\Scripts\\python.exe -m uvicorn main:app --reload")
    print("Then open http://127.0.0.1:8000/ui/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())