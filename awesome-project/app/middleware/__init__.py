"""Middleware package.

Installed outermost-first in `install_middlewares`. Starlette runs the *last*
added middleware outermost, so the order below is the order they actually wrap:

    RequestContext            (outermost — tags every log line)
      └─ Authentication       (401 on protected prefixes)
           └─ RoleAuthorization   (403 on admin prefixes)
                └─ CORS
                     └─ routes

`AuthenticationMiddleware` must sit outside `RoleAuthorizationMiddleware`: the
role layer reads the user id the auth layer attaches to `request.state`.
"""

from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy.orm import sessionmaker

from app.middleware.auth import AuthenticationMiddleware, is_protected
from app.middleware.context import RequestContextMiddleware
from app.middleware.rbac import RoleAuthorizationMiddleware, is_admin_path

__all__ = [
    "AuthenticationMiddleware",
    "RequestContextMiddleware",
    "RoleAuthorizationMiddleware",
    "install_middlewares",
    "is_admin_path",
    "is_protected",
]


def install_middlewares(
    app: FastAPI,
    session_factory: sessionmaker,
    *,
    trust_forwarded_for: bool = False,
) -> None:
    """Attach the middleware stack.

    Added in reverse execution order — Starlette treats the most recently added
    middleware as the outermost wrapper.

    The factory is published on `app.state` rather than captured, so the RBAC
    middleware reads whatever the app currently considers authoritative.
    """
    app.state.session_factory = session_factory

    app.add_middleware(RoleAuthorizationMiddleware)
    app.add_middleware(AuthenticationMiddleware)
    app.add_middleware(
        RequestContextMiddleware, trust_forwarded_for=trust_forwarded_for
    )