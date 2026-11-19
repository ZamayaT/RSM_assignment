"""The snapshot: a document shows the trip as it was when requested, whatever changes afterwards."""
import pytest
from sqlalchemy import text

from app.db import get_engine
from tests.document_helpers import (  # noqa: F401
    book_current,
    complete_document,
    control,
    docs_dir,
    download,
    fresh_item,
    get_document,
    itinerary,
    mock,
    pdf_text,
    process_all,
    request_document,
    row,
)
from tests.itinerary_helpers import TRIP, add, offers


def text_of(client, headers, trip_id, document_id) -> str:
    response = download(client, headers, trip_id, document_id)
    assert response.status_code == 200, response.text
    return pdf_text(response.content)


def rename_trip(client, headers, trip_id, name) -> None:
    version = client.get(f"/trips/{trip_id}", headers=headers).json()["version"]
    response = client.put(f"/trips/{trip_id}", json={**TRIP, "name": name, "version": version}, headers=headers)
    assert response.status_code == 200, response.text


def test_later_changes_never_alter_a_document_that_was_already_requested(client, docs_dir):
    headers, trip_id, offer, item = fresh_item(client)
    document_id = request_document(client, headers, trip_id).json()["id"]
    snapshot_before = row(document_id)["snapshot"]
    version_before = row(document_id)["trip_version"]

    # After the request: confirm a booking, rename the trip, add another itinerary item.
    book_current(client, headers, trip_id, item)
    rename_trip(client, headers, trip_id, "A completely different name")
    second = offers(client, headers, trip_id, category="activity", destination="Lisbon")[0]
    assert add(client, headers, trip_id, second["id"], itinerary(client, headers, trip_id)["version"]).status_code == 201
    process_all()

    assert row(document_id)["snapshot"] == snapshot_before  # stored content is untouched
    assert row(document_id)["trip_version"] == version_before
    content = text_of(client, headers, trip_id, document_id)
    assert "A completely different name" not in content and second["title"] not in content
    assert "Summer in Lisbon" in content and item["title"] in content
    assert f"from trip version {version_before}" in content
    assert "Confirmed" not in content.splitlines()  # the booking was confirmed after the request


def test_a_new_document_shows_the_new_content_and_a_higher_version(client, docs_dir):
    headers, trip_id, offer, item = fresh_item(client)
    first_id = complete_document(client, headers, trip_id)
    book_current(client, headers, trip_id, item)
    rename_trip(client, headers, trip_id, "Renamed trip")
    second_id = complete_document(client, headers, trip_id)

    first, second = (get_document(client, headers, trip_id, i) for i in (first_id, second_id))
    old, new = (text_of(client, headers, trip_id, i) for i in (first_id, second_id))

    assert second["tripVersion"] > first["tripVersion"]
    assert "Summer in Lisbon" in old and "Renamed trip" not in old
    assert "Renamed trip" in new and "Confirmed" in new.splitlines()
    assert f"from trip version {second['tripVersion']}" in new


def test_the_pdf_states_the_time_the_user_and_the_trip_version(client, docs_dir):
    headers, trip_id, offer, item = fresh_item(client)
    document_id = complete_document(client, headers, trip_id)
    stored = row(document_id)

    lines = text_of(client, headers, trip_id, document_id).splitlines()

    header = next(line for line in lines if line.startswith("Generated at"))  # the footer is drawn first

    assert header == (
        f"Generated at {stored['snapshot_at']:%Y-%m-%d %H:%M} UTC by Alice from trip version {stored['trip_version']}"
    )
    assert f"Document {document_id}" in lines and "Page 1" in lines  # footer


def test_costs_and_booking_statuses_in_the_pdf_match_the_snapshot(client, docs_dir):
    headers, trip_id, offer, item = fresh_item(client)
    attempt = book_current(client, headers, trip_id, item).json()
    assert attempt["status"] == "confirmed"
    budget = client.get(f"/trips/{trip_id}/budget", headers=headers).json()
    document_id = complete_document(client, headers, trip_id)

    content = text_of(client, headers, trip_id, document_id)

    snapshot = row(document_id)["snapshot"]
    assert snapshot["budget"]["confirmedTotal"] == budget["confirmedTotal"]
    assert snapshot["budget"]["estimatedTotal"] == budget["estimatedTotal"]
    for total in (budget["confirmedTotal"], budget["combinedTotal"], budget["budget"], budget["remaining"]):
        assert f"{total} USD" in content
    assert "Confirmed" in content.splitlines()  # the item's line and its booking row
    assert f"{attempt['acceptedPrice']['amount']} USD" in content
    assert snapshot["bookings"][0]["status"] == "confirmed"


@pytest.mark.parametrize("state", ["pending", "unknown"])
def test_a_pending_or_unknown_booking_is_never_shown_as_confirmed(client, docs_dir, state):
    headers, trip_id, offer, item = fresh_item(client)
    control("PUT", "/booking-outcomes", outcome="pending", count=1)
    attempt = book_current(client, headers, trip_id, item).json()
    assert attempt["status"] == "pending"
    if state == "unknown":
        with get_engine().begin() as connection:
            connection.execute(text("UPDATE booking_attempts SET status='unknown' WHERE id=:i"), {"i": attempt["id"]})
    document_id = complete_document(client, headers, trip_id)

    content = text_of(client, headers, trip_id, document_id)

    assert "Confirmed" not in content.splitlines()
    assert "0.00 USD" in content  # nothing is counted as confirmed
    expected = "Pending (not confirmed yet)" if state == "pending" else "Unknown (the outcome is not confirmed)"
    assert expected in content
    assert row(document_id)["snapshot"]["bookings"][0]["status"] == state


def test_characters_outside_the_pdf_font_are_replaced_by_a_question_mark(client, docs_dir):
    headers, trip_id, offer, item = fresh_item(client)
    version = client.get(f"/trips/{trip_id}", headers=headers).json()["version"]
    changed = {**TRIP, "name": "Café 日本", "version": version}
    assert client.put(f"/trips/{trip_id}", json=changed, headers=headers).status_code == 200
    document_id = complete_document(client, headers, trip_id)

    content = text_of(client, headers, trip_id, document_id)

    assert "Café ??" in content  # Western characters stay, others become "?"
