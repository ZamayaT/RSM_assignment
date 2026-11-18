# Change 04 — Search

Status: Draft, awaiting developer approval

## Goal
A participant of a trip can search transport, accommodation, and activities through the provider mock (over HTTP only) and compare the results. The search clearly shows whether it was complete, partial (with a warning per failed supplier, keeping the successful results), empty, or failed, and never presents offers as booked or guaranteed. Covers FR-08 to FR-10 and the "Search" view.

## Scope
- Backend (`backend/`): provider HTTP client (configuration, timeouts, error mapping), search options endpoint, trip search endpoint with validation and defaults, search states, failure handling and logging.
- Frontend (`frontend/`): Search view reached from the trip overview, results table, search states, freshness and estimate labels.
- Tests for the search guarantees (including the partial-result guarantee against the real mock) and README updates.

## Out of scope
- "Add to itinerary" and everything that stores an offer (change 5); this step stores nothing about searches or offers.
- Refreshing a quote (`GET /offers/{id}`), bookings, idempotency, reconciliation (change 6).
- Caching, pagination, server-side sorting or filtering of results; the assistant and MCP (change 8).
- Frontend automated tests (documented limit in `PROJECT.md` section 11); the frontend is checked manually.
- The mock's `/control` endpoints are never used by the application; only the tests use them, to create failures.
- `assignment/` is read-only reference; the backend never reads it at runtime.

## Assumptions to confirm
- Configuration: the backend reads `PROVIDER_BASE_URL` and `PROVIDER_TOKEN` (already in `.env.example`) and a new `PROVIDER_TIMEOUT_SECONDS` (default 5). `httpx` (already in `requirements.txt`) is used at runtime; no new dependency.
- Endpoint: `POST /trips/{id}/search` with `{category, destination, origin?, startsOn?, endsOn?, travelers?, providerId?}`. It is a POST because it forwards a provider search, but it changes nothing. Any participant (including viewers) may search; non-participants get `404`.
- Defaults and validation: dates default to the trip dates and travelers to the trip travelers (applied by the backend). The destination must be one of the trip's destinations; `origin` is required for transport and ignored otherwise; dates must be a valid range; travelers 1–20. Errors are `400` with `details.fields`, like change 2.
- Options for the form come from `GET /search/options` (categories, origins `London`/`New York`/`Madrid`, suppliers `supplier-a/b/c`), so the frontend hardcodes nothing. Any logged-in user may call it.
- Search states returned with HTTP `200`: `complete` (offers, no warnings), `partial` (the provider reported `partial=true`; offers kept and one warning per failed supplier, even if the offer list is empty), `empty` (no offers, `partial=false`). Each result carries the provider's fields (id, supplier, title, description, destination, origin, start and end with offset, price as a two-decimal USD string, availability, revision, `validUntil`) plus the response's `searchedAt`.
- A **failed** search (all suppliers down, a rate-limited supplier, a timeout, the provider unreachable, or an unexpected provider response) returns the standard error body with a distinct code and a clear message: `503 PROVIDER_UNAVAILABLE`, `429 RATE_LIMITED` (with `Retry-After` when the provider sent it), `504 PROVIDER_TIMEOUT`, `502 PROVIDER_ERROR`. Provider details are logged with the request ids; the user never sees raw provider text.
- A provider `400` (for example an unknown supplier) is reported as `400` on the `providerId` field.
- No automatic retries: a search is cheap to repeat, and the user sees the failure and can retry. The wait is bounded by the timeout.
- Freshness: "searched at" and "quote valid until" are shown as the provider sent them; the UI does not decide whether a quote is expired (the provider clock can differ from the browser's). Results are labeled as estimates, not bookings or guaranteed prices.
- Comparison in the UI: the table can be sorted by price, start time, or supplier in the browser; unavailable offers are marked and listed.
- Search tests use the real mock over HTTP (`docker compose exec backend pytest` with the stack running) and reset it after each test; deterministic failures (timeouts, unreachable provider, malformed responses) use a stubbed HTTP transport.

## Tasks

### Provider client
- [x] 1.1 Settings (`PROVIDER_BASE_URL`, `PROVIDER_TOKEN`, `PROVIDER_TIMEOUT_SECONDS`) and a provider client module: search call with bearer token and timeout, typed result (offers, partial, warnings, searchedAt) and typed errors for 400, 429, 503, timeout, unreachable, and malformed responses.
- [x] 1.2 `GET /search/options` (categories, origins, suppliers) from one constants module.

### Search endpoint
- [x] 2.1 `POST /trips/{id}/search`: participant check (`404` otherwise), validation and defaults, call through the provider client, state `complete` / `partial` / `empty` with offers and per-supplier warnings.
- [x] 2.2 Failure mapping for the cases above (standard error body, codes and statuses as listed), provider request ids and timings logged.

### Frontend
- [x] 3.1 API calls, Search route `/trips/:id/search` and a "Search" link on the trip overview; form with category, destination (the trip's), origin (transport only), date window and travelers prefilled from the trip, optional supplier; per-field errors from the backend.
- [x] 3.2 Results and states: loading indicator, results table (title, supplier, schedule, price in USD, availability, restrictions text from the description, "searched at" and "quote valid until"), sorting, a permanent "estimates, not bookings" notice, partial warning per supplier with the results kept, empty message, failed message with a "Try again" action.

### Tests and documentation
- [x] 4.1 Provider client tests with a stubbed transport: success, `partial`, `400`, `429` with `Retry-After`, `503`, timeout, unreachable, malformed body.
- [x] 4.2 Search endpoint tests against the real mock: complete and empty results per category, defaults from the trip, unknown destination and missing origin (`400`), unknown supplier, partial result with one supplier down (offers kept, warning present), all suppliers down (`503`), rate limited (`429`), viewer allowed, non-participant `404`, no login `401`, mock reset after each test.
- [x] 4.3 Update `README.md`: how to run a search in the browser, how to try a partial and a failed search with the mock's control commands (copy-paste), and that the search tests need the mock running (only what is implemented).

## Acceptance criteria
- In the browser: open a trip, click Search, search accommodation for one of its destinations and see offers with price, schedule, availability, "searched at", "quote valid until", and the "estimates" notice; sort the table.
- Transport search asks for an origin; a destination outside the trip cannot be chosen, and a forced invalid request is refused with a message next to the field.
- With one supplier made unavailable in the mock: the page shows the remaining results and a warning naming the failed supplier. With all suppliers of the category down: a clear failed message and "Try again". With no matches: an empty message.
- A viewer can search; a user who is not on the trip cannot reach the trip's search (`404`).
- A slow or unreachable provider never leaves the page waiting beyond the timeout.
- Every guarantee above is verified by tests run with `docker compose exec backend pytest`.
- `assignment/` is untouched.

## Technologies implemented
- `httpx` (already in `requirements.txt`): backend HTTP client for the provider search (`app/provider_client.py`).
