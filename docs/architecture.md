# Architecture note

A group plans a trip: shared trips, provider search, an itinerary with costs, simulated bookings, PDF trip documents and a read-only AI assistant that uses MCP tools. Details and requirements are in [`claude/PROJECT.md`](../claude/PROJECT.md); this note is the short version.

## Components

```
frontend (React + Vite + MUI)  --REST-->  backend (FastAPI)  --HTTP-->  mock_provider (FastAPI, the supplied contract)
                                            |  \-- /mcp (read-only MCP tools) <-- assistant loop --> LLM API (OpenAI-compatible)
                                            |
worker (same image, other entrypoint) ------+--> PostgreSQL (app data; the mock has its own schema)
                                            \--> volume with the generated PDFs
```

One repository, one `docker compose up`. The backend is a modular monolith; the worker shares its code and runs documents and booking reconciliation. The provider is reached only over HTTP through its public contract (`backend/app/provider_client.py`); the mock's `/control` endpoints are used only by tests, evaluations and the demo.

## Key decisions and the alternatives rejected

| Decision | Why | Rejected |
|---|---|---|
| One integer `version` per trip, optimistic locking | Simple and safe; the second of two saves gets `409` with the latest data | Pessimistic locks; per-item versions (more false-conflict code than value) |
| `Decimal` with two digits for all money | Provider amounts are two-decimal strings, so totals are exact | Floats |
| A booking attempt row is saved **before** calling the provider, with a stable `clientReference` and `Idempotency-Key` | A lost answer can be reconciled; repeating a decision never books twice | Calling first, then saving |
| PostgreSQL job table + worker (`FOR UPDATE SKIP LOCKED`) | Survives restarts; no extra service | `BackgroundTasks` (lost on restart); Celery/Redis |
| Polling for status | State always comes from the database; reloads and disconnects recover for free | WebSockets |
| PDFs on a volume, metadata, size and SHA-256 in PostgreSQL, a frozen JSON snapshot per document | Later edits never change an existing document; tampering is detected | Bytes in the database |
| MCP inside the backend at `/mcp` (official `mcp` SDK, HTTP) | Permissions are enforced in one place and the tools call only read code | A separate MCP process (duplicated permission logic) |
| A real model through an OpenAI-compatible API, configured only by `LLM_*` variables | No paid key and no simulated answers; the provider is replaceable | A scripted model as the product; one vendor's SDK |
| Seeded users, token login, no passwords | The assignment excludes production identity | Registration, passwords |

## Guarantees and where each is verified

| Guarantee | How it works | Verified by |
|---|---|---|
| Access follows the role (organizer, editor, viewer); a non-participant gets `404` | One permission helper (`trips.py`) used by every endpoint and every MCP tool | `test_permissions.py`, `test_*_permissions.py`, `test_mcp.py` |
| No lost update | Version check on save; `409` with current data | `test_versioning.py`, `test_itinerary_concurrency.py` |
| Exact budget, estimated versus confirmed kept apart | `Decimal`; confirmed totals use the accepted price, which later price changes never alter | `test_budget.py` |
| A booking is never duplicated and an unknown outcome is never shown as failed or confirmed | Attempt saved first; reconcile by reference, replay only if the provider has no record, backoff, then "unresolved" | `test_bookings_flow.py`, `test_bookings_recovery.py` |
| One supplier down gives a partial result with a warning; all down gives an error | Per-supplier warnings kept with the other offers | `test_search.py`, `evals.search` |
| Documents survive restarts and keep their content | Job states, a stuck job returns to the queue, write to a temporary file then rename, checksum on download | `test_documents_*.py` |
| The assistant can only read, for everyone | No write tool exists; each tool re-checks the user from the bearer token; the endpoint rejects any other `trip_id`; `mcp_server` and `assistant` import no write module | `test_mcp.py`, `test_assistant.py` |
| Failures are visible | Tool errors are returned as errors, shown in the "Tools used" list and required in the answer by the system prompt | `test_assistant.py` (our loop), `evals.assistant` (the model) |

## Evaluation areas of the candidate guide: where each is implemented

Checked against the code. "Gap" marks what is only partly met or not met (details also in the known limitations).

