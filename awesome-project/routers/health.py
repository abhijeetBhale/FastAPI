from datetime import datetime

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from database import get_db
from schemas.responses.health import HealthResponse, ReadinessResponse
from services.health_service import HealthService

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
def health():
    """Process-level check. Does not touch the database, so it stays fast and
    keeps reporting healthy during a database outage."""
    from main import app

    return HealthResponse(
        status="ok",
        service=app.title,
        version=app.version,
        timestamp=datetime.now(),
    )


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    responses={503: {"description": "A dependency is unavailable"}},
)
def readiness(response: Response, db: Session = Depends(get_db)):
    """Full check including the database. Returns 503 when PostgreSQL is
    unreachable, so a load balancer stops sending traffic."""
    ok, latency_ms, error = HealthService(db).check_database()
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ok" if ok else "unavailable",
        database="up" if ok else "down",
        latency_ms=round(latency_ms, 3),
        detail=error,
    )