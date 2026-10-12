from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="User-Address API", version="1.0.0")

# CORS (for frontend dev)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
from routers.user import router as user_router
from routers.address import router as address_router
from routers.inspection import router as inspection_router
from routers.health import router as health_router

app.include_router(user_router)
app.include_router(address_router)
app.include_router(inspection_router)
# Registered last so /health keeps its literal path even if a resource router
# later introduces a `/{id}` route that would otherwise shadow it.
app.include_router(health_router)

# Small frontend UI for the inspection flow (open http://127.0.0.1:8000/ui/)
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