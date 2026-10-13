from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class UserResponse(BaseModel):
    id: int
    name: str
    email: str
    phone: Optional[str] = None
    is_active: bool
    role: str = "user"
    created_at: datetime

    model_config = {"from_attributes": True}


class UserDetailResponse(UserResponse):
    """A user plus a count of their inspections.

    `inspection_count` comes from a single aggregate query, not by loading every
    inspection and counting in Python.
    """

    inspection_count: int = 0
