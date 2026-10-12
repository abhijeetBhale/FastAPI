from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CurrentUserResponse(BaseModel):
    """The signed-in user, as the portal sees them."""

    id: int
    name: str
    email: str
    phone: Optional[str] = None
    role: str
    created_at: datetime

    # Conveniences the portal uses to decide what to render.
    inspection_count: int = 0
    has_password: bool = False

    model_config = {"from_attributes": True}


class MeResponse(BaseModel):
    """`/auth/me` plus the permission list.

    Sending the permissions lets the UI hide controls the caller cannot use,
    instead of rendering a button that returns 403 when pressed.
    """

    user: CurrentUserResponse
    permissions: list[str] = Field(default_factory=list)
    is_admin: bool = False


class LoginResponse(BaseModel):
    """Returned after a successful sign-in.

    The token itself is set as an httpOnly cookie and is deliberately NOT in
    this body, so it cannot be read by page JavaScript.
    """

    message: str = "Signed in"
    user: CurrentUserResponse
    expires_in_hours: int


class MessageResponse(BaseModel):
    detail: str


class PasswordProblemResponse(BaseModel):
    """422 body for a rejected password."""

    detail: str
    problems: list[str] = Field(default_factory=list)