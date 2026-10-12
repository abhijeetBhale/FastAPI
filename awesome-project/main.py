import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import get_settings
from errors import register_exception_handlers

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
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

register_exception_handlers(app)

from routers.health import router as health_router  # noqa: E402
from routers.inspection import router as inspection_router  # noqa: E402
from routers.user import router as user_router  # noqa: E402

app.include_router(user_router)
app.include_router(inspection_router)
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