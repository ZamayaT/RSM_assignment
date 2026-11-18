# Travel Planning Platform

Group trip planning with provider search, simulated bookings, PDF trip documents, and a read-only AI assistant using MCP.

> Status: under construction. This README only documents what is already implemented; setup steps are added as each development step is completed.

Everything runs in **Docker**: Python, Node, PostgreSQL and all packages are installed inside containers. On your machine you only need Git and Docker Desktop.

## 1. Requirements

| Program | Purpose | Download |
|---|---|---|
| Git | Clone the repository | https://git-scm.com/downloads |
| Docker Desktop (includes Docker Compose) | Build and run all services | https://www.docker.com/products/docker-desktop/ |

On Windows, Docker Desktop requires WSL 2. The installer offers to enable it; accept and restart if asked.

## 2. Check the installation

Open a terminal (PowerShell, Git Bash, or a macOS/Linux terminal) and run:

```bash
git --version
docker --version
docker compose version
```

Each command should print a version. Open Docker Desktop and wait until it is running before continuing.

## 3. Clone the repository

```bash
git clone https://github.com/ZamayaT/RSM_assignment.git
cd RSM_assignment
```

## 4. Create the configuration file

Copy the example configuration. The defaults work for a local run; edit `.env` only if a port is already in use.

```bash
cp .env.example .env
```

## 5. Build and start everything

The first run downloads images and installs packages; it can take several minutes.

```bash
docker compose up --build
```

Leave this terminal open; it shows the logs of all services. Press `Ctrl+C` to stop.

To run in the background instead:

```bash
docker compose up --build -d
```

## 6. Open the application

| Service | URL |
|---|---|
| Web application | http://localhost:5173 |
| Backend API documentation | http://localhost:8000/docs |
| Provider mock API documentation | http://localhost:4010/docs |

The start page lists the seeded test users (`alice`, `bob`, `carol`). The backend creates them on startup if the database has none, and applies its migrations automatically when its container starts.

To log in, click a name. From there you can create a trip (name, destinations Lisbon/Paris/Rome, dates, travelers, budget in USD, notes), see it under **My trips**, open it, and edit it. Use **Switch user** in the top bar to log in as someone else: each user sees only their own trips. If two people edit the same trip, the second save is refused with a "changed by someone else" message and nothing is overwritten; click **Reload latest** to continue from the newest version. Your login is kept in the browser, so a page reload keeps you signed in.

To share a trip, open it and click **Participants**. As the organizer, type a username (suggestions appear as you type), choose **editor** or **viewer**, and click **Add**. You can also change a participant's role or remove them. To try the roles, add `bob` as viewer and `carol` as editor, then use **Switch user**: a viewer can read the trip but not edit it, an editor can edit the trip but sees the participants read-only, and a user who is not on the trip (or was removed) does not see it. The backend enforces these rules, not only the screens.

To search, open a trip and click **Search**. Choose a category (transport, accommodation, activity), one of the trip's destinations (transport also asks for an origin), adjust the dates, travelers or supplier if you like, and click **Search**. The results table can be sorted by price, start time or supplier. Results are estimates from the provider mock, not bookings: prices are not guaranteed, and each offer shows when it was searched and until when the quote is valid. Anyone on the trip, including viewers, can search.

To try a partial or failed search, run these in a terminal while the services are running, then search accommodation again in the browser:

```bash
# one supplier down: the page shows the other suppliers' results and a warning for supplier-b
curl -s -X PUT http://localhost:4010/control/suppliers/supplier-b/failure -H "Content-Type: application/json" -d '{"mode":"unavailable"}'

# all accommodation suppliers down: the page shows "The search failed" with a "Try again" button
curl -s -X PUT http://localhost:4010/control/suppliers/supplier-a/failure -H "Content-Type: application/json" -d '{"mode":"unavailable"}'
curl -s -X PUT http://localhost:4010/control/suppliers/supplier-c/failure -H "Content-Type: application/json" -d '{"mode":"unavailable"}'

# back to normal
curl -s -X POST http://localhost:4010/control/reset
```

