# Change 00 — Project skeleton

Status: Complete

## Goal
A runnable empty platform: one command (`docker compose up --build`) starts PostgreSQL, backend, provider mock, and frontend, each answering a basic request. No business logic.

## Scope
- Repository layout and tooling for backend, mock provider, and frontend.
- Docker Compose with persistent PostgreSQL volume.
- Configuration through environment variables with `.env.example`.
- Test runner working with one trivial test.
- README updated with the real setup steps.

## Out of scope
- Any domain logic, users, trips, database tables, worker process, MCP, assistant, real mock endpoints.

## Assumptions to confirm
- Database access with SQLAlchemy and migrations with Alembic. Alembic is only installed and initialized here (no tables yet).
- Planned ports: frontend 5173, backend 8000, mock provider 4010, PostgreSQL 5432.
- The worker service is added in the change that first needs it (bookings), not here.

## Tasks

### Repository and configuration
- [x] 1.1 Create folders `backend/`, `mock_provider/`, `frontend/` and a root `.gitignore` (Python, Node, `.env`, volumes).
- [x] 1.2 Create `.env.example` with ports, database credentials, and service URLs; no real secrets.

### Backend
- [x] 2.1 FastAPI app in `backend/` with dependency file, `GET /health` returning `{"status": "ok"}`, and a Dockerfile.
- [x] 2.2 Settings module reading configuration from environment variables (no hardcoded values).
- [x] 2.3 PostgreSQL connection (SQLAlchemy) and Alembic initialized; `GET /health/ready` checks the database connection and returns 503 if unavailable.
- [x] 2.4 `pytest` configured with one test for `GET /health`.

### Provider mock (placeholder)
- [x] 3.1 Minimal FastAPI app in `mock_provider/` with `GET /health` and a Dockerfile. Real contract endpoints come in change 01.

### Frontend
- [x] 4.1 Vite + React app in `frontend/` with MUI installed, a basic layout with navigation placeholder, and a Dockerfile.
- [x] 4.2 The page displays the backend status by calling `GET /health` (proves frontend-backend connectivity; backend URL from configuration).

### Docker Compose
- [x] 5.1 `docker-compose.yml` with services `postgres` (named volume), `backend`, `mock_provider`, `frontend`; backend waits for a healthy database.
- [x] 5.2 Verify `docker compose up --build` starts everything from a clean clone and that data in the PostgreSQL volume survives `docker compose down` and a new `up`.

### Documentation
- [x] 6.1 Update `README.md`: add Docker Desktop to requirements, and steps for `.env` creation, start, URLs, running `pytest`, stop, and reset (`down -v`), each with a copy-paste command. Only what is implemented in this change.

## Acceptance criteria
- Following the README on a clean clone starts all four services with no manual steps beyond the documented commands.
- `http://localhost:5173` shows the app with the backend status as "ok".
- `http://localhost:8000/health` and `http://localhost:4010/health` return `ok`; `/health/ready` fails when PostgreSQL is stopped.
- `docker compose exec backend pytest` passes.
- Stopping and restarting keeps the database volume; `down -v` clears it.
- No secrets committed; `.env` is ignored by git.

## Technologies implemented
- Docker and Docker Compose: run PostgreSQL, backend, provider mock, and frontend with one command (`docker-compose.yml`).
- PostgreSQL 16: main database, with a named volume so data survives restarts.
- Python 3.12: language of the backend and the provider mock.
- FastAPI: web framework for the backend and the provider mock.
- Uvicorn: server that runs the FastAPI apps.
- pydantic-settings: reads backend configuration from environment variables (`backend/app/config.py`).
- SQLAlchemy 2: database access layer (`backend/app/db.py`).
- psycopg 3: PostgreSQL driver used by SQLAlchemy.
- Alembic: database migrations (`backend/migrations/`); initialized, no migrations yet.
- pytest and httpx: backend tests (httpx powers FastAPI's test client).
- Node.js 22: runtime for the frontend container.
- React 19 and TypeScript: frontend application (`frontend/src/`).
- Vite: frontend dev server and build tool.
- MUI (Material UI) and Emotion: UI components and the styling engine MUI requires.
