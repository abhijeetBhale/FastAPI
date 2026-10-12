"""Add a phone number to users and remove the addresses table.

`addresses` held nothing but `email_address` + `user_id` — a second email with
no location in it. Since `users.email` already covers "who is this person", the
table was redundant. Phone is the detail that was genuinely missing, so this
migration:

1. adds `users.phone` (nullable, so existing rows survive),
2. drops `inspections.address_id` and its foreign key / index,
3. drops the `addresses` table.

Revision ID: 0004_add_phone_drop_addresses
Revises: 0003_link_inspections_to_users
Create Date: 2026-10-12

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_add_phone_drop_addresses"
down_revision: Union[str, Sequence[str], None] = "0003_link_inspections_to_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("phone", sa.String(length=20), nullable=True))
    op.create_index("ix_users_phone", "users", ["phone"])

    # The optional per-inspection address link goes away with the table.
    op.drop_index("ix_inspections_address_id", table_name="inspections")
    op.drop_constraint(
        "fk_inspections_address_id", "inspections", type_="foreignkey"
    )
    op.drop_column("inspections", "address_id")

    op.drop_index("ix_addresses_id", table_name="addresses")
    op.drop_table("addresses")


def downgrade() -> None:
    op.create_table(
        "addresses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email_address", sa.String(length=100), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    op.create_index("ix_addresses_id", "addresses", ["id"], unique=False)

    op.add_column("inspections", sa.Column("address_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_inspections_address_id",
        "inspections",
        "addresses",
        ["address_id"],
        ["id"],
    )
    op.create_index("ix_inspections_address_id", "inspections", ["address_id"])

    op.drop_index("ix_users_phone", table_name="users")
    op.drop_column("users", "phone")