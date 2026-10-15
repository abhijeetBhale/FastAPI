"""Store the AI decision made during the upload step.

When the OpenAI Decisions API is enabled, `create_inspection` evaluates the
uploaded image against a fixed rubric (cargo present? which type? matches the
declared type?) and stores the whole verdict — answers, probabilities,
recommendation, threshold, rubric version — in one JSONB column. Same
reasoning as `detection_result` in 0011: the rubric may gain questions, and a
column family would need a migration per question.

`decided_at` is null for rows created while the feature was off (`not_run`),
which stays distinct from a stored `ok: false` — attempted, failed, review
queue as usual.

Revision ID: 0012_ai_decision
Revises: 0011_detection_results
Create Date: 2026-10-15

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0012_ai_decision"
down_revision: Union[str, Sequence[str], None] = "0011_detection_results"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "inspections",
        sa.Column(
            "decision_result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "inspections", sa.Column("decided_at", sa.DateTime(), nullable=True)
    )

    # "Which live submissions have never been AI-decided" is the same shape
    # of filter the detection index serves — without it, that is a full scan.
    op.create_index(
        "ix_inspections_decided_at",
        "inspections",
        ["decided_at"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_inspections_decided_at", table_name="inspections")
    op.drop_column("inspections", "decided_at")
    op.drop_column("inspections", "decision_result")