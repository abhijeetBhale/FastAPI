"""Add roles and review tracking.

* `users.role` replaces the `is_admin` boolean with a named role, so
  authorisation can grow beyond two levels without another migration. Existing
  admins are migrated across.
* `inspections.reviewed_by` / `reviewed_at` record *who* approved or rejected a
  submission and when — otherwise the audit log is the only trace, and the row
  itself cannot say.

Revision ID: 0010_roles_and_reviews
Revises: 0009_user_credentials
Create Date: 2026-10-12

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0010_roles_and_reviews"
down_revision: Union[str, Sequence[str], None] = "0009_user_credentials"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("role", sa.String(length=20), nullable=False, server_default="user"),
    )
    # Carry the old boolean across before dropping it.
    op.execute("UPDATE users SET role = 'admin' WHERE is_admin = true")
    op.drop_column("users", "is_admin")

    op.create_check_constraint(
        "ck_users_role", "users", sa.text("role IN ('user','admin')")
    )
    op.create_index("ix_users_role", "users", ["role"])

    op.add_column(
        "inspections", sa.Column("reviewed_by", sa.Integer(), nullable=True)
    )
    op.add_column(
        "inspections", sa.Column("reviewed_at", sa.DateTime(), nullable=True)
    )
    op.create_foreign_key(
        "fk_inspections_reviewed_by",
        "inspections",
        "users",
        ["reviewed_by"],
        ["id"],
    )
    op.create_index("ix_inspections_reviewed_by", "inspections", ["reviewed_by"])

    # A submission awaiting review is the queue an admin works through.
    op.create_index(
        "ix_inspections_pending_review",
        "inspections",
        ["created_at"],
        postgresql_where=sa.text("status = 'submitted' AND deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_inspections_pending_review", table_name="inspections")
    op.drop_index("ix_inspections_reviewed_by", table_name="inspections")
    op.drop_constraint("fk_inspections_reviewed_by", "inspections", type_="foreignkey")
    op.drop_column("inspections", "reviewed_at")
    op.drop_column("inspections", "reviewed_by")

    op.drop_index("ix_users_role", table_name="users")
    op.drop_constraint("ck_users_role", "users", type_="check")

    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute("UPDATE users SET is_admin = true WHERE role = 'admin'")
    op.drop_column("users", "role")