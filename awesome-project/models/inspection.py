from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from database import Base


class Inspection(Base):
    __tablename__ = "inspections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # ---- user-supplied inputs -------------------------------------------
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(100), nullable=False)
    cargo_type: Mapped[str] = mapped_column(String(50), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # ---- stored image metadata (the uploaded file lives on disk) --------
    image_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    image_original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    image_content_type: Mapped[str] = mapped_column(String(50), nullable=False)
    image_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    # Best-effort dimensions from the file header (no Pillow needed).
    image_width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    image_height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now()
    )

    # Computed so the response schema can expose a working link via
    # `from_attributes`, without storing a redundant column.
    @property
    def image_url(self) -> str:
        return f"/inspections/{self.id}/image"