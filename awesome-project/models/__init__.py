"""Every model, imported in one place.

Alembic's `env.py` imports this module rather than listing individual models.
Anything not imported here is invisible to autogenerate, and the symptom is a
migration that silently generates no operations.
"""

from database import Base  # noqa: F401  re-exported for convenience

from models.cargo_type import CargoType  # noqa: F401
from models.tag import Tag  # noqa: F401
from models.inspection_tag import inspection_tags  # noqa: F401
from models.user import User  # noqa: F401
from models.inspection import (  # noqa: F401
    Inspection,
    INSPECTION_STATUSES,
    STATUS_APPROVED,
    STATUS_DRAFT,
    STATUS_REJECTED,
    STATUS_SUBMITTED,
)
from models.audit_log import AuditLog  # noqa: F401
from models.idempotency_key import IdempotencyKey  # noqa: F401

__all__ = [
    "Base",
    "AuditLog",
    "CargoType",
    "IdempotencyKey",
    "INSPECTION_STATUSES",
    "Inspection",
    "STATUS_APPROVED",
    "STATUS_DRAFT",
    "STATUS_REJECTED",
    "STATUS_SUBMITTED",
    "Tag",
    "User",
    "inspection_tags",
]