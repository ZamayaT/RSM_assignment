# Change 01 — Provider mock

Status: Complete

## Goal
A working mock of the external travel provider that implements `assignment/openAPI.json` exactly, with fixture data, persistent bookings, and reproducible failure scenarios. The main application will later consume it only over HTTP.

## Scope
- All five contract operations under `/v1`, with the behavior rules of the contract (see `claude/PROJECT.md` section 7).
- Fixture data: 3 destinations, 3 transport origins, 3 suppliers, all three categories, at least two suppliers per category.
- A controllable clock so quote expiry is reproducible.
- Persistence in PostgreSQL: bookings, references, idempotency records survive restarts.
- A control interface **outside** the contract (`/control/...`) to trigger failure scenarios and reset data.
- Contract-level automated tests and a mock-specific README.

## Out of scope
- Any use of the mock by the backend or frontend (later changes).
- Payments, cancellation, refunds, callbacks, token issuance.
- Modifying `openAPI.json` (it stays unchanged; ambiguities are documented in the mock README).
- A UI for the mock (FastAPI's `/docs` is enough).
- `assignment/` is read-only reference material: it is never copied, modified, or read by the mock at runtime.

## Assumptions to confirm
- The mock stores its data in the same PostgreSQL server, in its own schema `mock_provider`, with its own Alembic migrations (independent from the backend's).
- Demo tokens: `travel-demo-token` (main caller) and `other-demo-token` (a second caller, to demonstrate booking visibility scoping). The token string identifies the caller.
- A pending booking resolves lazily when read, after a configurable delay measured by the mock clock; the control interface can force the outcome.
- Fixtures are seeded on startup when the tables are empty, and re-seeded by the control `reset`.
- Response shapes are verified with typed Pydantic models and tests; no extra schema-validation tool is added.

## Tasks

### Persistence and configuration
- [x] 1.1 Mock settings from environment variables; PostgreSQL connection with schema `mock_provider`; Alembic initialized; `pytest` configured; `mock_provider` service in `docker-compose.yml` gets the database variables and waits for a healthy PostgreSQL.
- [x] 1.2 Tables and first migration: offers (current quote fields, revision, availability, validity), bookings (immutable offer snapshot, status, timestamps, failure), idempotency records (caller, key, request fingerprint, booking), unique constraints for (caller, key) and (caller, clientReference).

### Clock and fixtures
- [x] 2.1 Controllable clock: real time by default, optionally frozen or offset through configuration; every time-dependent rule uses it.
- [x] 2.2 Fixture data: destinations Lisbon, Paris, Rome; origins London, New York, Madrid; suppliers `supplier-alamo`, `supplier-boots`, `supplier-croc`; a few offers per destination and category with varied prices, availability, and quote expiries; dates relative to the clock; seeded on startup when empty.

### Cross-cutting API behavior
- [x] 3.1 Bearer-token authentication (demo tokens above); `401 UNAUTHORIZED` in the contract's error format with a `requestId`.
- [x] 3.2 Request validation errors mapped to `400 BAD_REQUEST` in the contract's error format.

### Offers
- [x] 4.1 `POST /v1/offers/search`: validate input (origin required for transport, `startsOn <= endsOn`, travelers 1–20), case-insensitive matching, offers fit the party and date window (an exact party-size quote is preferred; when a listing has none, its smallest larger-party quote is returned instead, e.g. a search for 3 returns the 4-traveler offers; no larger quote means no offer), `providerId` handling (unknown supplier returns 400), complete/partial/empty results, `503` when no queried supplier succeeds and `429` for a rate-limited single-supplier query.
- [x] 4.2 `GET /v1/offers/{offerId}`: current quote; expired quotes refreshed with a future `validUntil` and a new `revision`; unavailable offers returned with `available=false`; `404` for unknown ids.

### Bookings
- [x] 5.1 `POST /v1/bookings` for a new request: atomically check revision, price, `validUntil`, and availability; `201` on acceptance; `409 OFFER_CHANGED` and `409 OFFER_UNAVAILABLE` create nothing; `404` for unknown offers.
- [x] 5.2 Idempotency: same key and same semantic body returns the same booking with `200` (even after the quote expired or changed); same key with a different body returns `409 IDEMPOTENCY_CONFLICT` (property order is irrelevant); new key with an existing `clientReference` returns `409 REFERENCE_CONFLICT`; concurrent identical requests create exactly one booking.
- [x] 5.3 `GET /v1/bookings/{bookingId}` and `GET /v1/bookings/by-reference/{clientReference}`, visible only to the creating caller (`404` otherwise).
- [x] 5.4 Booking lifecycle: accepted bookings are `confirmed`, `failed` (with a `failure`), or `pending` then resolved to a terminal status; terminal statuses never reverse; offer snapshot and total are immutable; only status and `updatedAt` change.

### Control interface (outside the contract)
- [x] 6.1 `/control` endpoints, not part of `/v1`: reset data and re-seed; set or advance the clock; per-supplier failure mode (`unavailable`, `timeout`, `rate_limited` with `Retry-After`) and artificial latency; change an offer's price or availability (new revision); choose the outcome of the next bookings (`confirmed`, `failed`, `pending`) and force a pending booking to resolve.

### Tests and documentation
- [x] 7.1 Search tests: complete, partial with warnings, empty, all suppliers failing (503), single-supplier rate limit (429), unknown supplier (400), invalid input (400), unauthorized (401).
- [x] 7.2 Booking tests: each rule of tasks 5.1–5.4, concurrent identical requests, caller scoping, and persistence of bookings across a mock restart.
- [x] 7.3 `mock_provider/README.md`: fixture locations and suppliers, demo tokens, clock usage, every control endpoint, and a copy-paste recipe for each failure scenario; plus any contract ambiguities found and the choice made.
- [x] 7.4 Update the root `README.md` with the command to run the mock tests and a pointer to `mock_provider/README.md` (only what is implemented).

## Acceptance criteria
- Every operation behaves as the contract describes, verified by automated tests that run with `docker compose exec mock_provider pytest`.
- A booking and its idempotency data are still available after restarting the mock container; `docker compose down -v` clears them.
- Each failure scenario (supplier down, timeout, rate limit, price change, sold out, pending booking, slow response) can be triggered and reverted through the control interface with documented commands.
- Fixture dates are in the future relative to the mock clock, and expiry scenarios are reproducible by moving the clock.
- `assignment/openAPI.json` is unchanged and the mock does not read it at runtime.

## Technologies implemented
- pydantic-settings: mock configuration from environment variables (`mock_provider/app/config.py`).
- SQLAlchemy 2 + psycopg 3: ORM models and PostgreSQL access for the mock's `mock_provider` schema.
- Alembic: the mock's own migrations (run on container start), independent from the backend's.
- pytest + httpx: mock test suite (`docker compose exec mock_provider pytest`); httpx backs the FastAPI test client used by the API tests.
