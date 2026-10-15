from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool

# Importing `database` gives us the app's already-configured engine, so
# migrations and the app always target the same database. This removes the old
# duplication where the URL was written in both alembic.ini and
# app/database/database.py.
from app.database.base import Base
from app.database.database import engine
# Importing the package registers every model on Base.metadata. Listing them
# individually here is what previously let a new model be forgotten, which
# makes autogenerate silently emit nothing.
import app.models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=str(engine.url),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # NullPool: a migration process connects, runs, and exits. The app's pooled
    # engine is not needed here.
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()