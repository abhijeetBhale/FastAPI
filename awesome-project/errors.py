"""Global exception handling.

Without these, any unhandled error returns Starlette's default response and the
client sees a bare 500 while the traceback goes to the server log. Here every
unexpected exception becomes a clean JSON body with a request id, so a client
error is never confused with a bug.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

logger = logging.getLogger("app")


def register_exception_handlers(app: FastAPI) -> None:
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

        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": detail, "code": code},
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError):
        logger.exception("Database error on %s", request.url.path)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "A database error occurred."},
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        """Last resort. Returns a reference id instead of a stack trace.

        The client gets something they can quote in a bug report; the real
        detail stays in the server log where it belongs.
        """
        request_id = uuid.uuid4().hex[:12]
        logger.exception("Unhandled error [%s] on %s", request_id, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": "Internal server error.",
                "request_id": request_id,
            },
        )