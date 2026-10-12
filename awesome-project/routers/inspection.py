from datetime import datetime
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from database import get_db
from models.inspection import INSPECTION_STATUSES
from models.user import User
from schemas.errors import jsonable_errors
from schemas.requests.inspection import InspectionCreate, InspectionUpdate
from schemas.responses.inspection import (
    CargoTypeOut,
    InspectionListResponse,
    InspectionResponse,
    InspectionSummary,
    TagOut,
)
from services.idempotency_service import IdempotencyService
from services.inspection_service import InspectionService, resolve_image_path
from services.rbac import (
    P_SUBMISSIONS_READ_ANY,
    SELF_ASSIGNABLE_STATUSES,
    require_permission,
)
from services.security import require_current_user

router = APIRouter(
    prefix="/inspections",
    tags=["Inspections"],
    dependencies=[Depends(require_permission(P_SUBMISSIONS_READ_ANY))],
)
"""Cross-user inspection routes.

Every route on this router requires `submissions:read:any`, i.e. the admin role.
Before RBAC these were reachable with no authentication at all, which meant
anyone could approve a submission or read every user's email address. Applying
the dependency at the router level means a new endpoint added here is protected
by default instead of by remembering to add a check.
"""


def _page(rows, total, skip, limit) -> InspectionListResponse:
    return InspectionListResponse(
        items=rows,
        total=total,
        skip=skip,
        limit=limit,
        pages=-(-total // limit) if limit else 0,
    )


@router.post(
    "/",
    response_model=InspectionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an inspection (idempotent with Idempotency-Key)",
)
async def create_inspection_endpoint(
    name: str = Form(...),
    email: str = Form(...),
    cargo_type: str = Form(...),
    phone: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    status: str = Form("submitted"),
    tags: str = Form(""),
    image: UploadFile = File(...),
    idempotency_key: Annotated[Optional[str], Header(alias="Idempotency-Key")] = None,
    db: Session = Depends(get_db),
):
    """Creates an inspection, creating the user on demand.

    Send `Idempotency-Key` and a retried request returns the original response
    instead of creating a duplicate.
    """
    idem = IdempotencyService(db)
    if idempotency_key:
        replay = idem.lookup(idempotency_key, "POST /inspections/")
        if replay is not None:
            return JSONResponse(
                status_code=replay.status_code, content=replay.response
            )

    if status not in INSPECTION_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown status '{status}'. "
            f"Expected one of: {', '.join(INSPECTION_STATUSES)}",
        )

    try:
        payload = InspectionCreate(
            name=name.strip(),
            email=email.strip(),
            cargo_type=cargo_type.strip(),
            phone=(phone or "").strip() or None,
            notes=(notes or "").strip() or None,
            status=status,
            tags=[t for t in tags.split(",") if t.strip()],
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=jsonable_errors(exc))

    # Read once, then hand the bytes to the service. UploadFile spools to disk
    # above a threshold, so this does not hold a 10 MB upload in RAM twice —
    # but the service needs the header bytes for dimensions, so it takes the
    # full content.
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

    body = InspectionResponse.model_validate(insp).model_dump(mode="json")
    if idempotency_key:
        idem.store(idempotency_key, "POST /inspections/", 201, body)
    return body


