"""Portal inspection routes — owner-scoped only.

Every route on this router requires a signed-in user and operates strictly on
that user's own submissions. A user cannot access another's submissions by
editing the URL — ownership is enforced by deriving `user_id` from the session.
"""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.v1 import API_PREFIX
from app.core.security import require_current_user
from app.database.database import get_db
from app.models.inspection import Inspection
from app.models.user import User
from app.schemas.errors import jsonable_errors
from app.schemas.requests.inspection import InspectionCreate
from app.schemas.responses.envelope import envelope, list_links, pagination_meta
from app.schemas.responses.inspection import (
    CargoTypeOut,
    inspection_dump,
)
from app.services.idempotency_service import IdempotencyService
from app.services.inspection_service import InspectionService, resolve_image_path
from app.services.rbac import SELF_ASSIGNABLE_STATUSES

# --------------------------------------------------------------------- #
# Portal routes
#
# These require a signed-in user and are always scoped to that user. Note the
# difference from the admin routes: `user_id` comes from the session,
# never from a query parameter, so one user cannot read another's submissions
# by editing the URL.
# --------------------------------------------------------------------- #
portal = APIRouter(prefix="/portal", tags=["Portal"])


@portal.get(
    "/cargo-types",
    summary="Cargo lookup table (reference data, needed by the upload form)",
)
def portal_cargo_types(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    """Exposed on the portal as well as for admins.

    Cargo slugs and densities are reference data, not sensitive, and the upload
    form cannot render its dropdown without them — so a signed-in user needs
    this even though they hold no admin permission.
    """
    return envelope(
        [CargoTypeOut.model_validate(c).model_dump(mode="json")
         for c in InspectionService(db).list_cargo_types()]
    )


@portal.get(
    "/summary",
    summary="Counts the dashboard needs (scoped to the signed-in user)",
)
def portal_summary(
    user: User = Depends(require_current_user), db: Session = Depends(get_db)
):
    svc = InspectionService(db)
    mine = svc.list_inspections(skip=0, limit=1, user_id=user.id)
    return envelope({
        "total": mine.total,
        "stats": svc.stats(user_id=user.id),
        "cargo_types": [
            {"slug": c.slug, "label": c.label, "density_kg_m3": c.density_kg_m3}
            for c in svc.list_cargo_types()
        ],
        "has_any": mine.total > 0,
    })


@portal.get(
    "/submissions",
    summary="My submissions, paginated",
)
def portal_submissions(
    page: int = Query(1, ge=1),
    per_page: int = Query(6, ge=1, le=100, description="Cards per page"),
    cargo_type: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    tag: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    sort: str = Query("-created_at"),
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    skip = (page - 1) * per_page
    limit = per_page
    result = InspectionService(db).list_inspections(
        skip=skip,
        limit=limit,
        user_id=user.id,
        cargo_type=cargo_type,
        status=status_filter,
        tag=tag,
        search=search,
        sort=sort,
    )
    items = [inspection_dump(i, base=f"{API_PREFIX}/portal/submissions")
             for i in result.items]
    total_pages = -(-result.total // limit) if limit else 0
    return envelope(
        items,
        meta=pagination_meta(
            page=page,
            per_page=limit,
            total=result.total,
            total_pages=total_pages,
        ),
        links=list_links(
            base_path=f"{API_PREFIX}/portal/submissions",
            page=page,
            per_page=limit,
            total_pages=total_pages,
            query={"status": status_filter, "cargo_type": cargo_type,
                   "tag": tag, "search": search, "sort": sort},
        ),
    )


@portal.post(
    "/submissions",
    status_code=status.HTTP_201_CREATED,
    summary="Upload a new submission",
)
async def portal_create_submission(
    cargo_type: str = Form(...),
    status: str = Form("submitted"),
    notes: str = Form(""),
    tags: str = Form(""),
    image: UploadFile = File(...),
    idempotency_key: Annotated[
        Optional[str], Header(alias="Idempotency-Key")
    ] = None,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
    response: Response = None,  # type: ignore[assignment]
):
    """Upload without re-typing details.

    Name, email and phone come from the signed-in account, so the portal form
    cannot create a duplicate user or attribute a load to someone else.

    `status` is restricted to the self-assignable set: a user choosing
    'approved' on their own submission would be approving their own work.
    """
    idem = IdempotencyService(db)
    if idempotency_key:
        replay = idem.lookup(idempotency_key, "POST /portal/submissions")
        if replay is not None:
            stored = replay.response
            # §5: a replay returns the cached response plus this header, so
            # the client can tell a replay from a fresh create.
            return JSONResponse(
                status_code=replay.status_code,
                content=envelope(
                    stored,
                    links={"self": f"{API_PREFIX}/portal/submissions/{stored['id']}"},
                ),
                headers={"Idempotent-Replay": "true"},
            )

    if status not in SELF_ASSIGNABLE_STATUSES:
        raise HTTPException(
            status_code=403,
            detail=(
                f"You cannot set status '{status}'. "
                f"Choose one of: {', '.join(sorted(SELF_ASSIGNABLE_STATUSES))}. "
                "Approval is done by an administrator."
            ),
        )

    try:
        payload = InspectionCreate(
            name=user.name,
            email=user.email,
            phone=user.phone,
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

    body = inspection_dump(insp, base=f"{API_PREFIX}/portal/submissions")
    if idempotency_key:
        idem.store(idempotency_key, "POST /portal/submissions", 201, body)
    response.headers["Location"] = f"{API_PREFIX}/portal/submissions/{insp.id}"
    return envelope(
        body, links={"self": f"{API_PREFIX}/portal/submissions/{insp.id}"}
    )


@portal.get(
    "/submissions/{inspection_id}",
    summary="One of the caller's submissions",
)
def portal_submission_detail(
    inspection_id: int,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    insp = InspectionService(db).get_inspection(inspection_id)
    if not insp or insp.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found"
        )
    return envelope(
        inspection_dump(insp, base=f"{API_PREFIX}/portal/submissions"),
        links={"self": f"{API_PREFIX}/portal/submissions/{insp.id}"},
    )


@portal.delete(
    "/submissions/{inspection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Withdraw (soft-delete) the caller's submission",
)
def portal_withdraw_submission(
    inspection_id: int,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    # Ownership first — another user's id stays a 404, never a 403 (§7.2).
    # DELETE is idempotent (§5): withdrawing an already-withdrawn submission
    # is still 204. Only a submission that never existed 404s.
    insp = db.get(Inspection, inspection_id)
    if insp is None or insp.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found"
        )
    if insp.deleted_at is None:
        InspectionService(db).soft_delete(inspection_id)
    # 204 with an empty body — no envelope, no "null".
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@portal.get(
    "/submissions/{inspection_id}/image",
    summary="Serve an image the caller owns",
)
def portal_submission_image(
    inspection_id: int,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    """Image bytes for the caller's own submission.

    The cross-user `/inspections/{id}/image` route requires the admin
    permission, so the portal needs its own copy — otherwise a signed-in user
    cannot see the thumbnails of their own list.
    """
    insp = InspectionService(db).get_inspection(inspection_id)
    if not insp or insp.user_id != user.id:
        raise HTTPException(status_code=404, detail="Submission not found")
    path = resolve_image_path(insp)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Image file is missing")
    return FileResponse(
        path,
        media_type=insp.image_content_type,
        filename=insp.image_original_name,
    )