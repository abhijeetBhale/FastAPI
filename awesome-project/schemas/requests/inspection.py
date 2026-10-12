from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class InspectionCreate(BaseModel):
    """Fields the user fills in before choosing an image."""

    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    cargo_type: str = Field(min_length=1, max_length=50)
    notes: Optional[str] = Field(default=None, max_length=500)