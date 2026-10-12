"""Role-based access control.

Roles map to permissions; permissions map to routes. Nothing else in the codebase
needs to know about roles — it asks `require_permission(...)` and that decides.

Two layers enforce this, deliberately:

1. **Middleware** rejects whole path prefixes before a route handler runs. Cheap,
   and it stops a request that should never have been routed.
2. **Dependencies** check the specific permission, and can also verify ownership
   ("is this *your* submission?").

Neither layer is redundant: the middleware cannot tell whether `/inspections/7`
belongs to you, and the dependency cannot cheaply gate an entire prefix.
"""

from __future__ import annotations

from enum import StrEnum

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from models.user import User
from services.security import get_current_user


class Role(StrEnum):
    USER = "user"
    ADMIN = "admin"


# --------------------------------------------------------------------------- #
# Permission catalogue
#
# `own` means "the record the caller submitted"; `any` means "any record".
# Splitting them is what stops a user editing somebody else's submission by
# changing an id in the URL.
# --------------------------------------------------------------------------- #
P_SUBMISSIONS_CREATE = "submissions:create"
P_SUBMISSIONS_READ_OWN = "submissions:read:own"
P_SUBMISSIONS_READ_ANY = "submissions:read:any"
P_SUBMISSIONS_UPDATE_OWN = "submissions:update:own"
P_SUBMISSIONS_WITHDRAW_OWN = "submissions:withdraw:own"
P_SUBMISSIONS_REVIEW_ANY = "submissions:review:any"
P_SUBMISSIONS_DELETE_ANY = "submissions:delete:any"
P_SUBMISSIONS_RESTORE_ANY = "submissions:restore:any"
P_USERS_READ_OWN = "users:read:own"
P_USERS_READ_ANY = "users:read:any"
P_USERS_MANAGE = "users:manage"
P_AUDIT_READ = "audit:read"

USER_PERMISSIONS: frozenset[str] = frozenset(
    {
        P_SUBMISSIONS_CREATE,
        P_SUBMISSIONS_READ_OWN,
        P_SUBMISSIONS_UPDATE_OWN,
        P_SUBMISSIONS_WITHDRAW_OWN,
        P_USERS_READ_OWN,
    }
)

ADMIN_PERMISSIONS: frozenset[str] = USER_PERMISSIONS | frozenset(
    {
        P_SUBMISSIONS_READ_ANY,
        P_SUBMISSIONS_REVIEW_ANY,
        P_SUBMISSIONS_DELETE_ANY,
        P_SUBMISSIONS_RESTORE_ANY,
        P_USERS_READ_ANY,
        P_USERS_MANAGE,
        P_AUDIT_READ,
    }
)

ROLE_PERMISSIONS: dict[Role, frozenset[str]] = {
    Role.USER: USER_PERMISSIONS,
    Role.ADMIN: ADMIN_PERMISSIONS,
}

#: Statuses a non-admin is allowed to set on their own submission. Review
#: decisions (`approved` / `rejected`) are deliberately absent: deciding them is
#: the whole point of the approval workflow.
SELF_ASSIGNABLE_STATUSES: frozenset[str] = frozenset({"draft", "submitted"})


def has_permission(user: User, permission: str) -> bool:
    role = _coerce_role(user.role)
    return permission in ROLE_PERMISSIONS[role]


def has_role(user: User, role: Role) -> bool:
    return _coerce_role(user.role) == role


def is_admin(user: User) -> bool:
    return has_role(user, Role.ADMIN)


def _coerce_role(value: str | Role) -> Role:
    """Tolerate an unknown stored role by degrading to the least privilege."""
    try:
        return Role(value)
    except ValueError:
        return Role.USER


# --------------------------------------------------------------------------- #
# Dependencies
# --------------------------------------------------------------------------- #
def require_permission(permission: str):
    """Dependency factory: `user = Depends(require_permission(P_AUDIT_READ))`."""

    def _check(user: User = Depends(get_current_user)) -> User:
        if not has_permission(user, permission):
            # 403: the caller is authenticated but lacks the permission. Unlike
            # the ownership checks, this does reveal that the resource area
            # exists — which is intentional, so the UI can explain the refusal.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Your role ({user.role}) cannot perform this action.",
            )
        return user

    return _check


def require_role(role: Role):
    def _check(user: User = Depends(get_current_user)) -> User:
        if not has_role(user, role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action requires the '{role}' role.",
            )
        return user

    return _check


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not is_admin(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required.",
        )
    return user


def can_view_submission(user: User, submission_owner_id: int) -> bool:
    """Ownership OR review rights."""
    return submission_owner_id == user.id or has_permission(
        user, P_SUBMISSIONS_READ_ANY
    )


def can_modify_submission(user: User, submission_owner_id: int) -> bool:
    """Own submission, or an admin."""
    return submission_owner_id == user.id or has_permission(
        user, P_SUBMISSIONS_REVIEW_ANY
    )


def permissions_for(user: User) -> list[str]:
    """What this user may do. Sent to the UI so it can hide what will 403."""
    return sorted(ROLE_PERMISSIONS[_coerce_role(user.role)])