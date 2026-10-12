from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import String, Integer, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from database import Base

if TYPE_CHECKING:
    from .user import User


class AuditLog(Base):
    """Append-only record of who did what to which entity.

    `detail` is JSONB so variable extra context can be stored and queried
    without a second table.
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        # Indexed via migration 0008; declared here only so autogenerate does
        # not try to remove them. Listing a column in `index=True` would create
        # a duplicate single-column index.
        Index("ix_audit_log_entity", "entity_type", "entity_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    detail: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now()
    )

    def __repr__(self) -> str:
        return f"<AuditLog {self.action} {self.entity_type}#{self.entity_id}>"