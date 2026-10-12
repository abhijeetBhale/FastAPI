"""Role gate for administrator-only prefixes.

A thin layer over `AuthenticationMiddleware`: if the path belongs to an
admin-only prefix, the caller's role is checked before the request is routed.

The role is read from the database here rather than trusted from the token, so a
demotion takes effect on the next request instead of waiting for the token to
expire. The token carries no role claim for exactly that reason.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from models.user import User
from services.rbac import Role, _coerce_role

logger = logging.getLogger("app.rbac")

#: Prefixes restricted to the admin role.
ADMIN_PREFIXES: tuple[str, ...] = ("/admin",)


def is_admin_path(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in ADMIN_PREFIXES)


class RoleAuthorizationMiddleware(BaseHTTPMiddleware):
    """Rejects non-admins from admin paths, before routing.

    The session factory is read from `app.state.session_factory` at request
    time rather than captured at construction. That keeps one place owning the
    factory, and lets tests point it at their rolled-back transaction — a
    middleware holding its own connection would not see the test's uncommitted
    rows.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path

        if not is_admin_path(path):
            return await call_next(request)

        # AuthenticationMiddleware already ran (it is outer) and attached the id.
        user_id = getattr(request.state, "user_id", None)
        if user_id is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "Sign in to continue.",
                         "code": "authentication_required"},
            )

        factory = getattr(request.app.state, "session_factory", None)
        if factory is None:  # pragma: no cover - misconfiguration
            return JSONResponse(
                status_code=500,
                content={"detail": "Authorization is not configured."},
            )

        db: Session = factory()
        try:
            user = db.get(User, int(user_id))
            if user is None or not user.is_active:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Account is no longer active.",
                             "code": "authentication_required"},
                )
            if _coerce_role(user.role) != Role.ADMIN:
                logger.info(
                    "RBAC deny: user %s (%s) tried %s %s",
                    user.id, user.role, request.method, path,
                )
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": "Administrator access required.",
                        "code": "insufficient_role",
                        "your_role": user.role,
                    },
                )
            request.state.role = user.role
        finally:
            db.close()

        return await call_next(request)