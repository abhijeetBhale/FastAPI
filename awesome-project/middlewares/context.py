"""Request context: a correlation id, timing, and the resolved user.

Runs outermost so that every other layer — including the access middlewares and
any exception handler — can attach its log lines to the same request id. That id
is also what an unhandled-error response returns, so a client can quote it.
"""

from __future__ import annotations

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("app.request")

REQUEST_ID_HEADER = "X-Request-ID"
CLIENT_IP_HEADER = "X-Client-IP"


class RequestContextMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, trust_forwarded_for: bool = False):
        super().__init__(app)
        self.trust_forwarded_for = trust_forwarded_for

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        request.state.started_at = time.perf_counter()

        if self.trust_forwarded_for:
            # Only enable behind a proxy you control; otherwise a client can
            # spoof its own address.
            client_ip = request.headers.get(CLIENT_IP_HEADER)
            if client_ip:
                request.state.client_ip = client_ip

        try:
            response = await call_next(request)
        except Exception:
            elapsed = (time.perf_counter() - request.state.started_at) * 1000
            logger.exception(
                "[%s] %s %s failed after %.1fms",
                request_id, request.method, request.url.path, elapsed,
            )
            raise

        elapsed = (time.perf_counter() - request.state.started_at) * 1000
        request.state.elapsed_ms = elapsed
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers["X-Response-Time-ms"] = f"{elapsed:.1f}"

        # 5xx is worth a log line; 2xx/4xx are not.
        if response.status_code >= 500:
            logger.error(
                "[%s] %s %s -> %d in %.1fms",
                request_id, request.method, request.url.path,
                response.status_code, elapsed,
            )
        else:
            logger.debug(
                "[%s] %s %s -> %d in %.1fms",
                request_id, request.method, request.url.path,
                response.status_code, elapsed,
            )
        return response