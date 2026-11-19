# Provider mock

A mock of the external travel provider. It implements the contract in `assignment/openAPI.json` (five operations under `/v1`) with fixture data, persistent bookings, a controllable clock, and a `/control` interface to reproduce failures. The main application talks to it only over HTTP.

- Base URL (host): `http://localhost:4010` (inside Docker: `http://mock_provider:4010`)
- Interactive docs: http://localhost:4010/docs
- Data: PostgreSQL schema `mock_provider` (same server as the backend, separate migrations). Migrations run automatically when the container starts.
- Run its tests: `docker compose exec mock_provider pytest`

The commands below use `curl` in a POSIX shell (Git Bash, macOS, Linux). Define these once:

```bash
M=http://localhost:4010
T="Authorization: Bearer travel-demo-token"
J="Content-Type: application/json"
```

## Demo tokens

| Token | Caller |
|---|---|
| `travel-demo-token` | Main caller (the application) |
| `other-demo-token` | A second caller, to show that bookings, references and idempotency keys are scoped to the caller |

Send `Authorization: Bearer <token>` on every `/v1` request. `/control` and `/health` need no token.

## Fixtures

Defined in `mock_provider/app/fixtures.py`. They are loaded on startup when there are no offers, and again by `POST /control/reset`.

| What | Values |
|---|---|
| Destinations (case-insensitive) | `Lisbon`, `Paris`, `Rome` |
| Transport origins (case-insensitive) | `London`, `New York`, `Madrid` |
| Suppliers | `supplier-a` (transport, accommodation), `supplier-b` (transport, accommodation, activity), `supplier-c` (accommodation, activity) |
| Categories | `transport`, `accommodation`, `activity` |

- Each listing has one quote per party size: **1, 2 and 4 travelers**. A search matches the exact party size; when a listing has no quote for it, the smallest quote for a larger party is returned (3 travelers gets the 4-traveler offers; 5 or more gets nothing).
- Offer ids look like `rome-activity-supplier-b-1-p2` (`<destination>-<category>-[<origin>-]<supplier>[-<n>]-p<travelers>`).
- Prices are USD totals for the whole party and the whole segment, stay or activity. Accommodation is three nights; transport is one way.
- Dates are destination-local and start at least 21 days after the mock clock's "today". Offers carry the destination's timezone offset.
- Quote validity cycles through 30 minutes, 6 hours, 1 day and 3 days; every 11th offer is sold out (`available=false`). Revisions start at `r1`.

## Clock

All time-dependent rules use the mock clock: quote expiry, fixture dates, booking timestamps, pending resolution.

- **Real time** by default.
- **Configuration** (`.env`, then `docker compose up -d mock_provider`): `MOCK_CLOCK_FROZEN_AT=2030-01-15T09:00:00Z` freezes it; `MOCK_CLOCK_OFFSET_SECONDS=86400` shifts real time. A frozen instant wins over the offset.
- **At runtime** with `POST /control/clock` (see below). Runtime changes are lost on restart or `reset`.
- Fixture dates are generated relative to the clock when they are loaded; run `POST /control/reset` after changing the clock if you want fixtures relative to it.

## Control interface (outside the contract)

Not part of `/v1`. The application must not depend on it.

| Endpoint | Purpose |
|---|---|
| `GET /control/state` | Clock, supplier failure modes, latency, queued booking outcomes |
| `POST /control/reset` | Delete all bookings, references and idempotency records; reload fixtures; clear every setting below; clock back to its configured value |
| `POST /control/clock` | Body with exactly one of: `{"freeze":true}`, `{"frozenAt":"2030-01-15T09:00:00Z"}`, `{"offsetSeconds":3600}`, `{"advanceSeconds":3600}` (negative moves back), `{"realTime":true}` |
| `PUT /control/suppliers/{id}/failure` | `{"mode":"unavailable"\|"timeout"\|"rate_limited","retryAfterSeconds":2}` (`retryAfterSeconds` only matters for `rate_limited`) |
| `DELETE /control/suppliers/{id}/failure` | Remove the failure |
| `PUT /control/suppliers/{id}/latency` | `{"milliseconds":3000}` delays every request involving that supplier; `0` removes it (max 60000) |
| `POST /control/offers/{offerId}` | `{"price":"199.90"}`, `{"available":false}` and/or `{"restrictions":["Minimum age 18"]}`; a real change creates a new revision |
| `PUT /control/booking-outcomes` | `{"outcome":"confirmed"\|"failed"\|"pending","count":1}` queues the outcome of the next accepted bookings (empty queue means `confirmed`) |
| `DELETE /control/booking-outcomes` | Clear the queue |
| `POST /control/bookings/{id}/resolve` | `{"outcome":"confirmed"\|"failed"}` forces a pending booking to a terminal outcome |

