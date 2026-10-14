from typing import Optional

from pydantic import BaseModel

from schemas.responses.envelope import IsoDateTime


class UserResponse(BaseModel):
    id: int
    name: str
    email: str
    phone: Optional[str] = None
    is_active: bool
    role: str = "user"
    created_at: IsoDateTime

    model_config = {"from_attributes": True}


class UserDetailResponse(UserResponse):
    """A user plus a count of their inspections.

    `inspection_count` comes from a single aggregate query, not by loading every
    inspection and counting in Python.
    """

    inspection_count: int = 0
