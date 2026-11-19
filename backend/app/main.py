from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import auth, bookings, budget, destinations, documents, itinerary, participants, search, trips, users
from app.config import get_settings
from app.db import check_database
from app.errors import install_error_handling
from app.logging_setup import setup_logging
from app.seed import run_seed


@asynccontextmanager
async def lifespan(_: FastAPI):
    run_seed()
    yield


setup_logging()

app = FastAPI(title="Travel Planning Platform API", lifespan=lifespan)

install_error_handling(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().frontend_origin],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],  # the browser reads the download file name from it
)

app.include_router(auth.router)
app.include_router(destinations.router)
app.include_router(trips.router)
app.include_router(participants.router)
app.include_router(users.router)
app.include_router(search.router)
app.include_router(itinerary.router)
app.include_router(budget.router)
app.include_router(bookings.router)
app.include_router(documents.router)


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
