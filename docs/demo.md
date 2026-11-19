# Demo walkthrough

About 15 minutes. Start with a clean mock and the stack running (`docker compose up --build -d`, README steps 4 to 6). Open http://localhost:5173. The seeded users are `alice`, `bob`, `carol` and `daniela`. The failure steps use the provider mock's control interface (`M=http://localhost:4010; J="Content-Type: application/json"`); reset it first and after each scenario:

```bash
M=http://localhost:4010; J="Content-Type: application/json"
curl -s -X POST $M/control/reset
```

## 1. Main workflow

1. Log in as `alice`. **Create a trip**: destinations Lisbon and Rome, dates covering the next few months, 2 travelers, budget 1000 USD, notes "Beaches, relaxed pace".
2. **Participants** tab: add `bob` as *viewer* and `carol` as *editor*.
3. **Search** tab: accommodation in Lisbon. Each offer shows price, schedule, restrictions, search time and quote validity. Add one offer to the itinerary; add an activity from Rome too.
4. **Itinerary** and **Budget** tabs: items in order, warnings (conflicts, missing data), and the estimated total against the budget.
5. **Itinerary**, click **Book** on an item: the dialog shows the provider's current terms next to the saved estimate. Confirm. The **Bookings** tab shows the attempt and the Budget tab moves the amount from estimated to confirmed.
6. **Documents** tab: generate a trip summary. It goes *waiting*, *in progress*, *complete*; download the PDF (it states the trip version and who generated it).

Expected: everything above works for `alice`; the PDF keeps its content even if you edit the trip afterwards.

## 2. Permission denial

Log in as `bob` (viewer): the same trip shows no add, remove, book or generate actions. Directly through the API the backend refuses too:

```bash
TOKEN=$(curl -s -X POST localhost:8000/auth/login -H "$J" -d '{"username":"bob"}' | python -c "import sys,json;print(json.load(sys.stdin)['token'])")
curl -s -i -X POST localhost:8000/trips/TRIP_ID/itinerary -H "Authorization: Bearer $TOKEN" -H "$J" -d '{"offerId":"x","version":1}'   # 403
```

(`TRIP_ID` is in the trip's URL.) A user who is not on the trip gets `404`: log in as a user who is not a participant and open the same URL.

## 3. Concurrent save conflict

Log in as `alice` in one window and `carol` (editor of the trip) in a private window. Open the **Itinerary** of the trip in both, remove an item in one, then change the other without reloading. The second save is refused with a "changed by someone else" dialog and nothing is overwritten; **Reload latest** continues from the newest version.

## 4. Supplier failure (partial result)

```bash
curl -s -X PUT $M/control/suppliers/supplier-boots/failure -H "$J" -d '{"mode":"unavailable"}'
```

Search again: results from the other suppliers are kept and a warning names `supplier-boots`; the state is "partial", never shown as complete. Take all three suppliers down and the search fails with a clear error. Restore with `curl -s -X POST $M/control/reset`.

## 5. Unknown booking outcome

```bash
curl -s -X PUT $M/control/suppliers/supplier-alamo/latency -H "$J" -d '{"milliseconds":8000}'
```

Book an offer of `supplier-alamo` and confirm. The provider answers after the backend gave up, so the item shows **Unknown outcome** (not failed, not confirmed). Remove the delay:

```bash
curl -s -X PUT $M/control/suppliers/supplier-alamo/latency -H "$J" -d '{"milliseconds":0}'
```

The `worker` asks the provider by booking reference and the status settles by itself to the real one, with no duplicate booking.

## 6. Price change and sold out before confirming

With an offer id from the search results:

```bash
curl -s -X POST $M/control/offers/OFFER_ID -H "$J" -d '{"price":"150.00"}'
```

Open **Book**: the dialog highlights the new price and books exactly the terms shown. Then `-d '{"available":false}'` and the dialog refuses to confirm.

## 7. Assistant (needs `LLM_API_KEY`, see the README)

Open the **Assistant** tab and ask: "Recommend the cheapest accommodation in Lisbon within our remaining budget." The answer cites real offers, relates them to the dates, budget and restrictions, and (by default) lists the tools used with their arguments and results. Then:

- "Book it for us." It refuses and explains what to do from the Itinerary tab; nothing changes.
- Take a supplier down (step 4) and ask again: the answer says the search was partial.
- Ask for accommodation under 10 dollars: it says nothing suitable was found.
- As `bob` (viewer) the assistant works; as a user not on the trip, the endpoint answers `404`.

Inspect the same read-only tools directly: see "Inspect the MCP tools" in the README.

Without a key the tab explains what to set; the rest of the demo needs no model.

## Reset

```bash
curl -s -X POST $M/control/reset
```
