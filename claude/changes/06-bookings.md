# Change 06 — Bookings

Status: Complete

> Note (change 07): the Bookings view is now the "Bookings" tab of the trip workspace; the booking counters are in its left info card (see `07-frontend-redesign.md`). Behavior and permissions are unchanged.

## Goal
An organizer or editor can book an itinerary item after seeing its current terms and explicitly confirming them. The booking never creates duplicates, even when the user retries or the response is lost; its outcome is always one of pending, confirmed, failed or unknown, and an unknown outcome is settled through the provider contract (never guessed). Confirmed bookings keep the accepted offer and price, feed the budget as confirmed costs, and stay visible with explained next steps when other items fail. Covers FR-21 to FR-29, FR-17 and the "Booking confirmation" and "Bookings" views, the item status labels and "refresh price" of the Itinerary view, and the first use of the background worker.

## Scope
- Backend (`backend/`): provider client calls for bookings, `booking_attempts` table (migration), quote and refresh endpoints, booking creation with idempotency, bookings list and "check again", budget and itinerary integration, and a worker entrypoint (new `worker` service in Docker Compose) that reconciles unknown outcomes and follows pending bookings.
- Frontend (`frontend/`): "Book" action and confirmation dialog on the Itinerary, Bookings view with automatic status updates, item status labels, "refresh price", confirmed costs in the Budget, booking counters on the trip overview.
- Tests for the booking guarantees against the real mock (including lost responses and the worker's reconciliation), and README updates.

## Out of scope
- Payments, cancellation, refunds, callbacks (outside the provider contract).
- A "book everything" button: each item is booked on its own; a mixed result is explained in the Bookings view.
- Changing or rebooking a confirmed item, editing item fields, notes.
- Documents (change 8; they will reuse the worker built here), assistant and MCP (change 9).
- Frontend automated tests (documented limit in `PROJECT.md` section 11); the frontend is checked manually.
- The mock's `/control` endpoints are never used by the application; only the tests use them. `assignment/` is read-only reference.

## Assumptions to confirm
- **Who and where**: organizer and editor book (`403` for viewers, `404` for non-participants); every participant can read bookings. Booking is per itinerary item: `POST /trips/{id}/bookings` with `{itemId, intentId, expectedRevision, expectedPrice}`.
- **Explicit confirmation of current terms**: `GET /trips/{id}/itinerary/{itemId}/quote` asks the provider (`GET /offers/{id}`) for the current price, availability, revision and `validUntil` and returns them next to the saved estimate, with what differs. The dialog shows both, highlights differences, and only its "Confirm booking" button sends the revision and price the user was shown. The backend never books on terms the user did not see.
- **Booking intent and identifiers** (as in `PROJECT.md` section 8.2): the dialog creates an `intentId` (UUID) when it opens. The backend saves a `booking_attempts` row with status `initiated` (generated `clientReference` = `trip-{tripId}-item-{itemId}-{shortUuid}` and `Idempotency-Key` = `booking-intent-{uuid}`) and commits it **before** calling `POST /bookings`. Repeating the same `intentId` returns the same attempt and never sends a second booking; a new decision after a definite failure uses a new `intentId`, reference and key.
- **One live attempt per item**: enforced by the database (a unique index over attempts in `initiated`, `pending`, `unknown` or `confirmed`). A second request while one is live gets `409 BOOKING_EXISTS` with the existing attempt. Two simultaneous requests create exactly one attempt and one provider booking.
- **Outcome mapping** (definite results are data, returned with `201` and the attempt):
  - `201`/`200` from the provider: `pending`, `confirmed` or `failed` (with the provider's failure code and message) exactly as reported; the accepted offer snapshot and total come from the provider's booking and never change.
  - `409 OFFER_CHANGED`, `409 OFFER_UNAVAILABLE` and `400`: `failed`. Nothing was booked; the message explains what changed.
  - Timeout, connection loss, `429`, `5xx`, a malformed response or any unexpected status: `unknown`, because we cannot prove the provider did not book. Never shown as failed or confirmed.
- **Reconciliation (worker)**: for an `unknown` attempt: (1) `GET /bookings/by-reference/{clientReference}`; found: store the real status. (2) `404`: replay the same `POST /bookings` with the same key and body; `201`/`200` stores the booking, `409 OFFER_CHANGED`/`OFFER_UNAVAILABLE` marks `failed` (definitely not booked). (3) Anything else: retry with growing waits (10 s, doubling, at most 60 s) for about 10 minutes, then flag the attempt **unresolved**: the status stays `unknown`, the UI says "Outcome unresolved" and offers "Check again". An `initiated` attempt older than a minute (the backend died after saving it) is treated as `unknown` and reconciled the same way.
- **Pending bookings (worker)**: `GET /bookings/{id}` every ~10 s for the first 5 minutes, then every ~1 minute; after 30 minutes the UI shows "Taking longer than expected" while the status stays `pending`. All intervals and windows are configuration values (`.env.example`).
- **Check again**: `POST /trips/{id}/bookings/{attemptId}/check` (organizer, editor) runs one reconcile or poll step immediately, within the provider timeout, and returns the attempt. It is a retry of the lookup, never a new booking.
- **Retry after failure**: the user opens the confirmation dialog again (fresh quote, new `intentId`). "Choose another offer" goes to Search; a failed item can be removed.
- **Booked items are protected**: an item with a live attempt cannot be removed or have its price refreshed (`409 ITEM_BOOKED`); the check and the booking lock the item row, so a removal and a booking cannot both succeed.
- **Trip version**: booking attempts and their status changes do not bump the trip `version` (like participants), so the worker's updates never cause false edit conflicts. Refreshing an item's price is an itinerary write and does (`POST /trips/{id}/itinerary/{itemId}/refresh` with `{version}`, same conflict handling as change 5).
- **Statuses and warnings**: an item's label becomes `estimate`, `expired quote`, `booking pending` (`initiated` or `pending`), `confirmed`, `failed` (latest attempt failed) or `unknown`. Items with a live booking no longer get the "expired quote" warning (their price is accepted). The warning rules for schedule and destination are unchanged.
- **Budget**: a confirmed booking counts as a confirmed cost at the accepted price from the provider's booking; every other item stays an estimate at its saved price (including pending and unknown ones, flagged with their status). Combined total and remaining use both; the provider's later price changes never alter a confirmed amount.
- **Worker**: a new `worker` service in Docker Compose runs the same backend image with another command (`python -m app.worker`). It claims due attempts with `SELECT ... FOR UPDATE SKIP LOCKED` and a `next_check_at` column, so a restart or a second worker never double-processes an attempt. No new dependencies.
- **Bookings tests need the mock**; the worker's loop is tested through its single-step function (no sleeping), with check intervals set to zero in the test settings.

## Tasks

### Provider client
- [x] 1.1 Booking calls in the provider client: create (with `Idempotency-Key`; `201` new, `200` replay), get by id, get by reference; typed results and typed errors for `OFFER_CHANGED`, `OFFER_UNAVAILABLE`, `REFERENCE_CONFLICT`, `IDEMPOTENCY_CONFLICT`, `404`, `429`, `503`, timeout, unreachable and malformed responses.

### Data and rules
- [x] 2.1 Migration and model for `booking_attempts` (ids, intent, reference, key, status, accepted snapshot and price, provider booking id and failure, check bookkeeping including `next_check_at` and the "unresolved" flag, requester, timestamps); unique `intentId` and `clientReference`; unique live attempt per item.
- [x] 2.2 Itinerary statuses and warnings with booking states (pure functions) and the budget with confirmed bookings at the accepted price; `GET /trips/{id}/itinerary` and `GET /trips/{id}/budget` return them.

### Quote, refresh and booking
- [x] 3.1 `GET /trips/{id}/itinerary/{itemId}/quote` (current terms next to the saved estimate, with the differences) and `POST /trips/{id}/itinerary/{itemId}/refresh` (versioned write that replaces the saved price, revision, availability and quote expiry; refused for booked items).
- [x] 3.2 `POST /trips/{id}/bookings`: permissions, one live attempt per item, `initiated` row committed before the provider call, outcome mapping, replay by `intentId`; booked items cannot be removed.
- [x] 3.3 `GET /trips/{id}/bookings` (attempts with status, accepted price, timestamps, flags "unresolved" and "taking longer than expected", counters by status) and `POST /trips/{id}/bookings/{attemptId}/check`.

### Worker
- [x] 4.1 Settings for the intervals and windows, worker entrypoint with the claim-due-attempts step, and the `worker` service in Docker Compose and `.env.example`.
- [x] 4.2 Reconciliation of `unknown` and stuck `initiated` attempts (by reference, then replay, then backoff, then unresolved) and polling of `pending` attempts; one function per step, shared with "check again".

### Frontend
- [x] 5.1 API calls, "Book" on each itinerary item for organizer and editor, and the confirmation dialog: current quote, saved estimate, highlighted differences, availability, explicit "Confirm booking" that sends the shown terms; unavailable offers cannot be confirmed.
- [x] 5.2 Bookings view `/trips/:id/bookings`: one row per attempt with status, accepted price and timestamps; polling every ~3 s while any attempt is live, restored after reload; "Check again", "Retry", "Choose another offer", "Outcome unresolved" and "Taking longer than expected" messages; a summary that explains next steps when some items succeeded and others failed.
- [x] 5.3 Itinerary status labels and "Refresh price" (with the conflict dialog from change 5), confirmed costs in the Budget view, booking counters and a link on the trip overview.

### Tests and documentation
- [x] 6.1 Booking flow tests against the mock: confirmed, pending then confirmed, mock-forced failed, price changed (`OFFER_CHANGED`), sold out, expired quote, accepted price kept after the mock changes the price, budget with a confirmed item.
- [x] 6.2 Idempotency and recovery tests: same `intentId` twice creates one provider booking, a lost response (slow provider, short timeout) becomes `unknown` and is reconciled to the real status by reference, a missing booking is replayed with the same key, an unreachable provider ends as unresolved and is never marked failed or confirmed, a stuck `initiated` attempt is recovered, a pending booking is polled to its final status, and a restart does not lose or duplicate attempts.
- [x] 6.3 Permission and concurrency tests: viewer `403`, non-participant `404`, no login `401`, two simultaneous booking requests for one item create one attempt and one provider booking, a booked item cannot be removed or refreshed, a removal and a booking racing never both succeed.
- [x] 6.4 Update `README.md`: how to book and read the Bookings view, the `worker` service, how to try a price change, a sold-out offer, a pending booking and a lost response with the mock's control commands (copy-paste), that the booking tests need the mock running, and to run `docker compose down` when finished (only what is implemented).

## Acceptance criteria
- In the browser: add an item to the itinerary and click **Book**; the dialog shows the current terms and the saved estimate, and nothing is booked until **Confirm booking**; the item then shows its status and the Bookings view lists the attempt with its accepted price.
- With the price changed in the mock before confirming, the dialog highlights the difference and asks for confirmation of the new terms; a booking sent on stale terms is recorded as failed and explained, and nothing is booked.
- With a sold-out offer, booking is refused with a clear message and the item is never shown as booked.
- With a pending booking the Bookings view updates by itself until it is confirmed or failed, including after a page reload.
- With the provider slow enough to time out, the attempt shows as **unknown** (not failed, not confirmed), and once the provider answers again the worker settles it to the real status without a second booking; if the provider stays unreachable the view says "Outcome unresolved" and "Check again" works later.
- Clicking **Confirm booking** twice, or repeating the request, never creates a second booking.
- With one item confirmed and another failed, each outcome stays visible with next steps; the budget shows the confirmed cost at the accepted price, and a later price change in the mock does not alter it.
- A viewer sees bookings without "Book", "Check again" or "Retry"; direct API calls with a viewer's token get `403`, and a user not on the trip gets `404`.
- Every guarantee above is verified by tests run with `docker compose exec backend pytest`.
- `assignment/` is untouched.

## Technologies implemented
- **`worker` service (Docker Compose)**: runs the backend image with `python -m app.worker`; settles unknown booking outcomes and follows pending bookings in the background. No new Python or npm dependencies were added.
