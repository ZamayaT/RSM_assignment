# PROJECT.md — Travel Planning Platform

Sources: `assignment/candidate-guide.md`, `assignment/prd.md`, `assignment/openAPI.json`. This file is the working summary of the project; consult the sources only for exact wording.

Decision labels used in this document:
- **Confirmed (developer)**: decided by the developer.
- **Confirmed (recommended)**: proposed by Claude and confirmed by the developer.
- **Pending**: not final; do not implement as if decided.

---

## 1. Overview

A take-home assignment: a **web application where a group plans a trip** (destinations, dates, budget, itinerary), **searches travel options** (transport, accommodation, activities) from an external provider, makes **simulated bookings**, generates **downloadable PDF trip documents**, and uses a **read-only AI assistant** that recommends options through tools exposed via **MCP**.

The evaluation focuses on **backend engineering**: data integrity, concurrency, failure handling, permissions, and automated evidence (tests). The frontend only needs to let users complete the workflows and understand outcomes; visual polish is not evaluated.

## 2. Key concepts

**Booking domain**
- **Offer / quote**: a provider's proposal (e.g. "3-night hotel in Lisbon, 2 travelers, USD 420.00"). It is an *estimate*: not held, not guaranteed. Each quote has a `revision` (version) and a `validUntil` (expiry).
- **Booking**: committing to an offer. Provider statuses: `pending`, then `confirmed` or `failed`. Terminal statuses never reverse.
- **Idempotency**: repeating the same booking request (e.g. after a timeout) must not create a second booking. Implemented with an `Idempotency-Key` header and a `clientReference`.
- **Unknown outcome**: a *local* application state, not a provider status. A booking was sent and no response arrived; the application must **reconcile** by asking the provider for the real result.
- **Partial search**: several suppliers are queried and some fail. Successful results are shown together with warnings for the failed suppliers.
- **Price**: always the **total** for all travelers and the whole segment, stay, or activity (never per person or per night). USD only, decimal strings such as `"420.00"`.

**AI assistant**
- **MCP (Model Context Protocol)**: a standard way to expose "tools" to an AI model. The backend exposes read-only tools (e.g. `search_options`, `get_trip`); the assistant (an LLM) discovers and calls them; the backend runs them and returns real data.
- **Read-only**: the assistant inspects trips, searches, and recommends. It never edits the itinerary or requests bookings.
- **Grounded**: recommendations come from tool results, never from invented prices or availability.

**Development harness**
The assignment asks for the committed AI development setup (agent rules, prompts, workflow) and a short note on how AI was used and verified. The `claude/` folder is that harness: `CLAUDE.md` (rules), `PROJECT.md` (this file), `changes/` (one file per development step with its tasks).

## 3. Roles and permissions

| Role | Capabilities |
|---|---|
| **Organizer** | Creates the trip, manages participants and roles, plus all editor capabilities |
| **Editor** | Edits trip and itinerary, requests bookings, generates documents, plus all viewer capabilities |
| **Viewer** | Reads the trip, searches and compares options, uses the assistant, downloads documents |

- Any user can create a trip and becomes its organizer.
- Access is limited to trips the user belongs to; non-participants see nothing.
- Permissions are enforced on **every API request, status polling endpoint, and MCP tool**, not only by hiding UI controls.

## 4. Main views

Described from the organizer's standpoint (organizers see everything). Differences for other roles are noted at the end.

**4.1 User selection (start page)**
- List of seeded test users; clicking one logs in as that user (no password).
- The session token is kept in the browser; a "Switch user" action returns here.
- Purpose: quickly demonstrate different roles and permission behavior.

**4.2 My trips (home)**
- List of trips the user participates in, showing name, dates, destinations, and the user's role in each.
- "Create trip" button.

**4.3 Create / edit trip**
- Fields: name, one or more destinations (from the supported list), start and end dates, number of travelers, budget (USD), optional preferences/notes for the assistant.
- Validation errors are shown per field; nothing is reported as saved unless the save succeeded.
- Saving uses the trip version; a conflicting save shows the conflict dialog (see 4.7).

