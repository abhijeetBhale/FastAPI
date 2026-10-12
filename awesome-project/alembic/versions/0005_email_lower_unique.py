"""Enforce case-insensitive uniqueness on users.email.

The service already matched on `lower(email)`, but the UNIQUE index was
case-sensitive, so `Race@x.com` and `race@x.com` could both be inserted by two
concurrent requests that both passed the lookup.

Any pre-existing duplicates are resolved first, keeping the oldest row.

Revision ID: 0005_email_lower_unique
Revises: 0004_add_phone_drop_addresses
Create Date: 2026-10-12

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# `alembic_version.version_num` is VARCHAR(32), so the id must fit in 32
# characters or the migration cannot record itself.
revision: str = "0005_email_lower_unique"
down_revision: Union[str, Sequence[str], None] = "0004_add_phone_drop_addresses"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Keep the lowest id for each case-insensitive email, delete the rest.
    op.execute(
        """
        DELETE FROM users
        WHERE id NOT IN (
            SELECT MIN(id) FROM users GROUP BY lower(email)
        )
        """
    )
    op.create_index(
        "uq_users_email_lower", "users", [sa.text("lower(email)")], unique=True
    )
    # The plain unique index is now redundant.
    op.drop_index("ix_users_email", table_name="users")


def downgrade() -> None:
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.drop_index("uq_users_email_lower", table_name="users")