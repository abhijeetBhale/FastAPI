from pydantic import BaseModel

from app.schemas.responses.envelope import IsoDateTime

class HealthResponse(BaseModel):
    """Liveness — the process is up and serving. Touches no dependency."""

    status: str
    service: str
    version: str
    timestamp: IsoDateTime


class ReadinessResponse(BaseModel):
    """Readiness — the app can actually serve traffic, database included."""

    status: str
    database: str
    latency_ms: float
    detail: str | None = None