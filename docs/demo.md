# Demo walkthrough

About 15 minutes. Start the stack (README, "Run it", steps 2 to 4) and open http://localhost:5173. The seeded users are `alice`, `bob`, `carol` and `daniela`. The failure steps use the provider mock's control interface; define these once, and reset the mock first and after each scenario:

```bash
M=http://localhost:4010; J="Content-Type: application/json"
curl -s -X POST $M/control/reset
```

## 1. Main workflow

1. Log in as `alice`. **Create a trip**: destinations Lisbon and Rome, dates between tomorrow and 31 January 2027 (the mock's offers end there), 2 travelers, budget 1000 USD, notes "Beaches, relaxed pace".
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

(`TRIP_ID` is in the trip's URL.) A user who is not on the trip gets `404`: log in as `daniela` and open the same URL.

## 3. Concurrent save conflict

Log in as `alice` in one window and `carol` (editor of the trip) in a private window. Open the **Itinerary** of the trip in both, remove an item in one, then change the other without reloading. The second save is refused with a dialog that says someone else saved first and shows the latest itinerary next to your change; **Re-apply** or **Discard** it. Nothing is overwritten. (A conflicting **Edit Trip** save shows "changed by someone else" with **Reload latest**.)

## 4. Supplier failure (partial result)

```bash
curl -s -X PUT $M/control/suppliers/supplier-boots/failure -H "$J" -d '{"mode":"unavailable"}'
```

Search again: results from the other suppliers are kept and a warning names Supplier Boots; the state is "partial", never shown as complete. Take all three suppliers down and the search fails with a clear error. Restore with `curl -s -X POST $M/control/reset`.

## 5. Unknown booking outcome

```bash
curl -s -X PUT $M/control/suppliers/supplier-alamo/latency -H "$J" -d '{"milliseconds":8000}'
```

Book an offer of Supplier Alamo (`supplier-alamo`) and confirm. The provider answers after the backend gave up, so the item shows **Unknown outcome** (not failed, not confirmed). Remove the delay:

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
- As `bob` (viewer) the assistant works; as `daniela` (not on the trip), the endpoint answers `404`.

Inspect the same read-only tools directly with the commands in the README's **MCP** item.

Without a key the tab explains what to set; the rest of the demo needs no model.

## 8. More booking cases

Run one, then book an item in the browser (`OFFER_ID` is the item's offer id, shown in the itinerary API at http://localhost:8000/docs):

```bash
# the next booking is accepted but stays pending (the Bookings page updates when it resolves, after about 30 s)
curl -s -X PUT $M/control/booking-outcomes -H "$J" -d '{"outcome":"pending","count":1}'

# the next booking is accepted and then fails (Retry or Choose another offer)
curl -s -X PUT $M/control/booking-outcomes -H "$J" -d '{"outcome":"failed","count":1}'

# changed restrictions: the booking dialog highlights them next to the saved ones
curl -s -X POST $M/control/offers/OFFER_ID -H "$J" -d '{"restrictions":["Minimum age 21"]}'
```

## 9. Document failures

Generate a document in the browser after each one:

```bash
# a failed generation: send the worker to a folder it cannot create (Failed with a message), then undo it and click Retry
echo "DOCUMENTS_DIR=/proc/documents" >> .env && docker compose up -d --no-deps worker
sed -i '/^DOCUMENTS_DIR=/d' .env && docker compose up -d --no-deps worker

# a stuck job: stop the worker, generate (stays Waiting), pretend it died while working, start it again (it recovers and completes)
docker compose stop worker
docker compose exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "UPDATE documents SET status='"'"'in_progress'"'"', attempts = 1, started_at = now() - interval '"'"'5 minutes'"'"' WHERE status = '"'"'waiting'"'"'"'
docker compose start worker

# a corrupted file: alter every stored PDF, then click Download (refused, the document becomes Failed), then Retry
docker compose exec backend sh -c 'for f in /data/documents/*.pdf; do echo x >> "$f"; done'

# a lost file: delete them instead (the history shows Failed after the next refresh)
docker compose exec backend sh -c 'rm -f /data/documents/*.pdf'
```

A stuck document is picked up again after about 2 minutes (`DOCUMENT_STUCK_SECONDS`) and fails with an explanation after 3 attempts (`DOCUMENT_MAX_ATTEMPTS`).

## Reset

```bash
curl -s -X POST $M/control/reset
```
