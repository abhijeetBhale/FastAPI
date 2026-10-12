"""Add inspection status, timestamps and soft delete.

* `status` moves an inspection through a workflow instead of leaving every row
  in the same state.
* `updated_at` records the last modification.
* `deleted_at` enables soft delete: rows are hidden but retained, which is why
  `DELETE` no longer destroys history.

Revision ID: 0006_status_soft_delete
Revises: 0005_email_lower_unique
Create Date: 2026-10-12

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# Kept within the 32-character limit of alembic_version.version_num.
revision: str = "0006_status_soft_delete"
down_revision: Union[str, Sequence[str], None] = "0005_email_lower_unique"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

STATUSES = ("draft", "submitted", "approved", "rejected")


def upgrade() -> None:
    op.add_column(
        "inspections",
        sa.Column("status", sa.String(length=20), nullable=False, server_default="submitted"),
    )
    op.add_column("inspections", sa.Column("updated_at", sa.DateTime(), nullable=True))
    op.add_column("inspections", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    op.add_column("inspections", sa.Column("status_note", sa.String(length=300), nullable=True))

    op.create_index("ix_inspections_status", "inspections", ["status"])
    op.create_index("ix_inspections_deleted_at", "inspections", ["deleted_at"])
    # Partial index: only live rows are ever filtered on.
    op.create_index(
        "ix_inspections_created_at_live",
        "inspections",
        ["created_at"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_check_constraint(
        "ck_inspections_status",
        "inspections",
        sa.text("status IN ('draft','submitted','approved','rejected')"),
    )

    # Backfill updated_at for rows created before this column existed.
    op.execute("UPDATE inspections SET updated_at = created_at WHERE updated_at IS NULL")


def downgrade() -> None:
    op.drop_constraint("ck_inspections_status", "inspections", type_="check")
    op.drop_index("ix_inspections_created_at_live", table_name="inspections")
    op.drop_index("ix_inspections_deleted_at", table_name="inspections")
    op.drop_index("ix_inspections_status", table_name="inspections")
    op.drop_column("inspections", "status_note")
    op.drop_column("inspections", "deleted_at")
    op.drop_column("inspections", "updated_at")
    op.drop_column("inspections", "status")