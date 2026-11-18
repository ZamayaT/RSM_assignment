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

The web page should show a green "Backend status: ok" message.

## 7. Run the tests

With the services running (in another terminal):

```bash
docker compose exec backend pytest
```

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
