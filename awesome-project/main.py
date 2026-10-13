import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import get_settings
from database import SessionLocal
from errors import register_exception_handlers
from middlewares import install_middlewares

settings = get_settings()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Replaces the deprecated `@app.on_event("startup")`."""
    logger.info("Starting %s v%s", settings.app_title, settings.app_version)
    logger.info("Database target: %s", settings.database_url.rsplit("@", 1)[-1])
    logger.info("CORS origins: %s", ", ".join(settings.cors_origins))
    yield
    logger.info("Shutting down")


app = FastAPI(
    title=settings.app_title,
    version=settings.app_version,
    lifespan=lifespan,
    description=(
        "Cargo inspection API. Inspections belong to a user; cargo types come "
        "from a lookup table with density values."
    ),
)

# CORS origins come from config rather than being hardcoded to "*".
# Added first, so it ends up innermost — it must answer preflight requests
# before the auth middleware rejects them.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Response-Time-ms"],
)

register_exception_handlers(app)

# Auth + RBAC + request context. Added last, so these wrap everything above.
install_middlewares(app, SessionLocal)

from routers.admin import router as admin_router  # noqa: E402
from routers.auth import router as auth_router  # noqa: E402
from routers.detection import router as detection_router  # noqa: E402
from routers.health import router as health_router  # noqa: E402
from routers.inspection import portal as portal_router  # noqa: E402
from routers.lifting_plan import router as lifting_plan_router  # noqa: E402
from services.security import bearer_scheme  # noqa: E402

#: Attached to every authenticated router so OpenAPI marks those operations as
#: requiring `bearerAuth`. Swagger UI then renders the lock icon and enables its
#: Authorize dialog — otherwise /docs offers no way to sign in, because its
#: Authorize button can only hold apiKey/bearer/oauth2 and never a cookie.
#: `auto_error=False` means this changes the documentation, not the behaviour:
#: the real 401 still comes from `get_current_user`.
authed = [Depends(bearer_scheme)]

# Auth is public (login/register) but also has protected endpoints (me, change-password)
app.include_router(auth_router)
# Portal: owner-scoped operations for signed-in users
app.include_router(portal_router, dependencies=authed)
# Detection: runs on the caller's own submissions
app.include_router(detection_router, dependencies=authed)
# Lifting plan: one Markdown document per submission, no persistence
app.include_router(lifting_plan_router, dependencies=authed)
# Admin: review workflow + user management (cross-user, requires admin role)
app.include_router(admin_router, dependencies=authed)
# Health checks
app.include_router(health_router)
# Registered last so /health keeps its literal path even if a resource router
# later introduces a `/{id}` route that would otherwise shadow it.
app.include_router(health_router)

# Frontend UI (open http://127.0.0.1:8000/ui/)
STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/ui", StaticFiles(directory=STATIC_DIR, html=True), name="ui")


@app.get("/")
def root():
    return {
        "message": "API is running",
        "ui": "/ui/",
        "docs": "/docs",
        "health": "/health",
    }