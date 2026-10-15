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
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1 import API_PREFIX
from app.database.base import utcnow
from app.database.database import get_db
from app.models.audit_log import AuditLog
from app.models.cargo_type import CargoType
from app.models.inspection import INSPECTION_STATUSES, Inspection
from app.models.user import User
from app.schemas.errors import jsonable_errors
from app.schemas.requests.inspection import (
    BulkDecisionRequest,
    DecisionRequest,
    InspectionCreate,
    InspectionUpdate,
)
from app.schemas.requests.user import UserRoleUpdate
from app.schemas.responses.envelope import envelope, list_links, pagination_meta
from app.schemas.responses.inspection import (
    CargoTypeOut,
    InspectionResponse,
    InspectionSummary,
    inspection_dump,
)
from app.schemas.responses.user import UserDetailResponse, UserResponse
from app.services.audit_service import AuditService
from app.services.detection import overlay_path_for
from app.services.idempotency_service import IdempotencyService
from app.services.inspection_service import InspectionService, resolve_image_path
from app.services.rbac import (
    P_AUDIT_READ,
    P_SUBMISSIONS_CREATE,
    P_SUBMISSIONS_READ_ANY,
    P_USERS_MANAGE,
    Role,
    require_permission,
)
from app.services.user_service import UserService

router = APIRouter(prefix="/admin", tags=["Admin"])


