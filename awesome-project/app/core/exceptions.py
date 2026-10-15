"""Global exception handling — RFC 9457 problem responses.

Without these, any unhandled error returns Starlette's default response and the
client sees a bare 500 while the traceback goes to the server log. Here every
error becomes a problem document (`type`, `title`, `status`, `detail`) with
`Content-Type: application/problem+json`, so clients handle errors by status
code instead of sniffing body shapes.

`code` is kept as an RFC 9457 extension member — a stable machine-readable
string for cases where the status code alone is ambiguous
(`authentication_required` vs `insufficient_role` are both auth-adjacent).

See `docs/API_CONVENTIONS.md` §4.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Optional

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("app")

PROBLEM_BASE = "https://api.example.com/problems"

#: Status code → (problem type slug, title).
_TITLES = {
    400: ("bad-request", "Bad Request"),
    401: ("authentication-required", "Authentication Required"),
    403: ("forbidden", "Forbidden"),
    404: ("not-found", "Not Found"),
    405: ("method-not-allowed", "Method Not Allowed"),
    409: ("conflict", "Conflict"),
    412: ("precondition-failed", "Precondition Failed"),
    422: ("validation-error", "Validation Error"),
    429: ("rate-limited", "Too Many Requests"),
    500: ("internal-error", "Internal Server Error"),
    503: ("service-unavailable", "Service Unavailable"),
    504: ("gateway-timeout", "Gateway Timeout"),
    502: ("bad-gateway", "Bad Gateway"),
}


def problem(
    http_status: int,
    detail: str,
    *,
    title: Optional[str] = None,
    type_uri: Optional[str] = None,
    code: Optional[str] = None,
    errors: Optional[list] = None,
    extra: Optional[dict] = None,
    headers: Optional[dict] = None,
) -> JSONResponse:
    """Build an RFC 9457 problem response.

    `detail` is always a human sentence. `errors` carries field-level
    failures (`{"field", "message"}`). Anything else a caller needs
    (`request_id`, `code`) rides along as extension members.
    """
    slug, default_title = _TITLES.get(http_status, ("error", "Error"))
    body: dict[str, Any] = {
        "type": type_uri or f"{PROBLEM_BASE}/{slug}",
        "title": title or default_title,
        "status": http_status,
        "detail": detail,
    }
    if errors:
        body["errors"] = errors
    if code:
        body["code"] = code
    if extra:
        body.update(extra)
    return JSONResponse(
        status_code=http_status,
        content=body,
        media_type="application/problem+json",
        # RFC 9110 headers raised with the exception — notably `Allow` on a
        # 405 (docs/API_CONVENTIONS.md §5 requires it). Dropped headers would
        # silently disappear because this response replaces the default one.
        headers=headers,
    )


def _path_template_regex(template: str) -> re.Pattern[str]:
    """`/api/v1/admin/users/{user_id}` → a regex that matches a real path."""
    parts = []
    for segment in template.strip("/").split("/"):
        if segment.startswith("{") and segment.endswith("}"):
            # `{param}` is one segment; `{param:path}` swallows the rest.
            converter = segment[1:-1].split(":", 1)
            is_catch_all = len(converter) == 2 and converter[1] == "path"
            parts.append(r".+" if is_catch_all else r"[^/]+")
        else:
            parts.append(re.escape(segment))
    return re.compile("^/" + "/".join(parts) + "/?$")


def allowed_methods(app: FastAPI, path: str) -> list[str]:
    """Every method this app supports on `path` — for a 405's `Allow` header.

    Starlette builds `Allow` from the single `Route` object that matched the
    path, so where one path is served by several handlers the header lists only
    the first one's methods: `PATCH` was missing from
    `/api/v1/admin/users/{id}` and `DELETE` from some submission paths. RFC
    9110 §15.5.6 requires the complete set, and §5 of the API conventions
    relies on this header to document a 405.

    `HEAD` is added wherever `GET` works, mirroring Starlette's own rule.
    Preflight `OPTIONS` is answered by the CORS middleware before routing, so
    it is deliberately not listed here.
    """
    allowed: set[str] = set()
    for template, operations in app.openapi().get("paths", {}).items():
        if _path_template_regex(template).match(path):
            allowed.update(method.upper() for method in operations)
    if "GET" in allowed:
        allowed.add("HEAD")
    return sorted(allowed)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        """Every `raise HTTPException(...)` becomes a problem document.

        `detail` may be a string (used verbatim) or a dict (merged as
        extension members, with `message` promoted to `detail` when present).
        """
        status_code = exc.status_code
        detail: Any = exc.detail
        code: Optional[str] = None
        extra: Optional[dict] = None
        if isinstance(detail, dict):
            code = detail.pop("code", None)
            message = detail.pop("message", None)
            extra = detail or None
            detail = message if message else "Request failed."
        if not isinstance(detail, str):
            detail = str(detail)
        headers = dict(exc.headers or {})
        if status_code == 405:
            # Rebuild it: Starlette's own `Allow` names only the first handler
            # that matched the path, which is misleading when a path supports
            # more than one method across separate route objects.
            headers["Allow"] = ", ".join(allowed_methods(request.app, request.url.path))
        return problem(
            status_code, detail, code=code, extra=extra, headers=headers or None
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        """Schema failures become 422 with per-field `errors[]`.

        `detail` stays a readable one-line summary so callers that only read
        `detail` keep working.
        """
        fields = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err.get("loc", []) if p != "body")
            fields.append({"field": loc, "message": err.get("msg", "")})
        summary = "; ".join(
            f"{f['field']}: {f['message']}" for f in fields[:3]
        ) or "Validation failed."
        return problem(422, summary, errors=fields)

    @app.exception_handler(IntegrityError)
    async def integrity_error(request: Request, exc: IntegrityError):
        """Database constraint violations are client errors, not server bugs.

        An unhandled one currently returns a 500 plus a traceback — which leaks
        schema details and misleads whoever is debugging it.
        """
        logger.warning("IntegrityError on %s: %s", request.url.path, exc.orig)

        text = str(exc.orig)
        if "uq_users_email_lower" in text or "ix_users_email" in text:
            detail = "That email address is already registered."
            code = "duplicate_email"
        elif "fk_inspections" in text:
            detail = "A referenced record does not exist."
            code = "missing_reference"
        else:
            detail = "That operation conflicts with existing data."
            code = "constraint_violation"

        return problem(409, detail, code=code)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError):
        logger.exception("Database error on %s", request.url.path)
        return problem(503, "A database error occurred.")

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        """Last resort. Returns a reference id instead of a stack trace.

        The client gets something they can quote in a bug report; the real
        detail stays in the server log where it belongs.
        """
        request_id = uuid.uuid4().hex[:12]
        logger.exception("Unhandled error [%s] on %s", request_id, request.url.path)
        return problem(
            500, "Internal server error.", extra={"request_id": request_id}
        )
