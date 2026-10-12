"""Replace the free-text `cargo_type` with a lookup table.

`inspections.cargo_type` was a plain string, so 'scrap-steel', 'Scrap Steel' and
'SCRAP STEEL' were three different values, and nothing stored the density that
the weight calculation needs.

This creates `cargo_types` with a density (kg/m3) seeded from the cargo project
notes, backfills existing inspections by matching their string, and replaces the
column with a foreign key.

Revision ID: 0007_cargo_types_lookup
Revises: 0006_status_soft_delete
Create Date: 2026-10-12

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007_cargo_types_lookup"
down_revision: Union[str, Sequence[str], None] = "0006_status_soft_delete"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# slug, label, density kg/m3, description
SEED = [
    ("scrap-steel", "Scrap Steel", 7850.0, "Ferrous scrap metal"),
    ("thermal-coal", "Thermal Coal", 800.0, "Steam-grade coal"),
    ("construction-gravel", "Construction Gravel", 1700.0, "Crushed aggregate"),
    ("agricultural-grain", "Agricultural Grain", 750.0, "Bulk grain"),
    ("other", "Other", None, "Unclassified load"),
]


def upgrade() -> None:
    op.create_table(
        "cargo_types",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=50), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("density_kg_m3", sa.Float(), nullable=True),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cargo_types_slug", "cargo_types", ["slug"], unique=True)

    cargo_types = sa.table(
        "cargo_types",
        sa.column("id", sa.Integer),
        sa.column("slug", sa.String),
        sa.column("label", sa.String),
        sa.column("density_kg_m3", sa.Float),
        sa.column("description", sa.String),
    )
    bind = op.get_bind()
    slug_to_id = {}
    for slug, label, density, description in SEED:
        bind.execute(
            cargo_types.insert().values(
                slug=slug,
                label=label,
                density_kg_m3=density,
                description=description,
            )
        )
        # Read the id back rather than relying on RETURNING, which a
        # lightweight `sa.table()` construct does not always populate.
        slug_to_id[slug] = bind.execute(
            sa.select(cargo_types.c.id).where(cargo_types.c.slug == slug)
        ).scalar()

    # Add the FK column and backfill from the existing free-text value.
    op.add_column("inspections", sa.Column("cargo_type_id", sa.Integer(), nullable=True))
    inspections = sa.table(
        "inspections",
        sa.column("id", sa.Integer),
        sa.column("cargo_type", sa.String),
        sa.column("cargo_type_id", sa.Integer),
    )

    fallback = slug_to_id["other"]
    for row in bind.execute(
        sa.select(inspections.c.id, inspections.c.cargo_type)
    ).fetchall():
        raw = (row.cargo_type or "").strip()
        matched = slug_to_id.get(raw.lower().replace(" ", "-"))
        bind.execute(
            inspections.update()
            .where(inspections.c.id == row.id)
            .values(cargo_type_id=matched or fallback)
        )

    op.alter_column("inspections", "cargo_type_id", nullable=False)
    op.create_foreign_key(
        "fk_inspections_cargo_type_id",
        "inspections",
        "cargo_types",
        ["cargo_type_id"],
        ["id"],
    )
    op.create_index("ix_inspections_cargo_type_id", "inspections", ["cargo_type_id"])

    op.drop_column("inspections", "cargo_type")


def downgrade() -> None:
    op.add_column(
        "inspections", sa.Column("cargo_type", sa.String(length=50), nullable=True)
    )
    bind = op.get_bind()
    cargo_types = sa.table("cargo_types", sa.column("id", sa.Integer), sa.column("slug", sa.String))
    inspections = sa.table(
        "inspections", sa.column("id", sa.Integer),
        sa.column("cargo_type_id", sa.Integer), sa.column("cargo_type", sa.String),
    )
    for row in bind.execute(
        sa.select(inspections.c.id, inspections.c.cargo_type_id)
    ).fetchall():
        slug = bind.execute(
            sa.select(cargo_types.c.slug).where(cargo_types.c.id == row.cargo_type_id)
        ).scalar()
        bind.execute(
            inspections.update()
            .where(inspections.c.id == row.id)
            .values(cargo_type=slug)
        )

    op.drop_index("ix_inspections_cargo_type_id", table_name="inspections")
    op.drop_constraint("fk_inspections_cargo_type_id", "inspections", type_="foreignkey")
    op.drop_column("inspections", "cargo_type_id")
    op.drop_index("ix_cargo_types_slug", table_name="cargo_types")
    op.drop_table("cargo_types")