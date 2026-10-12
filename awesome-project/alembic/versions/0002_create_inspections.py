"""Create inspections table.

Revision ID: 0002_create_inspections
Revises: 0001_initial
Create Date: 2026-10-12

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_create_inspections"
down_revision: Union[str, Sequence[str], None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "inspections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=100), nullable=False),
        sa.Column("cargo_type", sa.String(length=50), nullable=False),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.Column("image_filename", sa.String(length=255), nullable=False),
        sa.Column("image_original_name", sa.String(length=255), nullable=False),
        sa.Column("image_content_type", sa.String(length=50), nullable=False),
        sa.Column("image_size_bytes", sa.Integer(), nullable=False),
        sa.Column("image_width", sa.Integer(), nullable=True),
        sa.Column("image_height", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_inspections_id", "inspections", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_inspections_id", table_name="inspections")
    op.drop_table("inspections")