"""Audit trail.

Every write is recorded so you can ask "who changed this, and when" later
without adding logging calls to every service method.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog

class AuditService:
    def __init__(self, db: Session):
        self.db = db

    def record(
        self,
        *,
        action: str,
        entity_type: str,
        entity_id: Optional[int] = None,
        actor_user_id: Optional[int] = None,
        detail: Optional[dict[str, Any]] = None,
    ) -> AuditLog:
        """Add an entry to the log.

        Does not commit — it joins the caller's transaction so the audit row and
        the change it describes succeed or fail together.
        """
        entry = AuditLog(
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            actor_user_id=actor_user_id,
            detail=detail,
        )
        self.db.add(entry)
        return entry

    def for_entity(
        self, entity_type: str, entity_id: int
    ) -> list[AuditLog]:
        """History for one record, newest first."""
        return list(
            self.db.query(AuditLog)
            .filter(AuditLog.entity_type == entity_type)
            .filter(AuditLog.entity_id == entity_id)
            .order_by(AuditLog.created_at.desc())
            .all()
        )