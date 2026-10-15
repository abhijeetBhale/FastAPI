import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1 import API_PREFIX
from app.api.v1.api import api_router, health_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.database.database import SessionLocal
from app.middleware import install_middlewares

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
    # `/docs` is served by `swagger_ui()` below rather than by FastAPI's
    # default docs route: the default can only take JSON parameters, and the
    # method sorter this API wants is a JavaScript function.
    docs_url=None,
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

# Routing is assembled in `app/api/v1/api.py` and mounted here, so this module
# stays a description of the *app* — middleware, error handling, the static
# client — rather than a list of resources.
app.include_router(api_router)

# Health checks stay unversioned (D1): probe paths are configured in load
# balancers and containers, and are not part of the versioned API contract.
# Registered last, so /health keeps its literal path even if a resource router
# later introduces a `/{id}` route that would shadow it.
# Included exactly once: a second include duplicates the routes and their
# OpenAPI operationIds.
app.include_router(health_router)

# Frontend UI (open http://127.0.0.1:8000/ui/)
STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/ui", StaticFiles(directory=STATIC_DIR, html=True), name="ui")


#: Swagger UI's own `operationsSorter: "method"` orders every tag's operations
#: GET, PUT, POST, DELETE, … — not the order this API documents. A custom sorter
#: has to be a JavaScript function, and FastAPI's docs renderer JSON-encodes
#: every `swagger_ui_parameters` value, so a function cannot travel through it.
#: `/docs` is therefore rendered by hand: FastAPI's HTML is produced with a
#: placeholder, and the placeholder is swapped for this function literal. The
#: order is GET, POST, PUT, PATCH, DELETE; ties keep their path order, because
#: the sort is stable.
_METHOD_ORDER_JS = (
    "function (a, b) {"
    '  var order = ["get", "post", "put", "patch", "delete", "options", "head", "trace"];'
    '  var ai = order.indexOf(String(a.get("method") || "").toLowerCase());'
    '  var bi = order.indexOf(String(b.get("method") || "").toLowerCase());'
    "  return (ai < 0 ? order.length : ai) - (bi < 0 ? order.length : bi);"
    "}"
)

#: Distinct enough that no other part of the generated HTML contains it.
_METHOD_ORDER_PLACEHOLDER = "__method_order_sorter__"


@app.get("/docs", include_in_schema=False)
def swagger_ui() -> HTMLResponse:
    """Swagger UI, ordered GET, POST, PUT, PATCH, DELETE within each tag."""
    html = get_swagger_ui_html(
        openapi_url=app.openapi_url or "/openapi.json",
        title=f"{app.title} - Swagger UI",
        swagger_ui_parameters={"operationsSorter": _METHOD_ORDER_PLACEHOLDER},
    ).body.decode("utf-8")
    return HTMLResponse(
        html.replace(f'"{_METHOD_ORDER_PLACEHOLDER}"', _METHOD_ORDER_JS)
    )


@app.get("/")
def root():
    from app.schemas.responses.envelope import envelope

    return envelope(
        {
            "message": "API is running",
            "api": API_PREFIX,
            "ui": "/ui/",
            "docs": "/docs",
            "health": "/health",
        }
    )
