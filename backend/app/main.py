from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db import check_database

app = FastAPI(title="Travel Planning Platform API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().frontend_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness: the process is running."""
    return {"status": "ok"}


@app.get("/health/ready")
def ready() -> JSONResponse:
    """Readiness: the database is reachable."""
    if check_database():
        return JSONResponse({"status": "ok"})
    return JSONResponse({"status": "unavailable", "database": "down"}, status_code=503)