@router.get(
    "/",
    response_model=InspectionListResponse,
    summary="List inspections with filtering, sorting and pagination",
)
def list_inspections(
    skip: int = Query(0, ge=0, description="Rows to skip"),
    limit: int = Query(20, ge=1, le=100, description="Max rows per page"),
    user_id: Optional[int] = Query(None, ge=1),
    cargo_type: Optional[str] = Query(None, description="Slug, e.g. scrap-steel"),
    status_filter: Optional[str] = Query(None, alias="status"),
    tag: Optional[str] = Query(None),
    search: Optional[str] = Query(None, description="Notes, filename, name or email"),
    created_from: Optional[datetime] = Query(None),
    created_to: Optional[datetime] = Query(None),
    include_deleted: bool = Query(False),
    sort: str = Query("-created_at", description="created_at|updated_at|status|id, prefix - for descending"),
    db: Session = Depends(get_db),
):
    try:
        page = InspectionService(db).list_inspections(
            skip=skip,
            limit=limit,
            user_id=user_id,
            cargo_type=cargo_type,
            status=status_filter,
            tag=tag,
            search=search,
            created_from=created_from,
            created_to=created_to,
            include_deleted=include_deleted,
            sort=sort,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return _page(
        [InspectionResponse.model_validate(i) for i in page.items],
        page.total,
        page.skip,
        page.limit,
    )


@router.get("/stats", summary="Headline counts and total weight")
def inspection_stats(db: Session = Depends(get_db)):
    return InspectionService(db).stats()


@router.get("/summary", response_model=list[InspectionSummary], summary="Per-user aggregates")
def inspection_summary(db: Session = Depends(get_db)):
    return InspectionService(db).summary_by_user()


@router.get("/cargo-types", response_model=list[CargoTypeOut], summary="Cargo lookup table")
def list_cargo_types(db: Session = Depends(get_db)):
    return InspectionService(db).list_cargo_types()


@router.get("/tags", response_model=list[TagOut], summary="All tags in use")
def list_tags(db: Session = Depends(get_db)):
    return InspectionService(db).list_tags()


@router.get(
    "/orphaned-users",
    summary="Users with no inspections (correlated NOT EXISTS)",
)
def users_without_inspections(db: Session = Depends(get_db)):
    users = InspectionService(db).users_without_inspections()
    return [
        {"id": u.id, "name": u.name, "email": u.email} for u in users
    ]


# --------------------------------------------------------------------- #
# Portal routes
#
# These require a signed-in user and are always scoped to that user. Note the
# difference from the admin routes above: `user_id` comes from the session,
# never from a query parameter, so one user cannot read another's submissions
# by editing the URL.
# --------------------------------------------------------------------- #
portal = APIRouter(prefix="/portal", tags=["Portal"])


@portal.get(
    "/cargo-types",
    response_model=list[CargoTypeOut],
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
    return InspectionService(db).list_cargo_types()


@portal.get(
    "/summary",
    summary="Counts the dashboard needs (scoped to the signed-in user)",
)
def portal_summary(
    user: User = Depends(require_current_user), db: Session = Depends(get_db)
):
    svc = InspectionService(db)
    mine = svc.list_inspections(skip=0, limit=1, user_id=user.id)
    return {
        "total": mine.total,
        "stats": svc.stats(user_id=user.id),
        "cargo_types": [
            {"slug": c.slug, "label": c.label, "density_kg_m3": c.density_kg_m3}
            for c in svc.list_cargo_types()
        ],
        "has_any": mine.total > 0,
    }


@portal.get(
    "/submissions",
    response_model=InspectionListResponse,
    summary="My submissions, paginated",
)
def portal_submissions(
    skip: int = Query(0, ge=0),
    limit: int = Query(6, ge=1, le=50, description="Cards per page"),
    cargo_type: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    tag: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    sort: str = Query("-created_at"),
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    try:
        page = InspectionService(db).list_inspections(
            skip=skip,
            limit=limit,
            user_id=user.id,        # forced, not user-supplied
            cargo_type=cargo_type,
            status=status_filter,
            tag=tag,
            search=search,
            sort=sort,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return _page(
        [InspectionResponse.model_validate(i) for i in page.items],
        page.total,
        page.skip,
        page.limit,
    )


@portal.post(
    "/submissions",
    response_model=InspectionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a submission (lands in My submissions)",
)
async def portal_submit(
    cargo_type: str = Form(...),
    notes: Optional[str] = Form(None),
    tags: str = Form(""),
    # Named `status` to match what the form actually sends. No path parameter
    # shadows it on this router, and an earlier mismatch here silently ignored
    # the field — every upload became 'submitted' regardless of the choice.
    status: str = Form("submitted"),
    image: UploadFile = File(...),
    idempotency_key: Annotated[
        Optional[str], Header(alias="Idempotency-Key")
    ] = None,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
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
            return JSONResponse(
                status_code=replay.status_code, content=replay.response
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

    body = InspectionResponse.model_validate(insp).model_dump(mode="json")
    if idempotency_key:
        idem.store(idempotency_key, "POST /portal/submissions", 201, body)
    return body


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


@portal.get("/submissions/{inspection_id}", response_model=InspectionResponse)
def portal_get_submission(
    inspection_id: int,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    """Ownership is checked explicitly — a 404 rather than a 403, so the
    response does not confirm that someone else's id exists."""
    insp = InspectionService(db).get_inspection(inspection_id)
    if not insp or insp.user_id != user.id:
        raise HTTPException(status_code=404, detail="Submission not found")
    return insp


@portal.delete(
    "/submissions/{inspection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Withdraw one of my submissions",
)
def portal_delete_submission(
    inspection_id: int,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    insp = InspectionService(db).get_inspection(inspection_id)
    if not insp or insp.user_id != user.id:
        raise HTTPException(status_code=404, detail="Submission not found")
    InspectionService(db).soft_delete(inspection_id)


@router.get("/{inspection_id}", response_model=InspectionResponse)
def read_inspection(inspection_id: int, db: Session = Depends(get_db)):
    insp = InspectionService(db).get_inspection(inspection_id)
    if not insp:
        raise HTTPException(status_code=404, detail="Inspection not found")
    return insp


@router.patch("/{inspection_id}", response_model=InspectionResponse, summary="Partial update")
def patch_inspection(
    inspection_id: int,
    data: InspectionUpdate,
    admin: User = Depends(require_permission(P_SUBMISSIONS_READ_ANY)),
    db: Session = Depends(get_db),
):
    try:
        insp = InspectionService(db).update_inspection(inspection_id, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not insp:
        raise HTTPException(status_code=404, detail="Inspection not found")
    return insp


@router.get("/{inspection_id}/image", summary="The stored image")
def read_inspection_image(inspection_id: int, db: Session = Depends(get_db)):
    insp = InspectionService(db).get_inspection(inspection_id)
    if not insp:
        raise HTTPException(status_code=404, detail="Inspection not found")
    path = resolve_image_path(insp)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Image file is missing")
    return FileResponse(
        path,
        media_type=insp.image_content_type,
        filename=insp.image_original_name,
    )


@router.delete(
    "/{inspection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft delete (reversible)",
)
def delete_inspection_endpoint(inspection_id: int, db: Session = Depends(get_db)):
    if not InspectionService(db).soft_delete(inspection_id):
        raise HTTPException(status_code=404, detail="Inspection not found")


@router.post(
    "/{inspection_id}/restore",
    response_model=InspectionResponse,
    summary="Undo a soft delete",
)
def restore_inspection_endpoint(inspection_id: int, db: Session = Depends(get_db)):
    insp = InspectionService(db).restore(inspection_id)
    if not insp:
        raise HTTPException(status_code=404, detail="Inspection not found or not deleted")
    return insp


@router.delete(
    "/{inspection_id}/purge",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Hard delete (irreversible)",
)
def purge_inspection_endpoint(inspection_id: int, db: Session = Depends(get_db)):
    if not InspectionService(db).hard_delete(inspection_id):
        raise HTTPException(status_code=404, detail="Inspection not found")


@router.get("/{inspection_id}/linked", summary="What this inspection links to")
def read_inspection_links(inspection_id: int, db: Session = Depends(get_db)):
    insp = InspectionService(db).get_inspection(inspection_id)
    if not insp:
        raise HTTPException(status_code=404, detail="Inspection not found")
    return {
        "inspection_id": insp.id,
        "status": insp.status,
        "cargo_type": insp.cargo_type,
        "image_url": insp.image_url,
        "user": {
            "id": insp.user.id,
            "name": insp.user.name,
            "email": insp.user.email,
            "phone": insp.user.phone,
            "is_active": insp.user.is_active,
        },
        "tags": [t.name for t in insp.tags],
    }