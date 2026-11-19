# Change 05 — Itinerary and budget

Status: Complete

> Note (change 07): the Itinerary and Budget views are now tabs of the trip workspace; the links and the budget summary of the trip overview live in its left info card and tab bar (see `07-frontend-redesign.md`). Behavior and permissions are unchanged.

## Goal
Editors can add search results to a trip's itinerary, remove items and arrange their order; every participant sees the items with their schedule, cost, status and warnings, and a budget view that compares the estimated total with the trip budget. Concurrent edits never silently discard saved changes, and the person whose change was refused sees why and can re-apply or discard it. Covers FR-11 to FR-16, FR-18 to FR-20 and the "Itinerary", "Budget" and conflict dialog views, plus the "Add to itinerary" action of the Search view.

## Scope
- Backend (`backend/`): itinerary items table (migration), add / list / remove / reorder endpoints, offer snapshot taken at add time, warnings (pure functions), budget calculation (pure `Decimal` functions) and endpoint, optimistic locking on the trip `version`.
- Frontend (`frontend/`): "Add to itinerary" on search results, Itinerary view (items, status labels, warnings, remove, reorder, scheduling rules text), Budget view, conflict dialog, links and a budget summary on the trip overview.
- Tests for the itinerary, warning, budget and concurrency guarantees, and README updates.

## Out of scope
- Refreshing a quote (`GET /offers/{id}` for an existing item), booking, booking statuses and "confirmed" prices (change 6). Until then every item is an estimate and the confirmed total is `0.00`.
- Manual items not coming from a search, editing item fields, notes per item, drag and drop (reordering uses up/down buttons).
- Travel time, opening hours and local-day logic (documented limit in `PROJECT.md` section 8.2).
- Documents (change 8), assistant and MCP (change 9).
- Frontend automated tests (documented limit in `PROJECT.md` section 11); the frontend is checked manually.
- The mock's `/control` endpoints are never used by the application; `assignment/` is read-only reference.

