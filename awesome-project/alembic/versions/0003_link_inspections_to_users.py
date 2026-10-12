"""Connect inspections to users and addresses.

The UI captured name + email into `inspections` as free text, so the same person
could appear twice with different capitalisation and nothing tied an inspection
to the `users` table at all. This migration:

1. adds `user_id` (required) and `address_id` (optional) as foreign keys,
2. backfills `user_id` by matching each inspection's email against `users`
   case-insensitively, creating the user when no match exists,
3. leaves `address_id` NULL — historical rows carry no address data, and the
   column is optional,
4. drops the duplicated `name` / `email` columns, leaving `users` as the single
   source of truth for who a person is.

Revision ID: 0003_link_inspections_to_users
Revises: 0002_create_inspections
Create Date: 2026-10-12

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_link_inspections_to_users"
down_revision: Union[str, Sequence[str], None] = "0002_create_inspections"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    op.add_column("inspections", sa.Column("user_id", sa.Integer(), nullable=True))
    op.add_column("inspections", sa.Column("address_id", sa.Integer(), nullable=True))

    users = sa.table(
        "users",
        sa.column("id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("email", sa.String),
        sa.column("is_active", sa.Boolean),
    )
    inspections = sa.table(
        "inspections",
        sa.column("id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("email", sa.String),
        sa.column("user_id", sa.Integer),
    )

    existing = {
        row.email.lower(): row.id
        for row in bind.execute(sa.select(users.c.id, users.c.email))
    }

    for row in bind.execute(
        sa.select(inspections.c.id, inspections.c.name, inspections.c.email)
    ).fetchall():
        key = (row.email or "").strip().lower()
        if key in existing:
            user_id = existing[key]
        else:
            # is_active must be given explicitly: the column is NOT NULL and its
            # default lives in the SQLAlchemy model, not in the database.
            bind.execute(
                users.insert().values(
                    name=row.name, email=row.email, is_active=True
                )
            )
            # Read the id back rather than relying on RETURNING, which a
            # lightweight `sa.table()` construct does not always populate.
            user_id = bind.execute(
                sa.select(users.c.id).where(users.c.email == row.email)
            ).scalar()
            existing[key] = user_id

        bind.execute(
            inspections.update()
            .where(inspections.c.id == row.id)
            .values(user_id=user_id)
        )

    op.alter_column("inspections", "user_id", nullable=False)
    op.create_foreign_key(
        "fk_inspections_user_id", "inspections", "users", ["user_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_inspections_address_id",
        "inspections",
        "addresses",
        ["address_id"],
        ["id"],
    )
    op.create_index("ix_inspections_user_id", "inspections", ["user_id"])
    op.create_index("ix_inspections_address_id", "inspections", ["address_id"])

    op.drop_column("inspections", "email")
    op.drop_column("inspections", "name")


def downgrade() -> None:
    bind = op.get_bind()

    op.add_column(
        "inspections", sa.Column("name", sa.String(length=100), nullable=True)
    )
    op.add_column(
        "inspections", sa.Column("email", sa.String(length=100), nullable=True)
    )

    users = sa.table(
        "users",
        sa.column("id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("email", sa.String),
    )
    inspections = sa.table(
        "inspections",
        sa.column("id", sa.Integer),
        sa.column("user_id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("email", sa.String),
    )
    for row in bind.execute(
        sa.select(inspections.c.id, inspections.c.user_id)
    ).fetchall():
        user = bind.execute(
            sa.select(users.c.name, users.c.email).where(users.c.id == row.user_id)
        ).fetchone()
        if user is None:
            raise RuntimeError(
                f"Cannot restore inspection {row.id}: user {row.user_id} was not found"
            )
        bind.execute(
            inspections.update()
            .where(inspections.c.id == row.id)
            .values(name=user.name, email=user.email)
        )

    op.drop_index("ix_inspections_address_id", table_name="inspections")
    op.drop_index("ix_inspections_user_id", table_name="inspections")
    op.drop_constraint("fk_inspections_address_id", "inspections", type_="foreignkey")
    op.drop_constraint("fk_inspections_user_id", "inspections", type_="foreignkey")
    op.drop_column("inspections", "address_id")
    op.drop_column("inspections", "user_id")