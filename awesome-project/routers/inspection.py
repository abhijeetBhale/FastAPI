from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import ValidationError

from database import get_db
from schemas.requests.inspection import InspectionCreate
from schemas.responses.inspection import InspectionResponse
from services.inspection_service import (
    InspectionService,
    resolve_image_path,
)

router = APIRouter(prefix="/inspections", tags=["Inspections"])


@router.post("/", response_model=InspectionResponse, status_code=201)
async def create_inspection_endpoint(
    name: str = Form(...),
    email: str = Form(...),
    cargo_type: str = Form(...),
    notes: Optional[str] = Form(None),
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Two-step create: the user's detail fields plus the uploaded image."""
    try:
        payload = InspectionCreate(
            name=name.strip(),
            email=email.strip(),
            cargo_type=cargo_type.strip(),
            notes=(notes or "").strip() or None,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors())

    content = await image.read()
    try:
        return InspectionService(db).create_inspection(
            payload,
            original_name=image.filename or "",
            content_type=image.content_type or "",
            content=content,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/", response_model=List[InspectionResponse])
def read_inspections(
    skip: int = 0, limit: int = 100, db: Session = Depends(get_db)
):
    return InspectionService(db).get_inspections(skip, limit)


@router.get("/{inspection_id}", response_model=InspectionResponse)
def read_inspection(inspection_id: int, db: Session = Depends(get_db)):
    insp = InspectionService(db).get_inspection(inspection_id)
    if not insp:
        raise HTTPException(status_code=404, detail="Inspection not found")
    return insp


@router.get("/{inspection_id}/image")
def read_inspection_image(
    inspection_id: int, db: Session = Depends(get_db)
):
    """Serve the stored image back — the visible 'output' of the upload."""
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


@router.delete("/{inspection_id}", status_code=204)
def delete_inspection_endpoint(
    inspection_id: int, db: Session = Depends(get_db)
):
    success = InspectionService(db).delete_inspection(inspection_id)
    if not success:
        raise HTTPException(status_code=404, detail="Inspection not found")