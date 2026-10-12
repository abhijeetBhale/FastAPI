from datetime import datetime
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from database import get_db
from models.inspection import INSPECTION_STATUSES
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

router = APIRouter(prefix="/inspections", tags=["Inspections"])


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

    # Read once, then hand the bytes to the service. UploadFile already
    # spools to disk above a threshold, so this does not hold the whole file
    # in RAM for a 10 MB upload... but the service needs the header bytes for
    # dimensions, so it takes the full content.
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


@router.get("/{inspection_id}", response_model=InspectionResponse)
def read_inspection(inspection_id: int, db: Session = Depends(get_db)):
    insp = InspectionService(db).get_inspection(inspection_id)
    if not insp:
        raise HTTPException(status_code=404, detail="Inspection not found")
    return insp


@router.patch("/{inspection_id}", response_model=InspectionResponse, summary="Partial update")
def patch_inspection(
    inspection_id: int, data: InspectionUpdate, db: Session = Depends(get_db)
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