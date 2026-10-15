from typing import Any, Optional

from pydantic import BaseModel, Field

from app.schemas.responses.envelope import IsoDateTime

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

    # Populated only once an admin has decided.
    reviewed_by: Optional[int] = None
    reviewed_at: Optional[IsoDateTime] = None

    volume_m3: Optional[float] = None
    estimated_weight_kg: Optional[float] = None

    # ---- cargo detection --------------------------------------------------
    # `detection_status` is derived, never stored, so it cannot drift from
    # `detection_result`. The full report is omitted here — it can hold dozens
    # of boxes per image and would bloat every list response. Fetch it from
    # `GET /portal/submissions/{id}/detection`.
    detection_status: str = "not_run"
    detected_at: Optional[IsoDateTime] = None
    cargo_object_count: int = 0

    # ---- AI decision (OpenAI Decisions API, evaluated during upload) ------
    # `decision_status` and `ai_*` are derived from `decision_result`, so
    # they cannot disagree with it. Unlike detection, the answers are small
    # (a handful of numbers per question) and ARE included here: the whole
    # point is seeing the recommendation next to the approve/reject buttons
    # without a second request.
    decision_status: str = "not_run"       # not_run | ok | error
    decided_at: Optional[IsoDateTime] = None
    ai_recommendation: Optional[str] = None  # approve | review
    ai_answers: Optional[dict[str, Any]] = None

    image_filename: str
    image_original_name: str
    image_content_type: str
    image_size_bytes: int
    image_width: Optional[int] = None
    image_height: Optional[int] = None
    image_url: str

    tags: list[TagOut] = Field(default_factory=list)

    created_at: IsoDateTime
    updated_at: Optional[IsoDateTime] = None

    model_config = {"from_attributes": True}


def inspection_dump(insp: InspectionResponse, *, base: str) -> dict:
    """Serialise one submission with an `image_url` scoped to the surface.

    Owners and admins fetch images through different routes
    (`/portal/submissions/{id}/image` vs `/admin/submissions/{id}/image`),
    so a single model property cannot be right for both — the router stamps
    its own base here instead.
    """
    body = InspectionResponse.model_validate(insp).model_dump(mode="json")
    body["image_url"] = f"{base}/{body['id']}/image"
    return body


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
    last_inspection_at: Optional[IsoDateTime] = None