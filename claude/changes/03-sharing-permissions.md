# Change 03 — Sharing and permissions

Status: Approved

## Goal
An organizer can add other users to a trip as editor or viewer, change their role, and remove them. The role of each participant is enforced by the backend on every trip request, and the Participants view shows it in the browser. Covers FR-04 to FR-07 for the endpoints that exist so far (trips); later changes reuse the same permission helpers.

## Scope
- Backend (`backend/`): user search by username, list/add/change/remove participants, central permission helpers in the trips module, `403` for actions the role does not allow.
- Frontend (`frontend/`): Participants view (organizer: manage; editor and viewer: read-only), link from the trip overview, handling of lost access.
- Tests for the permission guarantees and README updates.

## Out of scope
- Invitations, acceptance, notifications, e-mail (the assignment excludes invitations; adding is immediate).
- Transferring the organizer role, a second organizer, leaving a trip, deleting trips.
- Permission checks for itinerary, bookings, documents, status polling, and MCP tools: those features do not exist yet and each later change applies the helpers written here (and tests them).
- Frontend automated tests (documented limit in `PROJECT.md` section 11); the frontend is checked manually.
- Any use of the provider mock.

## Assumptions to confirm
- Participant endpoints:
  - `GET /users?query=<text>`: logged-in users search by username (case-insensitive, contains), at most 10 results, returning `id`, `username`, `displayName` only.
  - `GET /trips/{id}/participants`: any participant of the trip.
  - `POST /trips/{id}/participants` with `{username, role}`: organizer only; `role` is `editor` or `viewer`.
  - `PUT /trips/{id}/participants/{userId}` with `{role}`: organizer only; `DELETE /trips/{id}/participants/{userId}`: organizer only.
- Exactly one organizer per trip, always the creator: the organizer's role cannot be changed, and the organizer cannot be removed (`400`).
- Permissions in one place, in the trips module: `can_read` (any participant), `can_edit` (organizer, editor; already exists), `can_manage_participants` (organizer). Other roles' capabilities are added by the changes that introduce them.
- Error rules: not a participant → `404` (as in change 2, existence is not revealed, including for the participants endpoints); participant without the needed role → `403 FORBIDDEN`; unknown username → `400` with `details.fields.username`; user already on the trip → `409 ALREADY_PARTICIPANT`; participant id not on the trip → `404`.
- Role and membership changes take effect on the next request (checked in the database every time, no cached roles). A removed user gets `404` on the trip; a user downgraded to viewer gets `403` on `PUT /trips/{id}`.
- Participant changes do not change the trip `version` (they are not part of the trip form, so they cannot cause an edit conflict).
- Viewers and editors see the Participants view read-only; the "Edit" link on the overview already hides for viewers.

## Tasks

### Permissions
- [x] 1.1 Permission helpers in the trips module (`can_read`, `can_edit`, `can_manage_participants`) and a single way to load the trip with the caller's role; `PUT /trips/{id}` uses them (no behavior change).

### Participants API
- [x] 2.1 `GET /users?query=` (authenticated username search, limited results, public fields only).
- [x] 2.2 `GET /trips/{id}/participants` (user, role) for any participant; `404` for non-participants.
- [x] 2.3 `POST /trips/{id}/participants`: organizer only; validates role and username; `409` when already a participant.
- [x] 2.4 `PUT /trips/{id}/participants/{userId}` and `DELETE /trips/{id}/participants/{userId}`: organizer only; the organizer row is protected.

### Frontend
- [ ] 3.1 API client calls, Participants route (`/trips/:id/participants`), read-only list of participants with roles, and a "Participants" link on the trip overview.
- [ ] 3.2 Organizer controls: search users by username, add as editor or viewer, change role, remove; errors shown next to the field or as a message; changes appear only after the server confirmed them.
- [ ] 3.3 Role-aware behavior: controls hidden for editors and viewers; a clear message when access was lost (`404`) or the action is no longer allowed (`403`), with a link back to My trips.

### Tests and documentation
- [ ] 4.1 Participants tests: list, add (editor/viewer), duplicate `409`, unknown user `400`, invalid role `400`, change role, remove, organizer protected, user search (auth required, limit, public fields only).
- [ ] 4.2 Permission tests: viewer `403` on `PUT /trips/{id}` and on all participant changes; editor can edit the trip but gets `403` on participant changes; non-participant `404` on trip and participant endpoints; role changes and removal take effect immediately; a removed user no longer lists the trip.
- [ ] 4.3 Update `README.md`: how to share a trip and try the roles with the seeded users (only what is implemented).

## Acceptance criteria
- In the browser: as `alice` create a trip, add `bob` as viewer and `carol` as editor; as `bob` see the trip in My trips, open it, and find no way to edit or manage participants; as `carol` edit the trip but see the participants read-only; as `alice` change `bob` to editor and remove `carol`; `carol` no longer sees the trip.
- Calling the API directly with a viewer's or editor's token is rejected with `403` for what the role does not allow, and with `404` for a non-participant.
- Every guarantee above is verified by tests run with `docker compose exec backend pytest`.
- `assignment/` is untouched.

## Technologies implemented
(To be filled as tasks are completed.)
