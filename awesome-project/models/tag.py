from typing import TYPE_CHECKING

from datetime import datetime

from sqlalchemy import String, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base, utcnow

if TYPE_CHECKING:  # avoids a circular import at runtime
    from .inspection import Inspection


class Tag(Base):
    """Free-form label, attached to inspections via inspection_tags."""

    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    colour: Mapped[str | None] = mapped_column(String(7), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )

    # The other side of the many-to-many.
    inspections: Mapped[list["Inspection"]] = relationship(
        secondary="inspection_tags",
        back_populates="tags",
    )

    def __repr__(self) -> str:
        return f"<Tag {self.name}>"