"""Add credentials to users for the self-service portal.

`password_hash` holds a PBKDF2-HMAC-SHA256 digest (never the password itself).
It is NULL for accounts that predate this migration — those users must use
"set password" on first login, and cannot log in until they do.

Revision ID: 0009_user_credentials
Revises: 0008_tags_audit_and_idempotency
Create Date: 2026-10-12

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009_user_credentials"
down_revision: Union[str, Sequence[str], None] = "0008_tags_audit_and_idempotency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=True))
    op.add_column(
        "users", sa.Column("password_set_at", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "users",
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "is_admin", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    # A partial index: only credentialed accounts are ever looked up by it.
    op.create_index(
        "ix_users_password_hash",
        "users",
        ["password_hash"],
        postgresql_where=sa.text("password_hash IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_users_password_hash", table_name="users")
    op.drop_column("users", "is_admin")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "password_set_at")
    op.drop_column("users", "password_hash")