Failure modes, latency and queued outcomes are held in memory: they reset when the mock restarts.

## Behavior notes

- **Pending bookings** resolve to `confirmed` when read, once `MOCK_PENDING_RESOLUTION_SECONDS` (default 30) of mock-clock time have passed since acceptance. Force another result with `/control/bookings/{id}/resolve` before that. Terminal outcomes never change; the database also refuses to change an accepted offer snapshot, the total, or a terminal outcome.
- **Failed bookings** carry `failure: {"code":"BOOKING_REJECTED","message":"..."}`.
- **Refreshing**: reading an expired quote (`GET /v1/offers/{id}` or search) gives it a `validUntil` one hour ahead and a new revision (`r1` to `r2`).

## Scenario recipes

Start each recipe from a clean state:

```bash
curl -s -X POST $M/control/reset
```

The booking recipes use the fixture offer `rome-activity-supplier-b-1-p2` (revision `r1`, price `107.64`). If a booking answers `OFFER_CHANGED` right after a reset, its 30-minute quote may have expired: read the offer with `curl -s $M/v1/offers/rome-activity-supplier-b-1-p2 -H "$T"` and use the revision it shows.

Reusable pieces:

```bash
SEARCH='{"category":"accommodation","destination":"Lisbon","startsOn":"2000-01-01","endsOn":"2100-01-01","travelers":2}'
BOOK='{"clientReference":"demo-1","offerId":"rome-activity-supplier-b-1-p2","expectedOfferRevision":"r1","expectedPrice":{"amount":"107.64","currency":"USD"}}'
```

### Complete search

```bash
curl -s -X POST $M/v1/offers/search -H "$T" -H "$J" -d "$SEARCH"
```

### Supplier down (partial result, then total failure)

```bash
curl -s -X PUT $M/control/suppliers/supplier-b/failure -H "$J" -d '{"mode":"unavailable"}'
curl -s -X POST $M/v1/offers/search -H "$T" -H "$J" -d "$SEARCH"   # 200, "partial": true, a warning for supplier-b
curl -s -X PUT $M/control/suppliers/supplier-a/failure -H "$J" -d '{"mode":"unavailable"}'
curl -s -X PUT $M/control/suppliers/supplier-c/failure -H "$J" -d '{"mode":"unavailable"}'
curl -s -i -X POST $M/v1/offers/search -H "$T" -H "$J" -d "$SEARCH"   # 503 PROVIDER_UNAVAILABLE
# revert
for s in supplier-a supplier-b supplier-c; do curl -s -X DELETE $M/control/suppliers/$s/failure; done
```

### Supplier timeout

Same as above with `{"mode":"timeout"}`: the search warning code is `PROVIDER_TIMEOUT`.

### Rate limit

```bash
curl -s -X PUT $M/control/suppliers/supplier-b/failure -H "$J" -d '{"mode":"rate_limited","retryAfterSeconds":5}'
SB='{"category":"accommodation","destination":"Lisbon","startsOn":"2000-01-01","endsOn":"2100-01-01","travelers":2,"providerId":"supplier-b"}'
curl -s -i -X POST $M/v1/offers/search -H "$T" -H "$J" -d "$SB"   # 429 RATE_LIMITED, Retry-After: 5
curl -s -X DELETE $M/control/suppliers/supplier-b/failure
```

### Slow response

```bash
curl -s -X PUT $M/control/suppliers/supplier-b/latency -H "$J" -d '{"milliseconds":3000}'
time curl -s $M/v1/offers/rome-activity-supplier-b-1-p2 -H "$T" > /dev/null   # about 3 seconds
curl -s -X PUT $M/control/suppliers/supplier-b/latency -H "$J" -d '{"milliseconds":0}'
```

To simulate a client that times out and cannot tell whether a booking was accepted, set the latency above the client's timeout, send the booking, then look it up with `GET /v1/bookings/by-reference/{clientReference}` or repeat the request with the same `Idempotency-Key`.

### Price change

```bash
curl -s -X POST $M/control/offers/rome-activity-supplier-b-1-p2 -H "$J" -d '{"price":"150.00"}'   # revision becomes r2
curl -s -i -X POST $M/v1/bookings -H "$T" -H "$J" -H "Idempotency-Key: price-1" -d "$BOOK"        # 409 OFFER_CHANGED
```

Booking again with `"expectedOfferRevision":"r2"` and `"amount":"150.00"` succeeds.

### Sold out

```bash
curl -s -X POST $M/control/offers/rome-activity-supplier-b-1-p2 -H "$J" -d '{"available":false}'
curl -s -i -X POST $M/v1/bookings -H "$T" -H "$J" -H "Idempotency-Key: soldout-1" -d "$BOOK"      # 409 OFFER_UNAVAILABLE
curl -s -X POST $M/control/offers/rome-activity-supplier-b-1-p2 -H "$J" -d '{"available":true}'   # restore
```

