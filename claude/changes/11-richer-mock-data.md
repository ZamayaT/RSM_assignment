# Change 11 — Richer mock data, supplier names and a new user

Status: Complete

## Goal
The provider mock offers options across November 2026, December 2026 and January 2027 (not only a few offers about a month ahead), with more accommodation, museum and food tours and other activities; the suppliers have recognizable names; and a fourth test user, Daniela, exists.

## Scope
- `mock_provider/app/fixtures.py`: repeated listings that fill every day from the day after the clock's "today" until 31 January 2027 (a clock past that window gets the next 92 days), seasonal prices for the repeated listings, six more activities per destination (a museum tour, a food places tour and four others), supplier names. The base catalogue keeps its ids and prices.
- Supplier identifiers renamed `supplier-a/b/c` to `supplier-alamo`, `supplier-boots`, `supplier-croc` everywhere (mock, backend, evaluations, tests, docs); the frontend shows them as "Supplier Alamo", "Supplier Boots", "Supplier Croc".
- Seed user `daniela` (created on startup if missing, also in an existing database).
- The assistant's `search_options` returns at most 20 offers (available first, then cheapest) with `offersTotal` and a `note`, because a year-long trip now matches dozens of offers and the model's tool result is bounded; the assistant's tool result limit and the "tools used" excerpt were raised to 16000 characters so the page and the evaluation see what the model saw.
- Tests and the search evaluation updated, with new checks for the months, the tours and the limit.

## Out of scope
- Real hotel or company names (suppliers and stays stay generic), new destinations or categories, changes to the supplied contract.
- Running the assistant evaluation again (it needs the developer's key and its daily limit).

## Tasks
- [x] 1.1 Mock catalogue: repeated listings over Nov 2026 to Jan 2027, seasonal prices, museum, food and other activities, supplier display names in stay titles; reset loads it in bulk.
- [x] 1.2 Rename the suppliers everywhere and show their names in the frontend (Search, Itinerary).
- [x] 1.3 Seed user Daniela (missing users are added on startup).
- [x] 1.4 `search_options` limit (20 best offers, `offersTotal`, `note`) and larger tool-result limits.
- [x] 2.1 Tests: mock fixtures (months, fallback window, tours, stable base ids, seasons), user lists, MCP limit and parity; `evals.search` cases for each month and the tours.
- [x] 2.2 Docs: README, mock README, PROJECT.md, `docs/` and this change file.

## Acceptance criteria
- A search for any category in November (from the 20th), December or January returns offers inside that month; museum and food places tours exist for every destination.
- Suppliers appear as Supplier Alamo, Boots and Croc in the Search and Itinerary tabs and in stay titles; `GET /auth/users` lists alice, bob, carol and daniela.
- The assistant's search tool result always fits what the model is given and says when offers were left out.
- `pytest` (backend and mock), `ruff check .`, the frontend `typecheck` and `evals.search` pass.
- `assignment/` is untouched.

## Technologies implemented
None added.
