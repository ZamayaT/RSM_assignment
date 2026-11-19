# Travel Planning Platform

Group trip planning with provider search, simulated bookings, PDF trip documents, and a read-only AI assistant using MCP. Everything runs in Docker; you only need Git and Docker Desktop.

## Run it

### 1. Requirements

| Program | Download |
|---|---|
| Git | https://git-scm.com/downloads |
| Docker Desktop (includes Docker Compose; on Windows it needs WSL 2) | https://www.docker.com/products/docker-desktop/ |

Check them (each prints a version), and start Docker Desktop:

```bash
git --version
docker --version
docker compose version
```

### 2. Get the code and the configuration

```bash
git clone https://github.com/ZamayaT/RSM_assignment.git
cd RSM_assignment
cp .env.example .env
```

The defaults work locally; edit `.env` only if a port is in use or to enable the assistant (step 5).

### 3. Start

```bash
docker compose up --build -d
```

The first run takes several minutes. Migrations, test users and the mock's offers are created automatically.

### 4. Open

| Service | URL |
|---|---|
| Web application | http://localhost:5173 |
| Backend API docs | http://localhost:8000/docs |
| Provider mock API docs | http://localhost:4010/docs |

Log in by clicking a test user (`alice`, `bob`, `carol`, `daniela`; no passwords).

### 5. Enable the assistant (optional)

The assistant needs a model behind an OpenAI-compatible API. With a free OpenRouter key (https://openrouter.ai/keys), uncomment `LLM_API_KEY=` in `.env` and paste the key (the base URL and a free model are already the defaults), then:

```bash
docker compose up -d backend
docker compose exec backend python -m app.assistant.probe
```

The probe checks that the model answers and uses tools (it never prints the key). Without a key the Assistant tab says what to set; everything else works.

### 6. Tests and checks

With the services running:

```bash
docker compose exec backend pytest
docker compose exec mock_provider pytest
docker compose exec backend ruff check .
docker compose exec mock_provider ruff check .
docker compose exec frontend npm run typecheck
docker compose exec backend python -m evals.search
```

All should pass. The backend tests use their own database (`<POSTGRES_DB>_test`), reset the mock around each test, take about 3 minutes and never call a model. The model-dependent evaluation, `python -m evals.assistant`, needs the key (see below).

### 7. Stop

```bash
docker compose down      # keeps the data
docker compose down -v   # deletes the database and the generated documents
```

### Troubleshooting

- **Port in use**: change `FRONTEND_PORT`, `BACKEND_PORT` or `MOCK_PROVIDER_PORT` in `.env` (and `FRONTEND_ORIGIN` or `VITE_BACKEND_URL` to match), then `docker compose up --build -d`.
- **Old mock data** (a mock database from before the current catalogue): `curl -s -X POST http://localhost:4010/control/reset`.
- **Trace an error**: every error shown in the browser has a request id; `docker compose logs backend | grep req-...` shows everything that request did.

## What it does and how to try it

Short reference; a guided walkthrough with failure and concurrency scenarios is in [`docs/demo.md`](docs/demo.md), and the mock's data and failure switches in [`mock_provider/README.md`](mock_provider/README.md).

- **Trips and roles**: create a trip (destinations Lisbon, Paris, Rome; dates; travelers; USD budget; notes) and share it from **Participants** as *editor* or *viewer*. Viewers only read; non-participants get nothing. The backend enforces it, not just the screens.
- **Search**: transport, stays and activities (including museum and food places tours) from Supplier Alamo, Boots and Croc, from the day after today until 31 January 2027; a trip outside that window finds nothing. Results show price, schedule, availability, restrictions, search time and quote validity, and are labelled complete, partial (a supplier failed), empty or failed. Try a failure: `curl -s -X PUT http://localhost:4010/control/suppliers/supplier-boots/failure -H "Content-Type: application/json" -d '{"mode":"unavailable"}'` (undo with `curl -s -X POST http://localhost:4010/control/reset`).
- **Itinerary and budget**: add results, reorder and remove items; warnings for overlaps (UTC instants; a stay may overlap other items, two stays may not), missing data, expired quotes, items outside the trip dates or destinations. Costs are the offer totals for the party, exact to the cent (half-up rounding); estimates and confirmed prices are kept apart.
- **Concurrent edits**: one version per trip; a stale save is refused with a dialog to re-apply or discard, so nothing is overwritten.
- **Bookings**: **Book** shows the current terms next to the saved estimate and books only what you confirm. Statuses: estimate, pending, confirmed, failed, unknown. A lost response becomes *Unknown* and the `worker` settles it with the provider (never booking twice); after about 10 minutes without an answer it shows **Outcome unresolved** with **Check again**. Timings: `BOOKING_*` in `.env.example`.
- **Documents**: **Generate document** builds a PDF in the background (waiting, in progress, complete, failed), from a snapshot of the trip at that moment. Downloads verify the file's checksum; a failed or damaged one can be retried. PDFs live in the `documents_data` volume.
- **Assistant**: the last tab answers travel questions with a real model that can only read (trip, itinerary, budget, bookings, search) as the logged-in user, and lists the tools it used (hide them with `VITE_SHOW_ASSISTANT_TOOLS=false`). It cannot book or change anything. Only the last question and answer are kept, in the browser session. Tool results are sent to the model provider: use test data only. Free models allow about 50 requests a day (2 to 4 per question).
- **MCP**: the read-only tools are at `http://localhost:8000/mcp` (same bearer token as the API). `search_options` returns the 20 best offers and says how many matched. List them:

  ```bash
  TOKEN=$(curl -s -X POST localhost:8000/auth/login -H 'Content-Type: application/json' -d '{"username":"alice"}' | python -c "import sys,json;print(json.load(sys.stdin)['token'])")
  curl -s -X POST localhost:8000/mcp -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
  ```

- **Evaluations**: `evals.search` is deterministic and free. `docker compose exec backend python -m evals.assistant` asks the model a few scenarios (cheapest within budget, nothing suitable, provider down, a request to book, and more), checks the answers with rules, prints a pass rate and writes a JSON report to `backend/evals/results/`. It costs about 2 to 3 model calls per scenario (`--only a,b`, `--runs 3`, `--list`).

## Deployment proposal

Not deployed; Compose is for local use (development servers). To deploy: run the same images on one container host behind an HTTPS reverse proxy, serve the frontend as static files (`npm run build`), keep the `worker` as a second container of the backend image, use a managed PostgreSQL with backups and a backed-up volume or object storage for PDFs, keep secrets (`POSTGRES_PASSWORD`, `PROVIDER_TOKEN`, `LLM_API_KEY`) in the host's secret store, and use `GET /health` and `GET /health/ready` as health checks. Real authentication and the real provider must replace the test users and the mock first.

## Documentation

- [`docs/architecture.md`](docs/architecture.md): decisions, guarantees, evaluation areas, limitations.
- [`docs/demo.md`](docs/demo.md): demo walkthrough and failure recipes.
- [`docs/ai-usage.md`](docs/ai-usage.md): how AI was used and verified.
- [`mock_provider/README.md`](mock_provider/README.md): the provider mock.
- `claude/`: the AI development harness (`CLAUDE.md` rules, `PROJECT.md` summary, `changes/` steps).
- `assignment/`: the original assignment, unchanged.