### Expired quote

```bash
curl -s -X POST $M/control/clock -H "$J" -d '{"advanceSeconds":259200}'                           # 3 days
curl -s -i -X POST $M/v1/bookings -H "$T" -H "$J" -H "Idempotency-Key: expired-1" -d "$BOOK"      # 409 OFFER_CHANGED
curl -s $M/v1/offers/rome-activity-supplier-b-1-p2 -H "$T"                                        # refreshed: new revision and validUntil
curl -s -X POST $M/control/clock -H "$J" -d '{"realTime":true}'
```

### Pending booking

```bash
curl -s -X PUT $M/control/booking-outcomes -H "$J" -d '{"outcome":"pending"}'
curl -s -X POST $M/v1/bookings -H "$T" -H "$J" -H "Idempotency-Key: pending-1" -d "$BOOK"          # 201, "status": "pending"
curl -s $M/v1/bookings/by-reference/demo-1 -H "$T"                                                # pending until 30 seconds pass
# resolve now instead of waiting (use the booking id from the response):
curl -s -X POST $M/control/bookings/BOOKING_ID/resolve -H "$J" -d '{"outcome":"failed"}'
```

### Failed booking

```bash
curl -s -X PUT $M/control/booking-outcomes -H "$J" -d '{"outcome":"failed"}'
curl -s -X POST $M/v1/bookings -H "$T" -H "$J" -H "Idempotency-Key: failed-1" -d "$BOOK"           # 201, "status": "failed", with "failure"
curl -s -X POST $M/v1/bookings -H "$T" -H "$J" -H "Idempotency-Key: failed-1" -d "$BOOK"           # 200, replayed as failed (no new booking)
```

### Idempotent replay and conflicts

```bash
curl -s -X POST $M/v1/bookings -H "$T" -H "$J" -H "Idempotency-Key: k-1" -d "$BOOK"               # 201
curl -s -X POST $M/v1/bookings -H "$T" -H "$J" -H "Idempotency-Key: k-1" -d "$BOOK"               # 200, same booking
curl -s -X POST $M/v1/bookings -H "$T" -H "$J" -H "Idempotency-Key: k-2" -d "$BOOK"               # 409 REFERENCE_CONFLICT
curl -s -X POST $M/v1/bookings -H "$T" -H "$J" -H "Idempotency-Key: k-1" \
  -d "${BOOK/demo-1/demo-2}"                                                                      # 409 IDEMPOTENCY_CONFLICT
```

### Persistence across a restart

```bash
curl -s -X POST $M/v1/bookings -H "$T" -H "$J" -H "Idempotency-Key: k-1" -d "$BOOK" > /dev/null
docker compose restart mock_provider
curl -s $M/v1/bookings/by-reference/demo-1 -H "$T"                                                # still there
curl -s -X POST $M/v1/bookings -H "$T" -H "$J" -H "Idempotency-Key: k-1" -d "$BOOK"               # 200 replay
```

`docker compose down -v` deletes the database volume (and so all of this); `POST /control/reset` clears only the mock's data.

## Contract ambiguities and the choices made

| Question | Choice |
|---|---|
| Quote has a stale revision and is also sold out: which 409? | `OFFER_UNAVAILABLE`. A sold-out offer also gets a new revision, and "no longer available" is the more useful answer. |
| `providerId` names a known supplier that does not offer the category | `200`, complete, no offers (only an unknown supplier is `400`). |
| Party size with no exact quote | The smallest quote for a larger party is returned for that listing. |
| Several suppliers queried and every one is rate-limited | `503 PROVIDER_UNAVAILABLE`; `429` is only for a single rate-limited supplier. |
| Meaning of the `timeout` failure mode | Reported like `unavailable` but with warning code `PROVIDER_TIMEOUT` in search. Use latency for a response that is actually slow. |
| Supplier failures vs. booking lookups and idempotent replays | Lookups and replays are pure reads of stored bookings and ignore supplier failures, so a caller can always reconcile. New bookings and offer reads obey them. |
| What does a pending booking become? | `confirmed`, lazily when read after the delay; or whatever the control interface forces. |
| `clientReference` uniqueness | Per caller, for the lifetime of the dataset (until a reset). |
| Idempotency key retention | Kept forever (the contract asks for at least seven days). |
| Search window | An offer matches when its whole span lies inside the window, using destination-local calendar days. |
| Refreshed quote lifetime | One hour of mock-clock time. |
| Optional `restrictions` on offers | Returned on every offer (also the offer copied into a booking), always as a list. Each fixture offer follows a fixed rule by category and id (see `RESTRICTIONS` in `app/fixtures.py`), and some offers state none (an empty list). A control change of the restrictions creates a new revision. |
| `/control` authentication | None; it is for local demonstration only. |