**4.4 Trip overview**
- Summary: dates, destinations, travelers, budget versus current total, remaining budget.
- Counters and alerts: itinerary warnings (conflicts, expired prices, missing information), bookings by status, latest document status.
- Navigation to the other trip views.

**4.5 Participants**
- Current participants with their role.
- Search existing users by public username; add as editor or viewer.
- Change a participant's role or remove them.

**4.6 Search**
- Inputs: category (transport, accommodation, activity), destination (one of the trip's destinations), origin (transport only), date window (defaults to trip dates), travelers (defaults to trip travelers), optional supplier.
- Results: title, supplier, schedule, price (USD), availability, restrictions, and freshness ("searched at", "quote valid until").
- Clear states: complete, partial (with a warning per failed supplier), empty, failed.
- Offers are labeled as estimates, never as booked or guaranteed.
- "Add to itinerary" on each result.

**4.7 Itinerary**
- Items in chronological order (manual reordering allowed), each with schedule, destination, cost, and a status label: estimate, expired quote, booking pending, confirmed, failed, unknown.
- Warnings per item: schedule conflict, missing information, expired quote, outside trip dates.
- Actions: remove, reorder, refresh price, book.
- Save feedback: "Saved" or an error. If another participant saved first, a **conflict dialog** explains it, shows the latest saved state next to the user's change, and lets the user re-apply or discard.
- A short explanation of the simplified scheduling rules is visible.

**4.8 Budget**
- Itemized table: item, category, amount, and whether it is an estimate or a confirmed booking price.
- Totals: estimated, confirmed, combined; comparison with the budget (remaining or over budget).
- Note on the rounding rule.

**4.9 Booking confirmation and bookings**
- Confirmation dialog (opened by "Book"): fetches the current quote, shows price, availability, and restrictions; if anything changed, highlights the difference and asks for explicit confirmation of the new terms.
- Bookings list: one row per booking attempt with its status (pending, confirmed, failed, unknown), accepted price, and timestamps.
- Actions depending on status: "Check again" (unknown or long pending), "Retry" or "Choose another offer" (failed), explanation of next steps when some items succeeded and others failed.

**4.10 Documents**
- "Generate document" button.
- History of all generated documents: who generated it, when, trip version, status (waiting, in progress, complete, failed).
- Download for completed documents; "Retry" for failed ones. Status updates automatically while the page is open and is restored after reload.

**4.11 Assistant**
- Chat panel tied to the current trip.
- Shows which tools were used and their results or failures, so recommendations can be checked.
- Permanent notice that the assistant is read-only: it recommends, the user performs changes.

**Other roles**
- **Editor**: same as organizer except the Participants view is read-only.
- **Viewer**: read-only everywhere; no create/edit, add/remove/reorder, book, or generate actions. Can search, use the assistant, view everything, and download documents. The backend rejects these actions even if called directly.

## 5. Functional requirements

IDs `FR-xx` map to PRD user stories (`US-xx`).

### Trips and sharing
- **FR-01 (US-01)** An organizer creates a trip with one or more destinations, dates, and a USD budget.
- **FR-02 (US-01)** Trip data persists across sessions and application restarts.
- **FR-03 (US-01)** Invalid or incomplete input returns actionable errors, never an apparent successful save.
- **FR-04 (US-02)** An organizer grants another participant viewer or editor access.
- **FR-05 (US-02)** Editors can plan; viewers cannot change the trip, request bookings, or start document generation.
- **FR-06 (US-02)** Participants read trip information and download available documents; non-participants have no access to the trip or its documents.
- **FR-07 (US-02)** Permissions are enforced on API requests, status subscriptions, and assistant tools.

### Search and compare
- **FR-08 (US-03)** Search transport, accommodation, and activities through the provider contract; show price, currency, schedule, availability, and restrictions.
- **FR-09 (US-03)** Distinguish complete, partial, empty, and failed searches; keep successful results when a supplier fails.
- **FR-10 (US-03)** Never present offers as confirmed bookings or guaranteed prices; show result freshness.

### Itinerary
- **FR-11 (US-04)** Editors add, remove, and arrange options; items show schedule and cost.
- **FR-12 (US-04)** Flag missing information, expired prices, and relevant schedule conflicts.
- **FR-13 (US-04)** Itinerary changes persist; simplified scheduling and travel rules are explained.

### Budget
- **FR-14 (US-05)** Itemized costs and a total in USD, compared with the budget.
- **FR-15 (US-05)** Distinguish estimates from confirmed booking prices.
- **FR-16 (US-05)** Documented, reproducible rounding rules.
- **FR-17 (US-05)** Confirmed booking prices remain understandable after provider prices change (stored accepted snapshot).

### Concurrent editing
- **FR-18 (US-06)** Concurrent edits never silently discard saved changes.
- **FR-19 (US-06)** Each participant can tell whether their change was saved; an affected participant can understand and resolve a conflict.
- **FR-20 (US-06)** Conflict handling preserves permissions and trip consistency.

### Booking
- **FR-21 (US-07)** Booking requires an explicit user action.
- **FR-22 (US-07)** Price and availability are checked before booking; changed terms require the user's confirmation.
- **FR-23 (US-07)** An unavailable option is never presented as booked.
- **FR-24 (US-07)** A booking retains the accepted offer and price.
- **FR-25 (US-08)** Booking outcomes distinguish pending, confirmed, failed, and locally unknown.
- **FR-26 (US-08)** Retrying the same booking intent does not create duplicate bookings.
- **FR-27 (US-08)** Unknown outcomes are reconciled through the provider contract; users can tell a failed request from an unresolved one.
- **FR-28 (US-08)** When some selections are booked and others fail, each outcome stays visible with explained next steps.
- **FR-29 (US-08)** Interrupted operations never erase confirmed bookings or silently turn uncertainty into success.

### Documents
- **FR-30 (US-09)** Editors generate a downloadable trip summary (itinerary, costs, booking statuses) without blocking the application.
- **FR-31 (US-09)** Generation status (waiting, in progress, complete, failed) is visible and restored after reload or reconnect.
- **FR-32 (US-09)** Interruptions or repeated requests never leave a missing or incomplete file presented as ready; failed generation can be retried.
- **FR-33 (US-10)** A document identifies the trip information and point in time it represents; later edits do not alter it.
- **FR-34 (US-10)** Authorized participants download completed documents; non-participants cannot.
- **FR-35 (US-10)** Mismatches between stored files and their references are detected or recovered; no document is falsely reported as ready.

### Assistant and MCP
- **FR-36 (US-11)** The assistant inspects the authorized trip and searches options through read-only MCP tools.
- **FR-37 (US-11)** Recommendations are grounded in retrieved data, explain their relation to dates, budget, preferences, and restrictions, flag gaps or conflicts, and state when nothing suitable exists.
- **FR-38 (US-11)** Tool failures and insufficient information are surfaced, not presented as success.
- **FR-39 (US-11)** The assistant is read-only for all roles.
- **FR-40 (US-12)** The application exposes read-only capabilities (option search, trip information) through MCP; the built-in assistant discovers and invokes them through MCP.
- **FR-41 (US-12)** MCP tool access is tied to the acting user's permissions; a trip identifier alone grants nothing.
- **FR-42 (US-12)** MCP exposes no itinerary modification or booking actions.

### Provider mock
- **FR-43** A mock of the supplied provider contract is implemented, and the application consumes it only over HTTP through its public contract.

## 6. Non-functional requirements

- Saved state survives normal restarts; records never imply success before the operation succeeded.
- Slow, unavailable, or rate-limited providers never leave the UI waiting indefinitely; there is always an understandable status.
- Long-running operations and partial failures are diagnosable (logs, request IDs) and recoverable within documented limits.
- Historical bookings and documents remain meaningful when external data changes (immutable snapshots).
- The client recovers its view of state after disconnects without depending on every notification arriving.
- Configuration is separated from code, with example configuration; startup is reproducible; readiness and shutdown behavior are defined.
- Automated tests provide evidence for the claimed guarantees; deterministic tests are separate from tests that need model access.

## 7. External provider mock

Summary of `openAPI.json`. The contract must stay **unchanged**. The application talks to the mock only over HTTP and never uses its database or control endpoints.

| Operation | Purpose |
|---|---|
| `POST /offers/search` | Search by category, destination (origin required for transport), date window `startsOn..endsOn`, travelers (1–20), optional `providerId`. Returns offers, `partial`, `warnings`, `searchedAt`. |
| `GET /offers/{offerId}` | Latest quote: price, availability, `revision`, `validUntil`. |
| `POST /bookings` | Create a booking. Header `Idempotency-Key`; body `clientReference`, `offerId`, `expectedOfferRevision`, `expectedPrice`. `201` new, `200` replay. |
| `GET /bookings/{bookingId}` | Booking state (visible only to its creator). |
| `GET /bookings/by-reference/{clientReference}` | Reconciliation after a lost response. |

Rules that drive the design:
- **Auth**: demo bearer token (e.g. `travel-demo-token`). Bookings, references, and idempotency keys are scoped to the caller.
- **Money**: USD, strings with two decimals; price is the total for the party and the whole item.
- **Search**: no `providerId` queries all suppliers of the category; unknown supplier returns 400; partial failure returns 200 with `partial=true` and warnings; all suppliers failing returns 503 (429 for a single rate-limited supplier); no matches returns 200 with an empty list and `partial=false`.
- **Booking checks** (new request, atomic): revision or price mismatch, or expired quote, returns `409 OFFER_CHANGED`; unavailable returns `409 OFFER_UNAVAILABLE`. Same key and same body returns the same booking (200, even if the quote has since expired). Same key with a different body returns `409 IDEMPOTENCY_CONFLICT`. A new key with an existing `clientReference` returns `409 REFERENCE_CONFLICT`. Concurrent identical requests create exactly one booking.
- **Persistence**: accepted bookings, references, and idempotency records survive restarts (keys retained at least seven days); a deliberate fixture reset may clear them. `clientReference` is unique for the mock dataset's lifetime.
- **Statuses**: `pending` then `confirmed` or `failed`; failed bookings include a `failure`; offer snapshot and totals are immutable.
- **Errors**: `{code, message, requestId}` with codes BAD_REQUEST, UNAUTHORIZED, NOT_FOUND, OFFER_CHANGED, OFFER_UNAVAILABLE, IDEMPOTENCY_CONFLICT, REFERENCE_CONFLICT, RATE_LIMITED (with `Retry-After`), PROVIDER_UNAVAILABLE.
- **Fixtures**: data for all three categories, enough suppliers to demonstrate partial results, and future dates or a controllable clock for reproducible expiry scenarios. Fixture location names must be documented.
- **Out of scope**: payments, cancellation, refunds, callbacks, token issuance.

## 8. Technical decisions

### 8.1 Summary

| Topic | Decision | Status |
|---|---|---|
| Backend | Python + FastAPI | Confirmed (developer) |
| Database | PostgreSQL | Confirmed (developer) |
| Provider mock | Python/FastAPI, separate process in the same repository | Confirmed (developer) |
| Architecture | Modular monolith, single repository | Confirmed (developer) |
| Money | Python `Decimal`, never floats | Confirmed (developer) |
| Document format | PDF | Confirmed (developer) |
| Scope | Required stories only, no extensions | Confirmed (developer) |
| Users and sharing | Creator becomes organizer; participants added by username search with editor or viewer role | Confirmed (developer) |
| Login | Start page lists seeded users; selecting one logs in | Confirmed (developer) |
| Testing | Reduced, prioritized scope (section 11) | Confirmed (developer) |
| Frontend | React + Vite with MUI (Material UI) components | Confirmed (developer) |
| MCP | Official Python `mcp` SDK, HTTP transport, mounted inside the backend | Confirmed (recommended) |
| Background jobs | PostgreSQL-backed job table + worker process | Confirmed (recommended) |
| Status updates | Polling | Confirmed (recommended) |
| Document storage | Local disk volume + metadata and checksum in PostgreSQL; ReportLab | Confirmed (recommended) |
| Packaging | Docker Compose | Confirmed (recommended) |
| Concurrency | Optimistic locking with a trip version number | Confirmed (recommended) |
| LLM provider | To be decided (section 13) | Pending |
| Build plan | Section 10 | Confirmed (developer) |

### 8.2 Details

**Frontend: React + Vite + MUI**
React keeps dynamic UI state (itinerary, conflicts, polling statuses) manageable; plain HTML/JS needs no build step but becomes error-prone with this many dynamic views. MUI (Material UI) provides the components (tables, forms, dialogs, alerts, chips for statuses) so no custom design work is needed; default theme with minimal customization.

**Login and test identities**
Seeded users (e.g. `alice`, `bob`, `carol`). The start page lists them; selecting one calls a login endpoint that returns a token for that user. No passwords or registration. The same users are searchable by username when adding participants.

**MCP: inside the backend, HTTP transport**
A mounted `/mcp` HTTP endpoint in the FastAPI app, implemented with the official Python `mcp` SDK, in its own module. It shares the database and the permission code, so access is enforced in one place, and it calls only read services, which makes "no modification or booking tools" easy to verify. A separate process was rejected: it would duplicate permission logic and add deployment effort. The README provides copy-paste terminal commands to run and inspect it.

**Assistant authentication**
The frontend sends the logged-in user's token with each chat message. The backend's assistant loop calls the MCP tools over HTTP forwarding that token as a bearer header. Each tool validates the token and checks trip membership. The LLM chooses only tool names and arguments (such as `trip_id`), never the user identity.

**Background jobs: PostgreSQL job table + worker**
"Generate document" inserts a `documents` row with status `waiting` and returns immediately. A worker process (same codebase, different entrypoint) claims rows with `SELECT ... FOR UPDATE SKIP LOCKED`, sets `in_progress`, renders the PDF, then sets `complete` or `failed`. Rows stuck `in_progress` beyond a timeout are reset to `waiting`, so restarts are recoverable. The same worker runs booking reconciliation. Rejected: FastAPI `BackgroundTasks` (lost on restart) and Celery/Redis (extra service with no benefit here).

**Status updates: polling**
The frontend polls status endpoints every 2–3 seconds while an operation is active. State always comes from the database, so reloads and disconnects recover naturally, and permission checks are ordinary requests. WebSockets push instantly but need reconnect logic and a fetch-current-state fallback anyway.

**Document storage and snapshots**
- Each generated PDF is kept (later edits must not alter existing documents, and files must be downloadable later).
- At request time the backend freezes a JSON **snapshot** of the trip (itinerary, costs, booking statuses) with the trip `version`, timestamp, and the generating user. The PDF is rendered from the snapshot and states "Generated at <time> by <user> from trip version N".
- Files are written to a temporary path and renamed when complete; PostgreSQL stores path, size, SHA-256 checksum, and status. Downloads verify existence and checksum; a mismatch marks the document as failed and allows regeneration.
- All generations are kept as history, visible to every participant.
- PDF library: ReportLab (pure Python). Storing bytes in PostgreSQL was rejected (bloats the database, hides the file/reference consistency handling).

**Packaging: Docker Compose**
One `docker-compose.yml` starts PostgreSQL, backend, worker, provider mock, and frontend with `docker compose up`, using persistent volumes for the database and documents. Requires Docker Desktop. Individual services can also be run from the terminal during development.

**Concurrency: optimistic locking**
Each trip has an integer `version`. Clients send the version they last saw; the server applies the change only if it still matches, then increments it. Otherwise it returns `409 Conflict` with the latest data, and the UI shows the conflict dialog. One version per trip (covering details and itinerary): simple and safe, at the cost of occasional false conflicts. Permissions are re-checked on every save.

**Money and rounding**
All amounts use `Decimal` with two fractional digits. Provider amounts are already two-decimal strings, so totals are exact sums; any division (not expected) rounds half-up to cents. Documented in the README and budget view.

**Mock dataset**
- Destinations: Lisbon, Paris, Rome. Transport origins: London, New York, Madrid.
- Three logical suppliers (`supplier-a`, `supplier-b`, `supplier-c`); each category is served by at least two, so partial results can be demonstrated in every category.
- A few offers per destination and category, mixing availability, prices, and quote expiries.
- Dates relative to the mock's clock, which can be frozen or advanced through configuration.
- Failure switches through mock-only control endpoints or configuration (never used by the application): supplier timeout, rate limit, price change, sold out, booking left pending, slow response.

**Scheduling rules (simplified)**
- Item times are compared as UTC instants (offers carry timezone offsets).
- Conflict: two items whose time ranges overlap (end equal to start is allowed). Accommodation may overlap activities and transport; two overlapping accommodations are a conflict.
- Other warnings: missing schedule or price, expired quote, item outside the trip dates, item destination not among the trip's destinations.
- Not modeled: travel time between places, opening hours, local-day logic.

**Multiple destinations**
Search takes one destination at a time, chosen from the trip's destinations; each itinerary item records its destination.

**Assistant preferences**
An optional free-text preferences/notes field on the trip (edited by organizer and editors, read by the assistant through `get_trip`), plus whatever the user writes in the chat.

**Quotes and refresh**
- Search results show search time and quote expiry.
- Itinerary items are marked expired locally once `validUntil` has passed.
- "Book" always calls `GET /offers/{id}` first and shows current terms for explicit confirmation; changed terms are highlighted. Only then is `POST /bookings` sent with the confirmed revision and price.
- Manual "refresh price" per itinerary item.

**Booking several items**
The provider books one offer per request. Each itinerary item gets its own booking attempt, identifiers, and status. There is no cross-item rollback: confirmed items stay confirmed while failed ones show next steps (retry, choose another offer, or leave out).

**Booking identifiers**
On confirmation, a local `booking_attempt` row (status `initiated`) with a generated UUID is saved **before** sending. `clientReference` = `trip-{tripId}-item-{itemId}-{shortUuid}`; `Idempotency-Key` = `booking-intent-{uuid}`. Retries of the same intent reuse both; a new user decision after a definite failure creates new ones.

**Unknown outcomes**
On timeout or connection loss during `POST /bookings`, the attempt becomes `unknown` and is reconciled automatically:
1. `GET /bookings/by-reference/{clientReference}`: if found, store the real status.
2. If 404, replay the same POST with the same key: the provider returns the existing booking (200), creates it (201), or rejects it (409, definitely not booked).
3. Retry with backoff for about 10 minutes, then show "Outcome unresolved" with a "Check again" action. Never mark failed or confirmed without provider evidence.

**Pending bookings**
The worker polls `GET /bookings/{id}` every ~10 seconds for the first 5 minutes, then every ~1 minute. After 30 minutes the UI shows "Taking longer than expected" while keeping the status pending. Intervals are configuration values.

## 9. Architecture

Modular monolith in one repository:

```
frontend/        React app
backend/         FastAPI app (API, MCP endpoint, domain modules)
  worker         same codebase, separate entrypoint (documents, booking reconciliation)
mock_provider/   separate FastAPI app implementing openAPI.json
postgres         application data (separate database/schema for the mock)
volume           generated PDFs
```

Backend modules:
- `auth`: test users, tokens, current-user dependency.
- `trips`: trips, participants, roles, permission checks (single source of truth for access).
- `itinerary`: items, ordering, warnings, versioning.
- `budget`: pure `Decimal` calculations.
- `providers`: HTTP client for the provider contract (timeouts, retries, error mapping); the only code that talks to the mock.
- `bookings`: attempts, idempotency, reconciliation.
- `documents`: snapshots, PDF rendering, storage, job queue, downloads.
- `assistant`: `LLMClient` interface and conversation loop.
- `mcp`: read-only tools; uses read services only and enforces the acting user's permissions.

Rules: dependencies point inward (API, then services, then repositories); `assistant` and `mcp` never import write services; all provider access goes through `providers`.

## 10. Build plan (Confirmed)

The PRD requires all 12 stories; there is no smaller official MVP. Each step is one `changes/` file and is built as a **vertical slice**: backend, its frontend view, and its tests together, so progress is visible in the browser at every step.

| # | Change | Backend | Frontend view |
|---|---|---|---|
| 0 | Project skeleton | Repo layout, Docker Compose, PostgreSQL, FastAPI health endpoint, config and `.env.example`, pytest setup | React + Vite + MUI shell with navigation |
| 1 | Provider mock | All contract endpoints, fixtures, persistence, clock, failure switches, contract tests | None (inspected via FastAPI's built-in `/docs` page) |
| 2 | Users and trips | Seeded users, login, trips CRUD, validation, versioning, persistence | User selection, My trips, Create/edit trip, Trip overview (basic) |
| 3 | Sharing and permissions | Participants, roles, permission enforcement and tests | Participants |
| 4 | Search | Provider client, search endpoint, partial/empty/failed handling | Search |
| 5 | Itinerary and budget | Items, ordering, warnings, budget calculations, conflict handling | Itinerary, Budget, conflict dialog |
| 6 | Bookings | Quote refresh, booking attempts, idempotency, reconciliation in worker | Booking confirmation, Bookings |
| 7 | Documents | Job table, worker, PDF, storage, checksum, history | Documents |
| 8 | MCP and assistant | MCP tools, `LLMClient`, assistant loop, evaluations | Assistant |
| 9 | Delivery | README, architecture note, demo walkthrough, AI usage note | Final consistency pass |

## 11. Testing strategy (reduced scope)

Not everything will be covered. Priorities, targeting the guarantees reviewers check:
1. **Budget and rounding**: unit tests for `Decimal` totals and estimate versus confirmed.
2. **Booking guarantees**: integration tests against the real mock: idempotent retry, `OFFER_CHANGED`, unavailable, lost response with reconciliation, `REFERENCE_CONFLICT`.
3. **Permissions**: viewers cannot edit, book, or generate; non-participants are denied, on REST and on MCP tools.
4. **Concurrency**: two saves based on the same version; the second receives 409 and nothing is lost.
5. **Document jobs**: status transitions, recovery of a stuck job, checksum mismatch detection.
6. **Search**: one supplier down produces `partial=true` with warnings.
7. **Assistant**: deterministic tests with a scripted LLM (only read-only tools, permissions enforced).

Skipped or minimal (documented as limits): frontend tests, browser end-to-end tests, load tests, broad edge-case coverage.

Tools: `pytest` with `httpx`, PostgreSQL test database through Compose. Model-dependent evaluations are a separate optional command requiring an API key or local model, with setup and cost documented; the default test run never needs a model.

## 12. Constraints, scope, and deliverables

**Constraints**
- Backend in Python or TypeScript (Python chosen); application tools for the assistant through MCP.
- Destinations, sample data, and travel rules may be limited if documented.
- USD only.
- Assumptions, unresolved questions, and unfinished requirements (with their impact) must be documented.

**Out of scope**: real payments, commercial reservations, cancellation, refunds, production identity or invitations, currency conversion, public cloud deployment, maps, live presence, real-time collaborative editing.

**Deliverables**
1. Repository with frontend, backend, provider mock, MCP layer, assistant integration, and tests.
2. The supplied `openAPI.json`, unchanged.
3. Sample data and instructions to reproduce mock behavior.
4. Everything needed to run the application, with example configuration.
5. README: setup, checks, tests, evaluations, proposed deployment approach.
6. Short architecture note: key decisions, alternatives, guarantees, known limitations.
7. Demo walkthrough: main workflow plus selected failure and concurrency scenarios.
8. Committed development harness (`claude/`) and a short AI usage and verification note.
9. Reproducible evaluations of search and assistant behavior, separating deterministic checks from model-dependent ones.

**Evaluation areas**: architecture and organization; persistence and integrity; calculations, freshness, and performance; communication and protocols (including MCP and recovery after disconnects); concurrency and background processing; integrations and failures; documents and storage; security, configuration, and diagnostics; setup and deployability; tests and tooling; search and assistant behavior. Extra layers, services, or polish earn no credit; demonstrable guarantees do. Reviewers may ask for a small change made with AI during the review.

## 13. Open questions

- **LLM provider (Pending).** The assignment supplies no API key. Until decided, everything is built as if a real model were used: an `LLMClient` interface configured by environment variables (`.env.example`), with MCP tools and the assistant loop fully working. Options: (1) scripted LLM for tests and demo, (2) free-tier hosted model or local model via Ollama, (3) reviewer supplies their own key. Possibly a question for the assignment authors. To be decided at change 8.
