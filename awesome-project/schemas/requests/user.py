from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from schemas.validators import PhoneNumber


class UserCreate(BaseModel):
    # max_length matches the String(50) column. Without it, an over-long name
    # reaches PostgreSQL and surfaces as an unhandled 500.
    name: str = Field(min_length=1, max_length=50)
    email: EmailStr
    phone: Optional[PhoneNumber] = None

    @field_validator("email")
    @classmethod
    def _lower_email(cls, v: str) -> str:
        # Stored lowercase so the case-insensitive unique index has one
        # canonical form to compare against.
        return v.strip().lower()


class UserUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=50)
    email: Optional[EmailStr] = None
    phone: Optional[PhoneNumber] = None
    is_active: Optional[bool] = None


class UserRoleUpdate(BaseModel):
    """An admin changing someone else's role — `PATCH /admin/users/{id}`.

    Just `role`, and required: this is a partial update of an existing
    resource, so the method is `PATCH` on the user, not `POST` on a
    `/role` sub-path (see docs/API_CONVENTIONS.md §5, which rejects
    POST-for-update). The other `UserUpdate` fields are self-service edits
    with a different permission and a different audit action.

    A missing `role` is a 422 from this schema rather than a hand-rolled
    check in the handler.
    """

    role: Literal["user", "admin"]