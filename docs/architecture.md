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

## What is and is not evidence for the assistant

- `test_mcp.py` checks the tool layer deterministically (tool list, authentication, permissions, parity with the REST responses).
- `test_assistant.py` uses a **scripted** model. It proves our loop, limits, error mapping and "writes nothing", not that a real model recommends well.
- `python -m evals.assistant` is the model-dependent evaluation (rules over tool calls and answer text, not opinions). It needs the developer's API key, cost is documented in the README, and no result from it is claimed in this repository.

## Known limitations

- Test users only: no passwords, registration or invitations.
- The frontend has no automated tests and is checked manually; no browser end-to-end or load tests.
- Search takes one destination at a time; scheduling rules are simplified (no travel time or opening hours); USD only.
- One version per trip causes occasional false conflicts between unrelated edits.
- The booking provider is a mock; "booking" is simulated and cannot be cancelled or refunded (out of scope).
- Assistant: the chat is not saved (cleared on reload); no streaming; free models have daily limits and answer inconsistently; tool results (test data) go to the configured model provider.
- The containers run development servers (see the deployment proposal in the README).
