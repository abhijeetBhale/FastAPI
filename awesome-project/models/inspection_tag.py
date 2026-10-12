from sqlalchemy import Column, ForeignKey, Index, Table
from database import Base

# Association table for the many-to-many between inspections and tags.
# Declared as a plain Table rather than a mapped class: it carries no data of
# its own beyond the two foreign keys.
inspection_tags = Table(
    "inspection_tags",
    Base.metadata,
    Column(
        "inspection_id",
        ForeignKey("inspections.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "tag_id",
        ForeignKey("tags.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    # The composite primary key already indexes inspection_id; this covers the
    # reverse lookup (which tags point at this inspection). Created in 0008.
    Index("ix_inspection_tags_tag_id", "tag_id"),
)