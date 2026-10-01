from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

app.include_router(user_router)
app.include_router(address_router)

@app.get("/")
def root():
    return {"message": "API is running"}   