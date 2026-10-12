"""Administrator routes.

Everything here is gated twice: `RoleAuthorizationMiddleware` rejects non-admins
on the `/admin` prefix before routing, and each route additionally declares the
permission it needs. Redundant on purpose — if the middleware prefix is ever
mis-registered, the dependency still refuses.

Review workflow: an admin approves or rejects a submission, optionally with a
note. Every decision is written to `audit_log` with the acting admin, so the
trail says who decided what.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database import get_db
from models.audit_log import AuditLog
from models.cargo_type import CargoType
from models.inspection import INSPECTION_STATUSES, Inspection
from models.user import User
from schemas.responses.inspection import (
    InspectionListResponse,
    InspectionResponse,
)
from schemas.responses.user import UserResponse
from services.audit_service import AuditService
from services.inspection_service import InspectionService, resolve_image_path
from services.rbac import (
    P_AUDIT_READ,
    P_SUBMISSIONS_READ_ANY,
    P_USERS_MANAGE,
    Role,
    require_permission,
)

router = APIRouter(prefix="/admin", tags=["Admin"])


def _page(rows, total, skip, limit) -> InspectionListResponse:
    return InspectionListResponse(
        items=rows,
        total=total,
        skip=skip,
        limit=limit,
        pages=-(-total // limit) if limit else 0,
    )


# --------------------------------------------------------------------- #
# submissions
# --------------------------------------------------------------------- #
@router.get(
    "/submissions",
    response_model=InspectionListResponse,
    summary="Every submission, across all users",
)
def list_all_submissions(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    user_id: Optional[int] = Query(None, ge=1),
    cargo_type: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    tag: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    include_deleted: bool = Query(False),
    sort: str = Query("-created_at"),
    admin: User = Depends(require_permission(P_SUBMISSIONS_READ_ANY)),
    db: Session = Depends(get_db),
):
    """No `user_id` is forced here — the whole point is to see everyone."""
    try:
        page = InspectionService(db).list_inspections(
            skip=skip, limit=limit, user_id=user_id, cargo_type=cargo_type,
            status=status_filter, tag=tag, search=search,
            include_deleted=include_deleted, sort=sort,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return _page(
        [InspectionResponse.model_validate(i) for i in page.items],
        page.total, page.skip, page.limit,
    )


@router.get(
    "/submissions/pending",
    response_model=InspectionListResponse,
    summary="The review queue",
)
def pending_submissions(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    admin: User = Depends(require_permission(P_SUBMISSIONS_READ_ANY)),
    db: Session = Depends(get_db),
):
    """Submitted, not yet decided, oldest first — the work queue."""
    page = InspectionService(db).list_inspections(
        skip=skip, limit=limit, status="submitted", sort="created_at"
    )
    return _page(
        [InspectionResponse.model_validate(i) for i in page.items],
        page.total, page.skip, page.limit,
    )


@router.get("/submissions/{inspection_id}", response_model=InspectionResponse)
def get_any_submission(
    inspection_id: int,
    include_deleted: bool = Query(False),
    admin: User = Depends(require_permission(P_SUBMISSIONS_READ_ANY)),
    db: Session = Depends(get_db),
):
    """Read any submission, including one an owner has withdrawn.

    Admins need the withdrawn rows to audit a dispute, so `include_deleted`
    is honoured here rather than filtering them out unconditionally.
    """
    svc = InspectionService(db)
    # `get_inspection` hides soft-deleted rows; a direct get includes them.
    insp = (
        db.get(Inspection, inspection_id)
        if include_deleted
        else svc.get_inspection(inspection_id)
    )
    if not insp:
        raise HTTPException(status_code=404, detail="Submission not found")
    return insp


def _decide(
    inspection_id: int,
    new_status: str,
    note: str | None,
    admin: User,
    db: Session,
) -> Inspection:
    if new_status not in ("approved", "rejected"):
        raise HTTPException(
            status_code=422,
            detail="A decision must be 'approved' or 'rejected'.",
        )

    svc = InspectionService(db)
    insp = svc.get_inspection(inspection_id)
    if not insp:
        raise HTTPException(status_code=404, detail="Submission not found")

    if insp.status == new_status:
        raise HTTPException(
            status_code=409,
            detail=f"Already {new_status}.",
        )

    insp.status = new_status
    insp.status_note = (note or "").strip() or None
    insp.reviewed_by = admin.id
    insp.reviewed_at = datetime.now()
    insp.updated_at = insp.reviewed_at

    AuditService(db).record(
        action=new_status,
        entity_type="inspection",
        entity_id=insp.id,
        actor_user_id=admin.id,
        detail={"note": insp.status_note, "previous_status": None},
    )
    db.commit()
    db.refresh(insp)
    return insp


@router.post(
    "/submissions/{inspection_id}/approve",
    response_model=InspectionResponse,
    summary="Approve a submission",
)
def approve_submission(
    inspection_id: int,
    note: Optional[str] = Query(None, max_length=300),
    admin: User = Depends(require_permission(P_SUBMISSIONS_READ_ANY)),
    db: Session = Depends(get_db),
):
    return _decide(inspection_id, "approved", note, admin, db)


@router.post(
    "/submissions/{inspection_id}/reject",
    response_model=InspectionResponse,
    summary="Reject a submission",
)
def reject_submission(
    inspection_id: int,
    note: Optional[str] = Query(None, max_length=300),
    admin: User = Depends(require_permission(P_SUBMISSIONS_READ_ANY)),
    db: Session = Depends(get_db),
):
    return _decide(inspection_id, "rejected", note, admin, db)


@router.post("/submissions/bulk", summary="Approve or reject many at once")
def bulk_decide(
    payload: dict,
    admin: User = Depends(require_permission(P_SUBMISSIONS_READ_ANY)),
    db: Session = Depends(get_db),
):
    """Body: `{"ids": [1, 2], "action": "approve", "note": "..."}`.

    Each id is processed independently: one bad row does not abort the batch, and
    the response reports what happened to each.
    """
    ids = payload.get("ids") or []
    action = (payload.get("action") or "").lower()
    note = payload.get("note")

    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=422, detail="'ids' must be a non-empty list")
    if action not in ("approve", "reject"):
        raise HTTPException(status_code=422, detail="'action' must be approve or reject")

    target = "approved" if action == "approve" else "rejected"
    results = []
    for raw_id in ids[:200]:  # bound the work per request
        try:
            insp_id = int(raw_id)
        except (TypeError, ValueError):
            results.append({"id": raw_id, "ok": False, "reason": "not an id"})
            continue
        try:
            _decide(insp_id, target, note, admin, db)
            results.append({"id": insp_id, "ok": True, "status": target})
        except HTTPException as exc:
            results.append(
                {"id": insp_id, "ok": False, "reason": exc.detail}
            )
    return {"processed": len(results), "results": results}


@router.get("/submissions/{inspection_id}/image", summary="Serve any image")
def admin_submission_image(
    inspection_id: int,
    include_deleted: bool = Query(True),
    admin: User = Depends(require_permission(P_SUBMISSIONS_READ_ANY)),
    db: Session = Depends(get_db),
):
    """Admin counterpart of `/portal/submissions/{id}/image`.

    Defaults to including withdrawn rows: an admin reviewing a dispute needs
    the image even after the owner withdrew the submission.
    """
    insp = (
        db.get(Inspection, inspection_id)
        if include_deleted
        else InspectionService(db).get_inspection(inspection_id)
    )
    if not insp:
        raise HTTPException(status_code=404, detail="Submission not found")
    path = resolve_image_path(insp)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Image file is missing")
    return FileResponse(
        path,
        media_type=insp.image_content_type,
        filename=insp.image_original_name,
    )


@router.post("/submissions/{inspection_id}/restore", response_model=InspectionResponse)
def restore_submission(
    inspection_id: int,
    admin: User = Depends(require_permission(P_SUBMISSIONS_READ_ANY)),
    db: Session = Depends(get_db),
):
    insp = InspectionService(db).restore(inspection_id)
    if not insp:
        raise HTTPException(status_code=404, detail="Not found or not deleted")
    return insp


@router.delete(
    "/submissions/{inspection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Permanently delete",
)
def purge_submission(
    inspection_id: int,
    admin: User = Depends(require_permission(P_SUBMISSIONS_READ_ANY)),
    db: Session = Depends(get_db),
):
    if not InspectionService(db).hard_delete(inspection_id):
        raise HTTPException(status_code=404, detail="Submission not found")


# --------------------------------------------------------------------- #
# dashboard
# --------------------------------------------------------------------- #
@router.get("/stats", summary="Platform-wide numbers")
def platform_stats(
    admin: User = Depends(require_permission(P_SUBMISSIONS_READ_ANY)),
    db: Session = Depends(get_db),
):
    svc = InspectionService(db)
    by_status = dict(
        db.execute(
            select(Inspection.status, func.count(Inspection.id))
            .where(Inspection.deleted_at.is_(None))
            .group_by(Inspection.status)
        ).all()
    )
    by_cargo = [
        {"slug": c.slug, "label": c.label, "count": n}
        for c, n in db.execute(
            select(CargoType, func.count(Inspection.id))
            .join(Inspection, Inspection.cargo_type_id == CargoType.id)
            .where(Inspection.deleted_at.is_(None))
            .group_by(CargoType.id, CargoType.slug, CargoType.label)
            .order_by(func.count(Inspection.id).desc())
        ).all()
    ]
    return {
        "stats": svc.stats(),
        "by_status": by_status,
        "by_cargo": by_cargo,
        "users": db.execute(select(func.count(User.id))).scalar_one(),
        "admins": db.execute(
            select(func.count(User.id)).where(User.role == Role.ADMIN.value)
        ).scalar_one(),
    }


# --------------------------------------------------------------------- #
# audit
# --------------------------------------------------------------------- #
@router.get("/audit", summary="Recent audit entries")
def read_audit(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    entity_type: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    admin: User = Depends(require_permission(P_AUDIT_READ)),
    db: Session = Depends(get_db),
):
    q = select(AuditLog)
    if entity_type:
        q = q.where(AuditLog.entity_type == entity_type)
    if action:
        q = q.where(AuditLog.action == action)
    q = q.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())

    total = db.execute(
        select(func.count()).select_from(q.order_by(None).subquery())
    ).scalar_one()
    rows = db.execute(q.offset(skip).limit(limit)).scalars().all()

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "items": [
            {
                "id": r.id,
                "action": r.action,
                "entity_type": r.entity_type,
                "entity_id": r.entity_id,
                "actor_user_id": r.actor_user_id,
                "detail": r.detail,
                "created_at": r.created_at,
            }
            for r in rows
        ],
    }


# --------------------------------------------------------------------- #
# users
# --------------------------------------------------------------------- #
@router.get("/users", response_model=list[UserResponse], summary="All users")
def list_users_admin(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    admin: User = Depends(require_permission(P_USERS_MANAGE)),
    db: Session = Depends(get_db),
):
    return list(db.execute(select(User).order_by(User.id).offset(skip).limit(limit)).scalars())


@router.post("/users/{user_id}/role", response_model=UserResponse)
def set_role(
    user_id: int,
    role: str = Query(..., pattern="^(user|admin)$"),
    admin: User = Depends(require_permission(P_USERS_MANAGE)),
    db: Session = Depends(get_db),
):
    if user_id == admin.id and role == "user":
        # Guard against an admin demoting themselves and locking everyone out.
        raise HTTPException(
            status_code=400,
            detail="You cannot remove your own administrator role.",
        )
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.role = role
    AuditService(db).record(
        action="set_role", entity_type="user", entity_id=user.id,
        actor_user_id=admin.id, detail={"role": role},
    )
    db.commit()
    db.refresh(user)
    return user