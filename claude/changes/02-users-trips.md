# Change 02 — Users and trips

Status: Approved

## Goal
Seeded test users who can "log in" by selecting a name, and trips that a logged-in user can create, list, view, and edit, with validation, versioning (optimistic locking), and persistence. First visible vertical slice: backend, its frontend views, and tests together.

## Scope
- Backend (`backend/`): seeded users, login by username, current-user dependency, trips with participants (the creator becomes organizer), trip versioning, consistent error format.
- Frontend (`frontend/`): user selection (start page), My trips, create/edit trip, basic trip overview, "Switch user".
- Tests for the backend guarantees of this step and README updates.

## Out of scope
- Adding or changing participants, roles other than organizer, viewer/editor behavior (change 3). Only the organizer row exists after this change; the permission check is written so change 3 can extend it.
- Itinerary, budget totals, search, bookings, documents, assistant, MCP.
- Deleting trips, passwords, registration, token expiry.
- The full conflict dialog with side-by-side comparison (change 5): here a version conflict shows a clear message and lets the user reload the latest data.
- Frontend automated tests (documented limit in `PROJECT.md` section 11); the frontend is checked manually.
- Any use of the provider mock (change 4 onward).

## Assumptions to confirm
- Seeded users: `alice`, `bob`, `carol` (username unique, plus a display name), created on startup when the table is empty.
- Login = `POST /auth/login` with a username; it returns a random opaque token stored in the database (survives restarts, can be revoked later). The token is sent as `Authorization: Bearer <token>`. No expiry in this change.
- Supported destinations are the mock's: Lisbon, Paris, Rome, exposed by `GET /destinations` so the frontend never hardcodes them.
- A trip has: name (1–120 chars), one or more destinations from the supported list, start and end date (end not before start), travelers 1–20, budget in USD (decimal string with two fractional digits, not negative), optional preferences/notes, an integer `version` starting at 1, timestamps.
- `PUT /trips/{id}` requires the `version` the client last saw; if it no longer matches, the server returns `409` with the latest trip and changes nothing. The check and the update are one atomic statement.
- Users see only trips they participate in; any other trip id returns `404` (not `403`), so existence is not revealed.
- Errors use one JSON shape: `{code, message, requestId, details}` with per-field messages in `details.fields` for validation errors (`400`), plus `401`, `404`, `409`.
- Backend tables live in the default schema with Alembic migrations run when the backend container starts (as the mock does).
- The frontend session token is kept in `localStorage`; routing uses `react-router-dom` so views survive a page reload (the only new frontend dependency).

## Tasks

### Persistence and seed data
- [x] 1.1 Tables and first migration: users, auth tokens, trips (with `version`), trip participants (trip, user, role); backend container runs `alembic upgrade head` on start.
- [x] 1.2 Seed users on startup when empty (idempotent); supported destinations list and `GET /destinations`.

### Authentication and errors
- [x] 2.1 `GET /auth/users` (public list), `POST /auth/login`, `GET /auth/me`, and the current-user dependency (`401` when the token is missing or unknown).
- [x] 2.2 Error format for all errors and mapping of validation errors to `400` with per-field `details.fields`.

### Trips
- [ ] 3.1 `POST /trips`: validate input; create the trip and its organizer participant in one transaction; version 1; money kept as `Decimal`.
- [ ] 3.2 `GET /trips` (the user's trips with their role) and `GET /trips/{id}` (participants only, otherwise `404`).
- [ ] 3.3 `PUT /trips/{id}` with optimistic locking on `version` (`409` with the latest trip on mismatch; version incremented on success); permission helper in the trips module that allows organizer and editor to edit.

### Frontend
- [ ] 4.1 API client and session: base URL from configuration, bearer token from `localStorage`, error handling (`401` returns to user selection); add `react-router-dom` and the route structure.
- [ ] 4.2 User selection start page (list of seeded users, click to log in) and a "Switch user" action in the app bar.
- [ ] 4.3 My trips: list with name, dates, destinations, and the user's role; "Create trip" button; empty state.
- [ ] 4.4 Create/edit trip form: all fields, per-field validation errors from the backend, success only after the save succeeded, version-conflict message with a "reload latest" action.
- [ ] 4.5 Basic trip overview: dates, destinations, travelers, budget, notes, role, "Edit" link (the form loads the latest version).

### Tests and documentation
- [ ] 5.1 Auth and trip tests: login, `401`, validation errors (each field), create/list/get, only-my-trips visibility, `404` for non-participants, money exactness.
- [ ] 5.2 Versioning and persistence tests: successful update increments the version, stale update gets `409` and loses nothing, two concurrent saves from the same version (exactly one succeeds), trips survive an engine restart.
- [ ] 5.3 Update `README.md`: seeded users, how to log in from the browser, how to run the tests, and `GET /docs` pointer (only what is implemented).

## Acceptance criteria
- In the browser at http://localhost:5173: choose a seeded user, create a trip, see it in My trips, open its overview, edit it, switch to another user and not see it.
- Invalid trip input shows an error next to each wrong field and nothing is reported as saved.
- Two edits from the same version: the second shows the conflict message and the first user's changes are intact.
- Trips and logins still work after `docker compose restart backend`; `docker compose down -v` clears them.
- Every backend guarantee above is verified by tests run with `docker compose exec backend pytest`.
- `assignment/` is untouched.

## Technologies implemented
(To be filled as tasks are completed.)
