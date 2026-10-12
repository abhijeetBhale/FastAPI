from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class InspectionResponse(BaseModel):
    """The stored record returned after the image is uploaded."""

    id: int
    name: str
    email: str
    cargo_type: str
    notes: Optional[str] = None

    image_filename: str
    image_original_name: str
    image_content_type: str
    image_size_bytes: int
    image_width: Optional[int] = None
    image_height: Optional[int] = None
    image_url: str

    created_at: datetime

    model_config = {"from_attributes": True}