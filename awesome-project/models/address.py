from sqlalchemy import String, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base  # ← connects to database.py


from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .user import User  # ← for type hinting only (avoid circular import)

class Address(Base):
    __tablename__ = "addresses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email_address: Mapped[str] = mapped_column(String(100), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))  # ← FK to User

    # Relationship: many Addresses belong to one User
    user: Mapped["User"] = relationship(back_populates="addresses")   