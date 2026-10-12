from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import String, Integer, DateTime, Index, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base

if TYPE_CHECKING:  # avoids a circular import at runtime
    from .inspection import Inspection


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        # Case-insensitive uniqueness. The plain UNIQUE on email() is not
        # enough: 'Race@x.com' and 'race@x.com' are distinct to PostgreSQL.
        Index("uq_users_email_lower", text("lower(email)"), unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    email: Mapped[str] = mapped_column(String(100), index=True)
    # Optional. Stored digits-only; formatting is stripped on input.
    phone: Mapped[Optional[str]] = mapped_column(String(20), index=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now()
    )

    # Eager-loaded: listing a user's inspections would otherwise be N+1.
    inspections: Mapped[list["Inspection"]] = relationship(
        back_populates="user", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<User {self.id} {self.email}>"