| Area | Where and how it is implemented | Gap |
|---|---|---|
| Architecture and organization | Separate services: `frontend/`, `backend/` (FastAPI modules: `trips`, `itinerary`, `itinerary_rules`, `budget`, `search`, `bookings`, `documents`, `provider_client`, `mcp_server/`, `assistant/`), `worker` (same image, `app.worker`) and `mock_provider/`. Calculations are pure code (`budget.py`, `itinerary_rules.py`); permission checks live in one place (`trips.py`: `can_read`, `can_edit`, `require`). The provider is reached only through `provider_client.py`; `mcp_server` and `assistant` import no write module (tested). | None known |
| Persistence and integrity | PostgreSQL with Alembic migrations (`backend/migrations/versions/0001` to `0005`, applied on backend start); check and unique constraints in `models.py` (dates, budget, travelers, one offer per trip item); a booking attempt is saved before the provider call and kept as history; each document keeps its snapshot, file, size and SHA-256; PDFs are written to a temporary file, flushed and renamed (`document_storage.py`). | None known |
| Calculations, freshness and performance | All money is `Decimal` with two digits (`budget.py: money`), estimated and confirmed kept apart, confirmed items use the accepted price. Search results show `searchedAt` and each offer's `validUntil`; itinerary items are marked expired locally (`itinerary_rules.is_expired`); booking always re-reads the offer first and asks for confirmation of changed terms. | No cache of search results (each search calls the provider; simplest and never stale). No performance or load tests. |
| Communication and protocols | REST with one error body (`code`, `message`, `requestId`, `details`) from `errors.py`; MCP over HTTP at `/mcp` with the official SDK, consumed by the assistant through the same endpoint (`mcp_bridge.py`); status by polling (Bookings, Documents, Itinerary pages), so a reload or lost connection recovers the real state from the database. | No push notifications (a deliberate choice: polling). |
| Concurrency and background processing | Optimistic locking: the save updates only `WHERE version = :seen` and returns `409` otherwise (`trips.py`, itinerary endpoints), with a conflict dialog in the UI. Repeated booking requests reuse the attempt's idempotency key and reference. Worker claims jobs with `FOR UPDATE SKIP LOCKED`; stuck documents return to the queue and are failed after a maximum of attempts; unknown bookings are reconciled with backoff (`booking_steps.py`, `document_steps.py`). | None known |
| Integrations and failures | `provider_client.py` maps every provider error (timeout, unreachable, 429 with Retry-After, `OFFER_CHANGED`, `OFFER_UNAVAILABLE`, `REFERENCE_CONFLICT`, malformed answer) to a typed error; the supplied contract is unchanged; the mock has `/control` failure switches (never used by the application); reproducible scenarios are in the mock's README and `docs/demo.md`; the search keeps partial results with per-supplier warnings. | None known |
| Documents and storage | PDF built from a frozen snapshot with the trip version, time and author; all generations kept; download re-checks existence and checksum and marks a mismatch as failed so it can be regenerated; downloads need participant access. Tested in `test_documents_*.py`. | Files live on one volume; no object storage. |
| Security, configuration and diagnostics | Permissions on REST and on MCP tools (a trip id alone grants nothing; non-participant gets `404`); the assistant endpoint also rejects any other `trip_id`. All configuration comes from environment variables (`config.py`, `.env.example`), and `.env` is git-ignored. Every request gets an id (`X-Request-Id`, `requestId` in errors) that appears in every log line, the provider call and the assistant's model call, and an unexpected error is a standard `500` with the id. | Test identities only (allowed by the guide). |
| Setup and deployability | `docker compose up --build` starts Postgres (with a healthcheck), backend (migrates on start), worker, mock and frontend; named volumes keep the database and documents; `/health` (liveness) and `/health/ready` (database) exist; the worker stops on SIGTERM; deployment proposal in the README. | Containers run development servers; only Postgres has a Compose healthcheck; no production build. |
| Tests and development tooling | `pytest` in `backend/` (342 tests, real mock over HTTP, separate test database) and `mock_provider/` (125 contract tests); `ruff` on both services and `tsc` on the frontend; `evals.search` and `evals.assistant`. The booking and search tests use the real mock with failures forced through its control interface, so they can detect real failures. | No frontend or browser tests; no coverage target (as the guide says). |
| Search and assistant behavior | Search: `evals.search` (10 deterministic cases: filters, known offers, party-size quote, partial, empty, refused, supplier-down). Assistant: five read-only MCP tools, permissions enforced in each tool (`test_mcp.py`), a conversation loop with a step limit and failures passed through (`test_assistant.py`, scripted model), and `evals.assistant` for the real model (rule-based checks, JSON report, cost documented in the README). | The assistant evaluation was run once: 4 of 4 graded scenarios passed, 3 were not evaluated because the free daily limit was reached (see `docs/ai-usage.md`). No full pass rate yet. |

## What is and is not evidence for the assistant

- `test_mcp.py` checks the tool layer deterministically (tool list, authentication, permissions, parity with the REST responses).
- `test_assistant.py` uses a **scripted** model. It proves our loop, limits, error mapping and "writes nothing", not that a real model recommends well.
- `python -m evals.assistant` is the model-dependent evaluation (rules over tool calls and answer text, not opinions). It needs the developer's API key and cost is documented in the README. Its only recorded result is the partial single run in `docs/ai-usage.md`.

## Known limitations

- Test users only: no passwords, registration or invitations.
- The frontend has no automated tests and is checked manually; no browser end-to-end or load tests.
- Search takes one destination at a time; scheduling rules are simplified (no travel time or opening hours); USD only.
- One version per trip causes occasional false conflicts between unrelated edits.
- The booking provider is a mock; "booking" is simulated and cannot be cancelled or refunded (out of scope).
- Assistant: conversations are not saved on the server (only the last question and answer are kept in the browser session, per user and trip, and never sent as context); no streaming; free models have daily limits and answer inconsistently; tool results (test data) go to the configured model provider.
- The containers run development servers (see the deployment proposal in the README).