# --------------------------------------------------------------------- #
# submissions
# --------------------------------------------------------------------- #
@router.get(
    "/submissions",
    summary="Every submission, across all users",
)
def list_all_submissions(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
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
        skip = (page - 1) * per_page
        result = InspectionService(db).list_inspections(
            skip=skip, limit=per_page, user_id=user_id, cargo_type=cargo_type,
            status=status_filter, tag=tag, search=search,
            include_deleted=include_deleted, sort=sort,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    items = [inspection_dump(i, base=f"{API_PREFIX}/admin/submissions")
             for i in result.items]
    total_pages = -(-result.total // per_page) if per_page else 0
    return envelope(
        items,
        meta=pagination_meta(
            page=page,
            per_page=per_page,
            total=result.total,
            total_pages=total_pages,
        ),
        links=list_links(
            base_path=f"{API_PREFIX}/admin/submissions",
            page=page,
            per_page=per_page,
            total_pages=total_pages,
            query={"status": status_filter, "cargo_type": cargo_type,
                   "tag": tag, "search": search, "sort": sort,
                   "include_deleted": include_deleted},
        ),
    )


@router.post(
    "/submissions",
    status_code=status.HTTP_201_CREATED,
    summary="Create a submission on behalf of any user (admin only)",
)
async def create_submission_admin(
    name: str = Form(...),
    email: str = Form(...),
    cargo_type: str = Form(...),
    phone: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    status: str = Form("submitted"),
    tags: str = Form(""),
    image: UploadFile = File(...),
    idempotency_key: Annotated[
        Optional[str], Header(alias="Idempotency-Key")
    ] = None,
    admin: User = Depends(require_permission(P_SUBMISSIONS_READ_ANY)),
    db: Session = Depends(get_db),
    response: Response = None,  # type: ignore[assignment]
):
    """Create an inspection on behalf of any user.

    Unlike the portal upload (which derives user from the session), the admin
    supplies the owner's name/email explicitly. The user is created if needed.
    """
    idem = IdempotencyService(db)
    if idempotency_key:
        replay = idem.lookup(idempotency_key, "POST /admin/submissions/")
        if replay is not None:
            stored = replay.response
            # §5: a replay returns the cached response plus this header, so
            # the client can tell a replay from a fresh create.
            return JSONResponse(
                status_code=replay.status_code,
                content=envelope(
                    stored,
                    links={
                        "self": f"{API_PREFIX}/admin/submissions/{stored['id']}"
                    },
                ),
                headers={"Idempotent-Replay": "true"},
            )

    if status not in INSPECTION_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown status '{status}'. Expected one of: {', '.join(INSPECTION_STATUSES)}",
        )

    try:
        payload = InspectionCreate(
            name=name.strip(),
            email=email.strip(),
            phone=(phone or "").strip() or None,
            cargo_type=cargo_type.strip(),
            notes=(notes or "").strip() or None,
            status=status,
            tags=[t for t in tags.split(",") if t.strip()],
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=jsonable_errors(exc))

    content = await image.read()
    try:
        insp = InspectionService(db).create_inspection(
            payload,
            original_name=image.filename or "",
            content_type=image.content_type or "",
            content=content,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    body = inspection_dump(insp, base=f"{API_PREFIX}/admin/submissions")
    if idempotency_key:
        idem.store(idempotency_key, "POST /admin/submissions/", 201, body)
    response.headers["Location"] = f"{API_PREFIX}/admin/submissions/{insp.id}"
    return envelope(
        body, links={"self": f"{API_PREFIX}/admin/submissions/{insp.id}"}
    )


@router.get(
    "/submissions/pending",
    summary="The review queue",
)
def pending_submissions(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    admin: User = Depends(require_permission(P_SUBMISSIONS_READ_ANY)),
    db: Session = Depends(get_db),
):
    """Submitted, not yet decided, oldest first — the work queue."""
    skip = (page - 1) * per_page
    result = InspectionService(db).list_inspections(
        skip=skip, limit=per_page, status="submitted", sort="created_at"
    )
    items = [inspection_dump(i, base=f"{API_PREFIX}/admin/submissions")
             for i in result.items]
    total_pages = -(-result.total // per_page) if per_page else 0
    return envelope(
        items,
        meta=pagination_meta(
            page=page,
            per_page=per_page,
            total=result.total,
            total_pages=total_pages,
        ),
        links=list_links(
            base_path=f"{API_PREFIX}/admin/submissions/pending",
            page=page,
            per_page=per_page,
            total_pages=total_pages,
        ),
    )


# NOTE: every literal `/submissions/<word>` route (pending, summary,
# orphaned-users) must be registered BEFORE `/{inspection_id}` below. FastAPI
# matches in registration order, so otherwise "summary" is parsed as an
# inspection id and returns 422.
@router.get(
    "/submissions/summary",
    summary="Per-user aggregates",
)
def summary_admin(
    admin: User = Depends(require_permission(P_SUBMISSIONS_READ_ANY)),
    db: Session = Depends(get_db),
):
    return envelope(InspectionService(db).summary_by_user())


@router.get(
    "/submissions/orphaned-users",
    summary="Users with no inspections (correlated NOT EXISTS)",
)
def orphaned_users_admin(
    admin: User = Depends(require_permission(P_SUBMISSIONS_READ_ANY)),
    db: Session = Depends(get_db),
):
    """Users who exist but have never submitted — the onboarding-funnel query."""
    users = InspectionService(db).users_without_inspections()
    return envelope(
        [{"id": u.id, "name": u.name, "email": u.email} for u in users]
    )


@router.get("/submissions/{inspection_id}")
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
    return envelope(
        inspection_dump(insp, base=f"{API_PREFIX}/admin/submissions"),
        links={"self": f"{API_PREFIX}/admin/submissions/{insp.id}"},
    )


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
    insp.reviewed_at = utcnow()
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
    return envelope(
        inspection_dump(insp, base=f"{API_PREFIX}/admin/submissions"),
        links={"self": f"{API_PREFIX}/admin/submissions/{insp.id}"},
    )


@router.post(
    "/submissions/{inspection_id}/approve",
    summary="Approve a submission",
)
def approve_submission(
    inspection_id: int,
    data: Optional[DecisionRequest] = None,
    admin: User = Depends(require_permission(P_SUBMISSIONS_READ_ANY)),
    db: Session = Depends(get_db),
):
    """`POST` because approving is a non-idempotent state transition (§5).

    The optional note comes from the JSON body, not `?note=` — a mutation's
    payload belongs in the body, and this is what the admin UI already sends.
    """
    return _decide(
        inspection_id, "approved", data.note if data else None, admin, db
    )


@router.post(
    "/submissions/{inspection_id}/reject",
    summary="Reject a submission",
)
def reject_submission(
    inspection_id: int,
    data: Optional[DecisionRequest] = None,
    admin: User = Depends(require_permission(P_SUBMISSIONS_READ_ANY)),
    db: Session = Depends(get_db),
):
    """Same contract as approve: body carries the optional note."""
    return _decide(
        inspection_id, "rejected", data.note if data else None, admin, db
    )


@router.post("/submissions/bulk", summary="Approve or reject many at once")
def bulk_decide(
    payload: BulkDecisionRequest,
    admin: User = Depends(require_permission(P_SUBMISSIONS_READ_ANY)),
    db: Session = Depends(get_db),
):
    """Body: `{"ids": [1, 2], "action": "approve", "note": "..."}`.

    Each id is processed independently: one bad row does not abort the batch, and
    the response reports what happened to each.
    """
    ids = payload.ids
    action = payload.action
    note = payload.note

    target = "approved" if action == "approve" else "rejected"
    results = []
    for raw_id in ids:  # capped at 200 ids by the schema
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
    return envelope({"processed": len(results), "results": results})


@router.patch(
    "/submissions/{inspection_id}",
    summary="Partial update (admin only)",
)
def patch_submission(
    inspection_id: int,
    data: InspectionUpdate,
    admin: User = Depends(require_permission(P_SUBMISSIONS_READ_ANY)),
    db: Session = Depends(get_db),
):
    """Admin partial update: change status, notes, tags, cargo_type, etc.

    The portal restricts users to `SELF_ASSIGNABLE_STATUSES`; admins can set any
    valid status. Use the approve/reject endpoints for the review workflow
    (they also record `reviewed_by`/`reviewed_at` and write an audit entry).
    """
    try:
        insp = InspectionService(db).update_inspection(inspection_id, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not insp:
        raise HTTPException(status_code=404, detail="Submission not found")
    return envelope(
        inspection_dump(insp, base=f"{API_PREFIX}/admin/submissions"),
        links={"self": f"{API_PREFIX}/admin/submissions/{insp.id}"},
    )


@router.get(
    "/submissions/{inspection_id}/detection",
    summary="Read any submission's detection result",
)
def admin_submission_detection(
    inspection_id: int,
    include_deleted: bool = Query(True),
    admin: User = Depends(require_permission(P_SUBMISSIONS_READ_ANY)),
    db: Session = Depends(get_db),
):
    """Admin counterpart of `/portal/submissions/{id}/detection`.

    Read-only on purpose: an admin reviewing a queue should not be able to burn
    30 s of CPU on someone's submission, and a detection result is not part of
    the approve/reject decision. Admins re-run detection as the owner would.

    Returns `status: "not_run"` rather than 404 when nothing has been detected
    yet — the submission exists, it simply has no result, and conflating those
    would be misleading.
    """
    from app.api.v1.endpoints.detection import _to_envelope
    insp = (
        db.get(Inspection, inspection_id)
        if include_deleted
        else InspectionService(db).get_inspection(inspection_id)
    )
    if not insp:
        raise HTTPException(status_code=404, detail="Submission not found")
    # The overlay has its own admin route, so the link is stamped with the
    # admin prefix rather than the owner-scoped portal one.
    return _to_envelope(insp, overlay_base=f"{API_PREFIX}/admin/submissions")


@router.get(
    "/submissions/{inspection_id}/detection/overlay",
    summary="Serve any submission's detection overlay",
)
def admin_submission_detection_overlay(
    inspection_id: int,
    include_deleted: bool = Query(True),
    admin: User = Depends(require_permission(P_SUBMISSIONS_READ_ANY)),
    db: Session = Depends(get_db),
):
    """Admin counterpart of the portal's overlay route."""
    insp = (
        db.get(Inspection, inspection_id)
        if include_deleted
        else InspectionService(db).get_inspection(inspection_id)
    )
    if not insp:
        raise HTTPException(status_code=404, detail="Submission not found")
    if not insp.detection_overlay:
        raise HTTPException(
            status_code=404,
            detail="No overlay for this submission — nothing was detected.",
        )
    try:
        path = overlay_path_for(insp.detection_overlay)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Overlay not found") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Overlay file is missing")
    return FileResponse(path, media_type="image/png")


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


@router.post("/submissions/{inspection_id}/restore")
def restore_submission(
    inspection_id: int,
    admin: User = Depends(require_permission(P_SUBMISSIONS_READ_ANY)),
    db: Session = Depends(get_db),
):
    insp = InspectionService(db).restore(inspection_id)
    if not insp:
        raise HTTPException(status_code=404, detail="Not found or not deleted")
    return envelope(
        inspection_dump(insp, base=f"{API_PREFIX}/admin/submissions"),
        links={"self": f"{API_PREFIX}/admin/submissions/{insp.id}"},
    )


@router.delete(
    "/submissions/{inspection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Withdraw (soft-delete) any submission",
)
def withdraw_submission_admin(
    inspection_id: int,
    admin: User = Depends(require_permission(P_SUBMISSIONS_READ_ANY)),
    db: Session = Depends(get_db),
):
    """Hide the row without destroying it. Restorable, still listed with
    `include_deleted=true`, still counted out of aggregates — the same
    withdraw semantics as the portal, applied cross-user.

    DELETE is idempotent (§5): withdrawing an already-withdrawn submission
    is still 204. Only a submission that never existed 404s."""
    insp = db.get(Inspection, inspection_id)
    if insp is None:
        raise HTTPException(status_code=404, detail="Submission not found")
    if insp.deleted_at is None:
        InspectionService(db).soft_delete(inspection_id)


@router.delete(
    "/submissions/{inspection_id}/purge",
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
    return envelope({
        "stats": svc.stats(),
        "by_status": by_status,
        "by_cargo": by_cargo,
        "users": db.execute(select(func.count(User.id))).scalar_one(),
        "admins": db.execute(
            select(func.count(User.id)).where(User.role == Role.ADMIN.value)
        ).scalar_one(),
    })


# --------------------------------------------------------------------- #
# audit
# --------------------------------------------------------------------- #
@router.get("/audit", summary="Recent audit entries")
def read_audit(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
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
    skip = (page - 1) * per_page
    rows = db.execute(q.offset(skip).limit(per_page)).scalars().all()

    items = [
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
    ]
    total_pages = -(-total // per_page) if per_page else 0
    return envelope(
        items,
        meta=pagination_meta(
            page=page,
            per_page=per_page,
            total=total,
            total_pages=total_pages,
        ),
        links=list_links(
            base_path=f"{API_PREFIX}/admin/audit",
            page=page,
            per_page=per_page,
            total_pages=total_pages,
            query={"entity_type": entity_type, "action": action},
        ),
    )


# --------------------------------------------------------------------- #
# cargo-types
# --------------------------------------------------------------------- #
@router.get(
    "/cargo-types",
    summary="Cargo lookup table (admin)",
)
def list_cargo_types_admin(
    admin: User = Depends(require_permission(P_SUBMISSIONS_READ_ANY)),
    db: Session = Depends(get_db),
):
    """Admin counterpart of `/portal/cargo-types`."""
    return envelope(
        [CargoTypeOut.model_validate(c).model_dump(mode="json")
         for c in InspectionService(db).list_cargo_types()]
    )


# users
# --------------------------------------------------------------------- #
@router.get("/users", summary="All users")
def list_users_admin(
    page: int = Query(1, ge=1),
    per_page: int = Query(100, ge=1, le=100),
    admin: User = Depends(require_permission(P_USERS_MANAGE)),
    db: Session = Depends(get_db),
):
    skip = (page - 1) * per_page
    users = list(db.execute(select(User).order_by(User.id).offset(skip).limit(per_page)).scalars())
    total = db.execute(select(func.count(User.id))).scalar_one()
    total_pages = -(-total // per_page) if per_page else 0
    return envelope(
        [UserResponse.model_validate(u).model_dump(mode="json") for u in users],
        meta=pagination_meta(
            page=page,
            per_page=per_page,
            total=total,
            total_pages=total_pages,
        ),
        links=list_links(
            base_path=f"{API_PREFIX}/admin/users",
            page=page,
            per_page=per_page,
            total_pages=total_pages,
        ),
    )


@router.get(
    "/users/{user_id}",
    summary="Read one user (admin only)",
)
def get_user_admin(
    user_id: int,
    admin: User = Depends(require_permission(P_USERS_MANAGE)),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    svc = UserService(db)
    return envelope(
        UserDetailResponse(
            **UserResponse.model_validate(user).model_dump(),
            inspection_count=svc.get_inspection_count(user_id),
        ).model_dump(mode="json"),
        links={"self": f"{API_PREFIX}/admin/users/{user.id}"},
    )


@router.patch(
    "/users/{user_id}",
    summary="Change a user's role (admin only)",
)
def update_user_role(
    user_id: int,
    data: UserRoleUpdate,
    admin: User = Depends(require_permission(P_USERS_MANAGE)),
    db: Session = Depends(get_db),
):
    """Change one user's role.

    `PATCH` on the user rather than `POST /users/{id}/role`: this changes part
    of an existing resource, and §5 rejects POST-for-update. The permission
    (`users:manage`), the self-demotion guard and the `set_role` audit action
    are unchanged — only the method and where `role` is carried.
    """
    if user_id == admin.id and data.role == "user":
        # Guard against an admin demoting themselves and locking everyone out.
        raise HTTPException(
            status_code=400,
            detail="You cannot remove your own administrator role.",
        )
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.role = data.role
    AuditService(db).record(
        action="set_role", entity_type="user", entity_id=user.id,
        actor_user_id=admin.id, detail={"role": data.role},
    )
    db.commit()
    db.refresh(user)
    return envelope(
        UserResponse.model_validate(user).model_dump(mode="json"),
        links={"self": f"{API_PREFIX}/admin/users/{user.id}"},
    )