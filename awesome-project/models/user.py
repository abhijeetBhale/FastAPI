from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import String, Integer, Boolean, DateTime, Index, text
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
    # Replaces the old is_admin boolean; see migration 0010.
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="user", index=True
    )

    # ---- portal credentials ---------------------------------------------
    # NULL means "has never set a password": such an account cannot log in.
    password_hash: Mapped[Optional[str]] = mapped_column(
        String(255), index=True
    )
    password_set_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now()
    )

    @property
    def can_login(self) -> bool:
        return self.is_active and self.password_hash is not None

    @property
    def is_admin(self) -> bool:
        """Convenience view over `role`. Kept so callers need not import the
        RBAC module just to branch on this."""
        return self.role == "admin"

    # Eager-loaded: listing a user's inspections would otherwise be N+1.
    #
    # `foreign_keys` is required: inspections references users twice (user_id
    # for the submitter, reviewed_by for the admin who decided), so SQLAlchemy
    # cannot infer which one this relationship means.
    inspections: Mapped[list["Inspection"]] = relationship(
        back_populates="user",
        lazy="selectin",
        foreign_keys="Inspection.user_id",
    )

    def __repr__(self) -> str:
        return f"<User {self.id} {self.email}>"