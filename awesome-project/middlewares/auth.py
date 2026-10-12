"""Authentication gate.

Rejects unauthenticated requests to protected path prefixes *before* routing and
before any handler runs. This is a cheap first line of defence; the real,
ownership-aware checks live in `services.rbac.py` dependencies.

Why a prefix list rather than per-route checks: it fails closed. Forgetting to
add a check to a new route cannot leave it open, because the default for an
unlisted prefix is public and the default for a listed one is closed.
"""

from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from services.security import COOKIE_NAME, decode_access_token

logger = logging.getLogger("app.auth")

#: Prefixes that require a valid session credential.
PROTECTED_PREFIXES: tuple[str, ...] = (
    "/portal",
    "/admin",
)

_BEARER_PREFIX = "bearer "


def extract_token(request: Request) -> str | None:
    """Return the session JWT, from the cookie or an Authorization header.

    The cookie is preferred so the browser portal is unaffected. The bearer
    fallback exists because Swagger UI's "Authorize" button cannot hold a cookie,
    and this middleware runs before routing — so without it, a perfectly valid
    `Authorization: Bearer <jwt>` would be rejected here and never reach the
    dependency that would have accepted it.
    """
    token = request.cookies.get(COOKIE_NAME)
    if token:
        return token

    header = request.headers.get("Authorization", "")
    if header[: len(_BEARER_PREFIX)].lower() == _BEARER_PREFIX:
        return header[len(_BEARER_PREFIX) :].strip() or None
    return None

#: Paths inside a protected prefix that stay reachable while signed out, so an
#: expired session can be refreshed rather than dead-ending.
PUBLIC_EXCEPTIONS: frozenset[str] = frozenset(
    {
        "/admin/login-as",  # reserved for future use
    }
)

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def is_protected(path: str) -> bool:
    if path in PUBLIC_EXCEPTIONS:
        return False
    return any(path == p or path.startswith(p + "/") or path.startswith(p)
               for p in PROTECTED_PREFIXES)


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """Blocks anonymous traffic to the protected prefixes."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path

        if is_protected(path):
            token = extract_token(request)
            if not token:
                return self._deny(
                    request, 401, "Sign in to continue.", needs_auth=True
                )
            try:
                payload = decode_access_token(token)
            except Exception:
                return self._deny(
                    request, 401, "Your session is invalid or has expired.",
                    needs_auth=True,
                )
            # Stash the claims so downstream layers do not re-verify the token.
            request.state.auth = payload
            request.state.user_id = payload.get("sub")

        return await call_next(request)

    def _deny(
        self, request: Request, code: int, detail: str, *, needs_auth: bool
    ) -> JSONResponse:
        body = {"detail": detail}
        if needs_auth:
            # Lets the UI distinguish "log in" from "you may not do this".
            body["code"] = "authentication_required"
        return JSONResponse(status_code=code, content=body, headers={"X-Auth": "required"})