"""Router registration for version 1.

Every resource router is included here, exactly once, and `main.py` mounts the
result. Keeping the list in one place is what makes the version prefix
impossible to half-apply: `API_PREFIX` is set on the router below rather than
repeated in six `APIRouter(prefix=...)` calls, so a future v2 is a sibling
package plus one more `include_router`.

Two deliberate asymmetries:

* The auth router is mounted **without** `authed`. It is public at
  login/register and protected only on `/me` and `/change-password`, where the
  handler's own `Depends(get_current_user)` enforces it. Declaring the bearer
  scheme on it would tell OpenAPI that `/auth/login` needs a token that a
  first-time reader cannot obtain yet.
* The health routers are **not** part of `api_router` at all — `/health` and
  `/health/ready` stay outside the version prefix (D1), because probe
  configuration lives in load balancers and containers rather than in a
  versioned API contract. They are exported for `main.py` to mount last.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1 import API_PREFIX
from app.api.v1.endpoints.admin import router as admin_router
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.detection import router as detection_router
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.endpoints.inspection import portal as portal_router
from app.api.v1.endpoints.lifting_plan import router as lifting_plan_router
from app.core.security import bearer_scheme

__all__ = ["API_PREFIX", "api_router", "authed", "health_router"]

#: Attached to every authenticated router so OpenAPI marks those operations as
#: requiring `bearerAuth`. Swagger UI then renders the lock icon and enables its
#: Authorize dialog — otherwise /docs offers no way to sign in, because its
#: Authorize button can only hold apiKey/bearer/oauth2 and never a cookie.
#: `auto_error=False` means this changes the documentation, not the behaviour:
#: the real 401 still comes from `get_current_user`.
authed = [Depends(bearer_scheme)]

# The version is applied once, here — not in each endpoint module.
api_router = APIRouter(prefix=API_PREFIX)

api_router.include_router(auth_router)
# Portal: owner-scoped operations for signed-in users
api_router.include_router(portal_router, dependencies=authed)
# Detection: runs on the caller's own submissions
api_router.include_router(detection_router, dependencies=authed)
# Lifting plan: one Markdown document per submission, no persistence
api_router.include_router(lifting_plan_router, dependencies=authed)
# Admin: review workflow + user management (cross-user, requires admin role)
api_router.include_router(admin_router, dependencies=authed)
