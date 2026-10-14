from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    """Create a portal account."""

    name: str = Field(min_length=1, max_length=50)
    email: EmailStr
    phone: Optional[str] = None
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def _lower_email(cls, v: str) -> str:
        return v.strip().lower()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def _lower_email(cls, v: str) -> str:
        return v.strip().lower()


class SetPasswordRequest(BaseModel):
    """First-time password setup for an account that has none."""

    password: str = Field(min_length=8, max_length=128)


class ChangePasswordRequest(BaseModel):
    """Rotate an existing password."""

    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)