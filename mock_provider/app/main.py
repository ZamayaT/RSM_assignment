from fastapi import FastAPI

app = FastAPI(title="Travel Provider Mock API")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness: the process is running. Contract endpoints come in a later change."""
    return {"status": "ok"}
