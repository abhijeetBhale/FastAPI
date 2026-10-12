"""Add tags, an audit log, and idempotency keys.

* `tags` + `inspection_tags` — a many-to-many join, the standard way to attach
  free-form labels to a record.
* `audit_log` — who did what, to which entity, and when.
* `idempotency_keys` — lets a retried POST return the original response instead
  of creating a duplicate row.

Revision ID: 0008_tags_audit_and_idempotency
Revises: 0007_cargo_types_lookup
Create Date: 2026-10-12

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0008_tags_audit_and_idempotency"
down_revision: Union[str, Sequence[str], None] = "0007_cargo_types_lookup"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- timestamps the models expect ------------------------------------
    op.add_column("users", sa.Column("created_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE users SET created_at = now() WHERE created_at IS NULL")
    op.alter_column("users", "created_at", nullable=False)
    op.create_index("ix_users_email", "users", ["email"])

    # ---- tags (many-to-many with inspections) ----------------------------
    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("colour", sa.String(length=7), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tags_id", "tags", ["id"])
    op.create_index("ix_tags_name", "tags", ["name"], unique=True)

    op.create_table(
        "inspection_tags",
        sa.Column("inspection_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("inspection_id", "tag_id"),
    )
    op.create_index("ix_inspection_tags_tag_id", "inspection_tags", ["tag_id"])
    op.create_foreign_key(
        "fk_inspection_tags_inspection_id",
        "inspection_tags",
        "inspections",
        ["inspection_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_inspection_tags_tag_id",
        "inspection_tags",
        "tags",
        ["tag_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.create_index("ix_inspections_created_at", "inspections", ["created_at"])

    op.add_column("inspections", sa.Column("estimated_weight_kg", sa.Float(), nullable=True))
    op.add_column("inspections", sa.Column("volume_m3", sa.Float(), nullable=True))

    # ---- audit log -------------------------------------------------------
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        # JSONB: queryable, and avoids a second table for variable detail.
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_log_action", "audit_log", ["action"])
    op.create_index("ix_audit_log_entity", "audit_log", ["entity_type", "entity_id"])
    op.create_foreign_key(
        "fk_audit_log_actor_user_id", "audit_log", "users", ["actor_user_id"], ["id"]
    )

    # ---- idempotency -----------------------------------------------------
    op.create_table(
        "idempotency_keys",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("endpoint", sa.String(length=200), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index("ix_idempotency_keys_expires_at", "idempotency_keys", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_idempotency_keys_expires_at", table_name="idempotency_keys")
    op.drop_table("idempotency_keys")

    op.drop_constraint("fk_audit_log_actor_user_id", "audit_log", type_="foreignkey")
    op.drop_index("ix_audit_log_entity", table_name="audit_log")
    op.drop_index("ix_audit_log_action", table_name="audit_log")
    op.drop_table("audit_log")

    op.drop_constraint("fk_inspection_tags_tag_id", "inspection_tags", type_="foreignkey")
    op.drop_constraint(
        "fk_inspection_tags_inspection_id", "inspection_tags", type_="foreignkey"
    )
    op.drop_index("ix_inspection_tags_tag_id", table_name="inspection_tags")
    op.drop_table("inspection_tags")

    op.drop_index("ix_inspections_created_at", table_name="inspections")
    op.drop_column("inspections", "volume_m3")
    op.drop_column("inspections", "estimated_weight_kg")

    op.drop_index("ix_tags_name", table_name="tags")
    op.drop_index("ix_tags_id", table_name="tags")
    op.drop_table("tags")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_column("users", "created_at")