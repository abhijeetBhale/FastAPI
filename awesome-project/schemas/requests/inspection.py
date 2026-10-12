from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from schemas.validators import PhoneNumber

InspectionStatus = Literal["draft", "submitted", "approved", "rejected"]


class InspectionCreate(BaseModel):
    """What the UI sends.

    `name` + `email` identify the user and are matched against `users`
    case-insensitively; a new user is created when no match exists.
    `phone` is optional and only used when creating that user — an existing
    user's stored phone is never overwritten.

    `cargo_type` is a *slug* from the cargo_types lookup table, not free text.
    """

    name: str = Field(min_length=1, max_length=50)
    email: EmailStr
    phone: Optional[PhoneNumber] = None
    cargo_type: str = Field(min_length=1, max_length=50)
    status: InspectionStatus = "submitted"
    notes: Optional[str] = Field(default=None, max_length=500)
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("email")
    @classmethod
    def _lower_email(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, v: list[str]) -> list[str]:
        cleaned = [t.strip() for t in v if t and t.strip()]
        return list(dict.fromkeys(cleaned))  # de-duplicate, keep order


class InspectionUpdate(BaseModel):
    """Partial update. Only the fields actually sent are applied."""

    status: Optional[InspectionStatus] = None
    status_note: Optional[str] = Field(default=None, max_length=300)
    notes: Optional[str] = Field(default=None, max_length=500)
    cargo_type: Optional[str] = Field(default=None, min_length=1, max_length=50)
    volume_m3: Optional[float] = Field(default=None, ge=0)
    estimated_weight_kg: Optional[float] = Field(default=None, ge=0)
    tags: Optional[list[str]] = Field(default=None, max_length=20)