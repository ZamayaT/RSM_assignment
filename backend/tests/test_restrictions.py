"""Offer restrictions: from the provider through search, quote, itinerary item, refresh and the document PDF."""
from tests.booking_helpers import fresh_item, quote
from tests.document_helpers import complete_document, docs_dir, download, pdf_text, row  # noqa: F401
from tests.itinerary_helpers import MOCK, TRIP, add, control, itinerary, make_trip, mock, offers  # noqa: F401


def test_search_results_carry_restrictions_as_a_list_and_some_offers_state_none(client):
    headers, trip_id = make_trip(client)
    results = offers(client, headers, trip_id)

    assert results and all(isinstance(o["restrictions"], list) for o in results)
    everything = results + offers(client, headers, trip_id, category="activity")
    assert any(o["restrictions"] for o in everything)
    assert any(o["restrictions"] == [] for o in everything)  # an offer without restrictions shows an empty list


def test_an_added_item_keeps_the_restrictions_of_its_offer(client):
    headers, trip_id = make_trip(client)
    offer = next(o for o in offers(client, headers, trip_id) if o["restrictions"])

    item = add(client, headers, trip_id, offer["id"], 1).json()["items"][0]

    assert item["restrictions"] == offer["restrictions"]
    assert itinerary(client, headers, trip_id)["items"][0]["restrictions"] == offer["restrictions"]  # persisted


def test_the_quote_flags_changed_restrictions_and_refresh_saves_the_new_ones(client):
    headers, trip_id, offer, item = fresh_item(client)
    saved = item["restrictions"]
    assert quote(client, headers, trip_id, item)["changes"] == []  # same terms: nothing flagged

    control("POST", f"/offers/{offer['id']}", restrictions=["Minimum age 21", "Photo ID required at check-in"])
    changed = quote(client, headers, trip_id, item)

    assert "restrictions" in changed["changes"]
    assert changed["savedRestrictions"] == saved
    assert changed["restrictions"] == ["Minimum age 21", "Photo ID required at check-in"]

    version = itinerary(client, headers, trip_id)["version"]
    refreshed = client.post(f"/trips/{trip_id}/itinerary/{item['id']}/refresh", json={"version": version}, headers=headers)
    assert refreshed.status_code == 200
    assert refreshed.json()["items"][0]["restrictions"] == ["Minimum age 21", "Photo ID required at check-in"]
    assert "restrictions" not in quote(client, headers, trip_id, item)["changes"]


def test_the_document_states_each_items_restrictions(client, docs_dir):
    headers, trip_id = make_trip(client)
    offer = next(o for o in offers(client, headers, trip_id) if o["restrictions"])
    add(client, headers, trip_id, offer["id"], 1)
    document_id = complete_document(client, headers, trip_id)

    snapshot = row(document_id)["snapshot"]
    content = pdf_text(download(client, headers, trip_id, document_id).content)

    assert snapshot["itinerary"][0]["restrictions"] == offer["restrictions"]
    assert "Restrictions" in content.splitlines()  # the column heading
    for restriction in offer["restrictions"]:  # long texts wrap inside the cell, so check their words
        assert all(word in content for word in restriction.split()[:2])


def test_an_item_without_restrictions_says_none_stated_in_the_document(client, docs_dir):
    headers, trip_id = make_trip(client)
    candidates = offers(client, headers, trip_id) + offers(client, headers, trip_id, category="activity")
    offer = next(o for o in candidates if not o["restrictions"])
    add(client, headers, trip_id, offer["id"], 1)
    document_id = complete_document(client, headers, trip_id)

    content = pdf_text(download(client, headers, trip_id, document_id).content)

    assert "None stated" in content.splitlines()