The backend waits at most `PROVIDER_TIMEOUT_SECONDS` (default 5, set in `.env`) for the provider.

To build an itinerary, click **Add to itinerary** on a search result (organizers and editors; viewers can only look). Open **Itinerary** from the trip page to see the items in order with schedule, cost, an "Estimate" or "Expired quote" label and warnings. Use **Up**/**Down** to arrange items and **Remove** to delete one. New items are placed by start time; the saved order is what everyone sees. The **Budget** page lists the costs and compares the total with the trip budget (remaining or over budget).

- **What is stored**: adding an item saves a copy of the offer as the provider returned it at that moment. If the provider's price changes later, the itinerary and budget keep the saved estimate.
- **Warnings** (simplified rules): two items conflict when their time ranges overlap, comparing UTC instants (an end equal to the next start is fine). A stay may overlap activities and transport, but two overlapping stays conflict. Also flagged: missing schedule or price, an expired quote, an item outside the trip dates, and a destination that is not on the trip. Travel time and opening hours are not checked. "Expired" uses the backend's clock, so it can differ from the provider mock's clock if you shifted that.
- **Budget rounding**: an item's cost is the offer's total price for the party (not multiplied by travelers). Totals are exact sums to the cent; any result with more decimals would be rounded half-up to the cent. Items without a price are left out. Every cost is an estimate until the item is booked; a confirmed booking counts as a confirmed cost at the price the provider accepted.

### Bookings

To book an item, open the **Itinerary** and click **Book** (organizers and editors; viewers can only look). A dialog shows the provider's current terms (price, availability, quote revision and validity) next to the estimate saved in the itinerary, and highlights what changed. Nothing is booked until you click **Confirm booking**, and it books exactly the terms shown. A sold-out or expired offer cannot be confirmed; use **Refresh price** on the item to replace its saved estimate with the current terms.

Each item then shows its status: *Estimate*, *Expired quote*, *Booking pending*, *Confirmed*, *Failed* or *Unknown outcome*. Open **Bookings** from the trip page to see every attempt with its status, price (the accepted price once the provider accepted it) and times. The page updates by itself while a booking can still change, including after a reload. A booked item cannot be removed or re-priced.

- **No duplicates**: clicking **Confirm booking** twice, retrying after a lost answer, or repeating the request books once. Each decision has its own identifier, and the attempt is saved before the provider is called.
- **Unknown is not failed**: if the provider does not answer in time (or answers with an error that proves nothing), the attempt is **Unknown**. It is never shown as failed or confirmed. The `worker` service asks the provider what happened (by the booking reference), sends the same booking again only if the provider has no record of it, and shows the real status. If the provider stays unreachable for about 10 minutes the page says **Outcome unresolved**; click **Check again** later. Check again only looks the booking up; it never books again.
- **Failed**: when the provider refuses (the price or terms changed, or the offer is sold out), nothing is booked and the reason is shown. Click **Retry** (fresh terms, a new decision) or **Choose another offer**.
- **Mixed results**: confirmed items stay booked and visible while others fail or wait; the Bookings page explains the next step for each.
- **Budget**: confirmed bookings count as confirmed costs at the accepted price, which later provider price changes never alter. Pending and unknown items still count as estimates.

The `worker` service starts with the rest (`docker compose up --build`) and uses the same image as the backend. Its timings (how soon an unknown outcome is checked, how often a pending booking is read, when it is called unresolved) are the `BOOKING_*` values in `.env.example`; the defaults are fine.

To try the difficult cases, run these while the services are running, then book an item in the browser (replace `OFFER_ID` with the item's offer id, shown by the search results or the itinerary API at http://localhost:8000/docs, and `supplier-a` with its supplier):

```bash
M=http://localhost:4010; J="Content-Type: application/json"

# a price change before you confirm: the dialog highlights the new price
curl -s -X POST $M/control/offers/OFFER_ID -H "$J" -d '{"price":"150.00"}'

# a sold-out offer: the dialog refuses to confirm
curl -s -X POST $M/control/offers/OFFER_ID -H "$J" -d '{"available":false}'

# the next booking is accepted but stays pending (the Bookings page updates when it resolves, after about 30 s)
curl -s -X PUT $M/control/booking-outcomes -H "$J" -d '{"outcome":"pending","count":1}'

# the next booking is accepted and then fails
curl -s -X PUT $M/control/booking-outcomes -H "$J" -d '{"outcome":"failed","count":1}'

# a lost response: the provider answers after the backend gave up, so the booking shows Unknown, then settles by itself
curl -s -X PUT $M/control/suppliers/supplier-a/latency -H "$J" -d '{"milliseconds":8000}'
# ...click Confirm booking, wait for "Unknown", then remove the delay:
curl -s -X PUT $M/control/suppliers/supplier-a/latency -H "$J" -d '{"milliseconds":0}'

# back to normal
curl -s -X POST $M/control/reset
```

To see an edit conflict, log in as `alice` in one browser window and as `carol` in a private window. As `alice`, create a trip and share it with `carol` as editor. Open the **Itinerary** of that trip in both windows, then change it in one window (for example, remove an item) and change it in the other without reloading. The second save is refused with a dialog that says someone else saved first, shows the latest itinerary next to your change, and lets you **Re-apply** it or **Discard** it. Nothing saved is overwritten. A trip edit and an itinerary change share one version, so they can conflict with each other too.

The API endpoints are listed and can be tried at http://localhost:8000/docs.

## 7. Run the tests

With the services running (in another terminal):

```bash
docker compose exec backend pytest
docker compose exec mock_provider pytest
```

The itinerary and booking tests (outcomes, idempotency, recovery by the worker, permissions and concurrency) also call the real mock, so the `backend` and `mock_provider` services must be running; after a `docker compose down` they are not, so start them again first. The booking tests run the worker's steps directly, with the waiting intervals set to zero, so they do not depend on the `worker` service or on waiting. The search tests call the real provider mock over HTTP, so the `mock_provider` service must be running; they reset the mock before and after each test, which also clears any failures you set by hand. The backend tests create and use their own database (`<POSTGRES_DB>_test`, dropped and recreated on each run), so your trips and logins are never touched. All of them should pass; they cover login, validation, trips, visibility, versioning conflicts, concurrent saves and persistence across a restart.

The provider mock stores its data in its own PostgreSQL schema (`mock_provider`) and applies its migrations automatically when its container starts. Its fixtures, demo tokens, clock, `/control` endpoints and copy-paste failure scenarios are documented in [`mock_provider/README.md`](mock_provider/README.md). On startup it also loads its fixture offers (Lisbon, Paris, Rome) if there are none.

The mock's clock follows real time by default. To freeze it or shift it, uncomment `MOCK_CLOCK_FROZEN_AT` (for example `2030-01-15T09:00:00Z`) or `MOCK_CLOCK_OFFSET_SECONDS` in `.env`, then run `docker compose up -d mock_provider`. Fixture dates are generated relative to the clock when they are first loaded.

## 8. Stop and reset

Stop the services (data is kept):

```bash
docker compose down
```

Stop and **delete all data** (the database volume) to start from scratch:

```bash
docker compose down -v
```

## 9. Troubleshooting

- **Port already in use**: change the port variables (`FRONTEND_PORT`, `BACKEND_PORT`, `MOCK_PROVIDER_PORT`) in `.env`. If you change `FRONTEND_PORT`, also update `FRONTEND_ORIGIN`; if you change `BACKEND_PORT`, also update `VITE_BACKEND_URL`. Then run `docker compose up --build` again.
- **Docker commands fail**: make sure Docker Desktop is running.
- **See the logs of one service**:

  ```bash
  docker compose logs -f backend
  ```

## Project documentation

- `assignment/`: original assignment (PRD, candidate guide, provider contract `openAPI.json`).
- `claude/PROJECT.md`: project summary, requirements, decisions, architecture, build plan.
- `claude/CLAUDE.md`: AI development rules (development harness).
- `claude/changes/`: one file per development step with its tasks.
