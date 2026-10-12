from datetime import datetime

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Liveness — the process is up and serving. Touches no dependency."""

    status: str
    service: str
    version: str
    timestamp: datetime


class ReadinessResponse(BaseModel):
    """Readiness — the app can actually serve traffic, database included."""

    status: str
    database: str
    latency_ms: float
    detail: str | None = None