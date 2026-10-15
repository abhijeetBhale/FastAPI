from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, Float, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.database.base import Base

class CargoType(Base):
    """Lookup table. Densities are typical bulk values in kg/m3."""

    __tablename__ = "cargo_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    density_kg_m3: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    def __repr__(self) -> str:
        return f"<CargoType {self.slug}>"