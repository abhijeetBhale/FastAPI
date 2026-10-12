from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class TagOut(BaseModel):
    id: int
    name: str
    colour: Optional[str] = None

    model_config = {"from_attributes": True}


class CargoTypeOut(BaseModel):
    id: int
    slug: str
    label: str
    density_kg_m3: Optional[float] = None
    description: Optional[str] = None

    model_config = {"from_attributes": True}


class InspectionResponse(BaseModel):
    """One inspection.

    `name` / `email` / `phone` come from the linked user; `cargo_type` and
    `cargo_label` from the lookup table. Neither is stored twice.
    """

    id: int

    user_id: int
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None

    cargo_type: str
    cargo_label: Optional[str] = None
    density_kg_m3: Optional[float] = None

    status: str
    status_note: Optional[str] = None
    notes: Optional[str] = None

    volume_m3: Optional[float] = None
    estimated_weight_kg: Optional[float] = None

    image_filename: str
    image_original_name: str
    image_content_type: str
    image_size_bytes: int
    image_width: Optional[int] = None
    image_height: Optional[int] = None
    image_url: str

    tags: list[TagOut] = Field(default_factory=list)

    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class InspectionListResponse(BaseModel):
    """Paginated envelope — the total is needed to render page controls."""

    items: list[InspectionResponse]
    total: int
    skip: int
    limit: int
    pages: int

    model_config = {"from_attributes": True}


class InspectionSummary(BaseModel):
    """Aggregate row for the per-user dashboard."""

    user_id: int
    name: Optional[str] = None
    email: Optional[str] = None
    inspection_count: int
    approved_count: int
    rejected_count: int
    total_weight_kg: float
    average_weight_kg: Optional[float] = None
    last_inspection_at: Optional[datetime] = None