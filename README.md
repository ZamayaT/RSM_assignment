# Travel Planning Platform

Group trip planning with provider search, simulated bookings, PDF trip documents, and a read-only AI assistant using MCP.

> Status: under construction. This README only documents what is already implemented; setup steps are added as each development step is completed.

Everything runs in **Docker**: Python, Node, PostgreSQL and all packages are installed inside containers. On your machine you only need Git and Docker Desktop.

## 1. Requirements

| Program | Purpose | Download |
|---|---|---|
| Git | Clone the repository | https://git-scm.com/downloads |
| Docker Desktop (includes Docker Compose) | Build and run all services | https://www.docker.com/products/docker-desktop/ |

On Windows, Docker Desktop requires WSL 2. The installer offers to enable it; accept and restart if asked.

## 2. Check the installation

Open a terminal (PowerShell, Git Bash, or a macOS/Linux terminal) and run:

```bash
git --version
docker --version
docker compose version
```

Each command should print a version. Open Docker Desktop and wait until it is running before continuing.

## 3. Clone the repository

```bash
git clone https://github.com/ZamayaT/RSM_assignment.git
cd RSM_assignment
```

## 4. Create the configuration file

Copy the example configuration. The defaults work for a local run; edit `.env` only if a port is already in use.

```bash
cp .env.example .env
```

## 5. Build and start everything

The first run downloads images and installs packages; it can take several minutes.

```bash
docker compose up --build
```

Leave this terminal open; it shows the logs of all services. Press `Ctrl+C` to stop.

To run in the background instead:

```bash
docker compose up --build -d
```

## 6. Open the application

| Service | URL |
|---|---|
| Web application | http://localhost:5173 |
| Backend API documentation | http://localhost:8000/docs |
| Provider mock API documentation | http://localhost:4010/docs |

The start page lists the seeded test users (`alice`, `bob`, `carol`). The backend creates them on startup if the database has none, and applies its migrations automatically when its container starts.

To log in, click a name. From there you can create a trip (name, destinations Lisbon/Paris/Rome, dates, travelers, budget in USD, notes), see it under **My trips**, open it, and edit it. Use **Switch user** in the top bar to log in as someone else: each user sees only their own trips. If two people edit the same trip, the second save is refused with a "changed by someone else" message and nothing is overwritten; click **Reload latest** to continue from the newest version. Your login is kept in the browser, so a page reload keeps you signed in.

To share a trip, open it and click **Participants**. As the organizer, type a username (suggestions appear as you type), choose **editor** or **viewer**, and click **Add**. You can also change a participant's role or remove them. To try the roles, add `bob` as viewer and `carol` as editor, then use **Switch user**: a viewer can read the trip but not edit it, an editor can edit the trip but sees the participants read-only, and a user who is not on the trip (or was removed) does not see it. The backend enforces these rules, not only the screens.

To search, open a trip and click **Search**. Choose a category (transport, accommodation, activity), one of the trip's destinations (transport also asks for an origin), adjust the dates, travelers or supplier if you like, and click **Search**. The results table can be sorted by price, start time or supplier. Results are estimates from the provider mock, not bookings: prices are not guaranteed, and each offer shows when it was searched and until when the quote is valid. Anyone on the trip, including viewers, can search.

To try a partial or failed search, run these in a terminal while the services are running, then search accommodation again in the browser:

```bash
# one supplier down: the page shows the other suppliers' results and a warning for supplier-b
curl -s -X PUT http://localhost:4010/control/suppliers/supplier-b/failure -H "Content-Type: application/json" -d '{"mode":"unavailable"}'

# all accommodation suppliers down: the page shows "The search failed" with a "Try again" button
curl -s -X PUT http://localhost:4010/control/suppliers/supplier-a/failure -H "Content-Type: application/json" -d '{"mode":"unavailable"}'
curl -s -X PUT http://localhost:4010/control/suppliers/supplier-c/failure -H "Content-Type: application/json" -d '{"mode":"unavailable"}'

# back to normal
curl -s -X POST http://localhost:4010/control/reset
```

The backend waits at most `PROVIDER_TIMEOUT_SECONDS` (default 5, set in `.env`) for the provider.

The API endpoints are listed and can be tried at http://localhost:8000/docs.

## 7. Run the tests

With the services running (in another terminal):

```bash
docker compose exec backend pytest
docker compose exec mock_provider pytest
```

The search tests call the real provider mock over HTTP, so the `mock_provider` service must be running; they reset the mock before and after each test, which also clears any failures you set by hand. The backend tests create and use their own database (`<POSTGRES_DB>_test`, dropped and recreated on each run), so your trips and logins are never touched. All of them should pass; they cover login, validation, trips, visibility, versioning conflicts, concurrent saves and persistence across a restart.

The provider mock stores its data in its own PostgreSQL schema (`mock_provider`) and applies its migrations automatically when its container starts. Its fixtures, demo tokens, clock, `/control` endpoints and copy-paste failure scenarios are documented in [`mock_provider/README.md`](mock_provider/README.md). On startup it also loads its fixture offers (Lisbon, Paris, Rome) if there are none.

The mock's clock follows real time by default. To freeze it or shift it, uncomment `MOCK_CLOCK_FROZEN_AT` (for example `2030-01-15T09:00:00Z`) or `MOCK_CLOCK_OFFSET_SECONDS` in `.env`, then run `docker compose up -d mock_provider`. Fixture dates are generated relative to the clock when they are first loaded.

## 8. Stop and reset

Stop the services (data is kept):

```bash
docker compose down
```

Stop and **delete all data** (the database volume) to start from scratch:

```bash
docker compose down -v
```

## 9. Troubleshooting

- **Port already in use**: change the port variables (`FRONTEND_PORT`, `BACKEND_PORT`, `MOCK_PROVIDER_PORT`) in `.env`. If you change `FRONTEND_PORT`, also update `FRONTEND_ORIGIN`; if you change `BACKEND_PORT`, also update `VITE_BACKEND_URL`. Then run `docker compose up --build` again.
- **Docker commands fail**: make sure Docker Desktop is running.
- **See the logs of one service**:

  ```bash
  docker compose logs -f backend
  ```

## Project documentation

- `assignment/`: original assignment (PRD, candidate guide, provider contract `openAPI.json`).
- `claude/PROJECT.md`: project summary, requirements, decisions, architecture, build plan.
- `claude/CLAUDE.md`: AI development rules (development harness).
- `claude/changes/`: one file per development step with its tasks.
