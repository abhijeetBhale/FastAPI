"""Store cargo detection results.

The SAM/YOLO detector writes a JSON report per image — boxes, scores, mask
coverage, per-object breakdown. It varies in shape as the pipeline evolves, so
it goes into a single JSONB column rather than a family of columns that would
need a migration every time a field is added.

`volume_m3` and `estimated_weight_kg` are deliberately NOT populated here. The
pipeline's measurement stage produces *relative* volume (normalised camera
intrinsics, `fx = fy = width`) and every metric output scales linearly off a
hardcoded `REFERENCE_WIDTH_METERS = 2.0`. Writing those numbers into columns
named for cubic metres and kilograms would look authoritative while being
dimensionless. They stay null until calibration is real.

Revision ID: 0011_detection_results
Revises: 0010_roles_and_reviews
Create Date: 2026-10-12

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0011_detection_results"
down_revision: Union[str, Sequence[str], None] = "0010_roles_and_reviews"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "inspections",
        sa.Column(
            "detection_result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "inspections", sa.Column("detected_at", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "inspections",
        sa.Column("detection_overlay", sa.String(length=255), nullable=True),
    )

    # The portal lists each submission's detection state, and "which have never
    # been run" is the query that drives it. Without this the filter is a full
    # scan of every live submission.
    op.create_index(
        "ix_inspections_detected_at",
        "inspections",
        ["detected_at"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_inspections_detected_at", table_name="inspections")
    op.drop_column("inspections", "detection_overlay")
    op.drop_column("inspections", "detected_at")
    op.drop_column("inspections", "detection_result")
