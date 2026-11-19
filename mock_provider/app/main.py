from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import v1_router
from app.control_routes import router as control_router
from app.errors import install_error_handling
from app.fixtures import seed_if_empty


@asynccontextmanager
async def lifespan(_: FastAPI):
    seed_if_empty()
    yield


app = FastAPI(title="Travel Provider Mock API", lifespan=lifespan)
install_error_handling(app)
app.include_router(v1_router)
app.include_router(control_router)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness: the process is running. Contract endpoints live under /v1."""
    return {"status": "ok"}