## Assumptions to confirm
- **Stored snapshot**: adding an item stores a copy of the offer (id, supplier, category, title, description, destination, origin, start and end with offset, travelers, price as `NUMERIC(12,2)` and currency, revision, availability, `validUntil`) plus who added it and when. Later changes at the provider never alter a stored item.
- **Add endpoint**: `POST /trips/{id}/itinerary` with `{offerId, version}`. The backend fetches the offer with `GET /offers/{id}` through the existing provider client and snapshots what the provider returns, so the client cannot invent offer data or prices. Provider failures use the same mapping and codes as change 4.
- **Add rules**: only organizer and editor (`403` for viewers, `404` for non-participants, as before). An unavailable offer is refused (`409 OFFER_UNAVAILABLE`); the same offer twice is refused (`409 ALREADY_IN_ITINERARY`); an offer for a destination that is not one of the trip's is refused (`400`).
- **Other endpoints**: `GET /trips/{id}/itinerary` (any participant): items with status and warnings plus the trip `version`. `DELETE /trips/{id}/itinerary/{itemId}?version=N` and `PUT /trips/{id}/itinerary/order` with `{itemIds, version}` (the complete new order; must contain exactly the current items, otherwise `400`). `GET /trips/{id}/budget` (any participant).
- **Ordering**: a new item is inserted at its chronological place (by start time); the user can then move items with up/down buttons. The stored order is what everyone sees.
- **Concurrency**: one `version` per trip, shared with the trip details (as decided in `PROJECT.md`). Every itinerary change sends the version it saw and succeeds only if it still matches, bumping the version in the same transaction; otherwise `409 VERSION_CONFLICT` with the latest trip and itinerary in `details.latest`. A trip form open at the same time can therefore conflict with an itinerary change (accepted false conflict). Removing an item that someone else already removed gives `404`, shown as "already removed".
- **Conflict dialog**: explains that someone else saved first, shows the latest itinerary next to a one-line description of the user's refused change, and offers **Re-apply** (send the same change again on the latest version; the server re-validates it) or **Discard** (load the latest). Nothing is reported as saved until the server confirmed it.
- **Status label** (this change): `estimate`, or `expired quote` when `validUntil` is in the past. The backend decides expiry on every read using its own UTC clock (the provider mock's clock may differ when it is shifted; documented in the README).
- **Warnings** (computed on read, never stored; per `PROJECT.md` section 8.2): schedule conflict (UTC time ranges overlap, end equal to start allowed; accommodation may overlap activities and transport, two accommodations conflict), missing schedule or price, expired quote, outside the trip dates (compared by UTC date), destination not among the trip's destinations (possible if the trip is edited later).
- **Budget**: item cost is the offer's total price as quoted for the party (not multiplied by travelers). The response lists item, category, amount and kind (`estimate`); totals estimated / confirmed / combined as two-decimal strings; trip budget; remaining (negative means over budget). Exact `Decimal` sums; rounding rule (half-up to cents, only relevant if a division ever appears) documented in the README and on the view. Expired items stay in the estimated total and are flagged.
- **Permissions**: read for any participant, writes for `can_edit` roles, using the existing helpers; viewers see the views without action buttons, and the backend rejects their requests.
- No new dependencies.

## Tasks

### Backend: data and rules
- [x] 1.1 Migration and model for itinerary items (offer snapshot columns, position, added by/at, unique offer per trip); `GET /trips/{id}/itinerary` returning items in stored order with the trip `version` (any participant).
- [x] 1.2 Pure warning and status functions (conflicts, missing information, expired quote, outside trip dates, destination not in trip) with unit tests.
- [x] 1.3 Pure budget calculation with `Decimal` (estimated, confirmed, combined, remaining) and `GET /trips/{id}/budget`, with unit tests.

### Backend: changes with locking
- [x] 2.1 Provider client: `GET /offers/{id}` call with the same error mapping as the search (typed result, typed errors, `404` for an unknown offer).
- [x] 2.2 `POST /trips/{id}/itinerary`: edit permission, version check, snapshot from the provider offer, chronological insertion, `OFFER_UNAVAILABLE` / `ALREADY_IN_ITINERARY` / destination checks, version bump in the same transaction.
- [x] 2.3 `DELETE /trips/{id}/itinerary/{itemId}` and `PUT /trips/{id}/itinerary/order`: edit permission, version check, order validation, version bump.
- [x] 2.4 Conflict response: `409 VERSION_CONFLICT` with the latest trip and itinerary for every itinerary write.

### Frontend
- [x] 3.1 API calls, "Add to itinerary" on each search result for organizer and editor (shows the server's answer: added, already added, unavailable, conflict), hidden for viewers.
- [x] 3.2 Itinerary view `/trips/:id/itinerary`: items in order with schedule, destination, cost, status label and warnings, remove, up/down reordering (hidden for viewers), the simplified scheduling rules explained, loading and error states, links from the trip overview and the search page.
- [x] 3.3 Conflict dialog for add, remove and reorder: explanation, latest itinerary next to the refused change, Re-apply and Discard.
- [x] 3.4 Budget view `/trips/:id/budget`: itemized table (item, category, amount, estimate), the three totals, comparison with the budget (remaining or over), rounding note; budget summary and itinerary warning count on the trip overview.

### Tests and documentation
- [x] 4.1 Itinerary endpoint tests against the real mock: add (snapshot stored, chronological position), unavailable offer, duplicate, destination outside the trip, remove, reorder (valid and invalid lists), persistence of order, snapshot unchanged after the mock changes the price.
- [x] 4.2 Permission tests: viewer `403` on every write and can read; editor can write; non-participant `404`; no login `401`; removed participant loses access immediately.
- [x] 4.3 Concurrency tests: two writers with the same version (second gets `409` with the latest state, nothing lost); add and trip edit racing; two simultaneous adds; version increases by one per change.
- [x] 4.4 Update `README.md`: how to build and arrange an itinerary, read the budget and see a conflict (two browser windows, two users), the scheduling and rounding rules (only what is implemented).

## Acceptance criteria
- In the browser: search accommodation, add an offer, see it in the Itinerary with schedule, cost, "estimate" label and no warnings; add an overlapping activity (allowed) and a second overlapping accommodation (conflict warning); move and remove items and see the order persist after a reload.
- The Budget view shows the itemized costs, the estimated total and how it compares with the trip budget (remaining or over).
- With the mock's clock advanced past an offer's `validUntil`, the item shows "expired quote" and a warning; changing a price in the mock does not change stored items.
- As `alice` and `carol` (editor) in two windows with the same itinerary open, both change it: the second save is refused with the conflict dialog showing the latest state, and **Re-apply** or **Discard** both work; no saved change is lost.
- A viewer sees the itinerary and budget without action buttons, and direct API writes with a viewer's token get `403`; a user not on the trip gets `404`.
- Every guarantee above is verified by tests run with `docker compose exec backend pytest`.
- `assignment/` is untouched.

## Technologies implemented
None: no new applications or dependencies were added in this change.
