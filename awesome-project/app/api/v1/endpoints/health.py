from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import problem
from app.database.base import utcnow
from app.database.database import get_db
from app.schemas.responses.envelope import envelope
from app.schemas.responses.health import HealthResponse, ReadinessResponse
from app.services.health_service import HealthService

router = APIRouter(tags=["Health"])


@router.get("/health", summary="Liveness probe")
def health():
    """Process-level check. Does not touch the database, so it stays fast and
    keeps reporting healthy during a database outage."""
    settings = get_settings()
    return envelope(
        HealthResponse(
            status="ok",
            service=settings.app_title,
            version=settings.app_version,
            timestamp=utcnow(),
        ).model_dump(mode="json")
    )


@router.get(
    "/health/ready",
    summary="Readiness probe",
    responses={503: {"description": "A dependency is unavailable"}},
)
def readiness(db: Session = Depends(get_db)):
    """Full check including the database. Returns 503 when PostgreSQL is
    unreachable, so a load balancer stops sending traffic — and per §4 the
    503 body is an RFC 9457 problem document, not an envelope."""
    ok, latency_ms, error = HealthService(db).check_database()
    if not ok:
        return problem(503, error or "The database is unreachable.")
    return envelope(
        ReadinessResponse(
            status="ok",
            database="up",
            latency_ms=round(latency_ms, 3),
        ).model_dump(mode="json")
    )