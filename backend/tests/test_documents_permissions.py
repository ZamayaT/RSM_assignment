"""Who may do what with documents. The backend enforces it even when called directly."""
import uuid

from tests.document_helpers import (  # noqa: F401
    complete_document,
    document_count,
    docs_dir,
    documents,
    download,
    get_document,
    login,
    make_trip,
    mock,
    request_document,
    retry,
    row,
    set_row,
    share,
)


def team(client):
    """A trip owned by alice with bob as viewer and carol as editor; dave-like outsiders use other trips."""
    owner, trip_id = make_trip(client, owner="alice")
    share(client, owner, trip_id, "bob", "viewer")
    share(client, owner, trip_id, "carol", "editor")
    return owner, login(client, "bob"), login(client, "carol"), trip_id


def failed_document(client, headers, trip_id) -> str:
    document_id = request_document(client, headers, trip_id).json()["id"]
    set_row(document_id, status="failed", failure_message="boom")
    return document_id


def test_a_viewer_cannot_generate_or_retry_but_the_editor_can(client, docs_dir):
    owner, viewer, editor, trip_id = team(client)

    assert request_document(client, viewer, trip_id).status_code == 403
    assert document_count(trip_id) == 0
    document_id = failed_document(client, owner, trip_id)
    denied = retry(client, viewer, trip_id, document_id)
    assert denied.status_code == 403 and denied.json()["code"] == "FORBIDDEN"
    assert row(document_id)["status"] == "failed"  # nothing changed

    assert retry(client, editor, trip_id, document_id).status_code == 200
    assert request_document(client, editor, trip_id).status_code == 200  # the live one from the retry
    complete_document(client, editor, trip_id)
    assert request_document(client, editor, trip_id).status_code == 201


def test_a_non_participant_gets_404_on_every_document_endpoint_including_download(client, docs_dir):
    owner, trip_id = make_trip(client, owner="alice")
    document_id = complete_document(client, owner, trip_id)
    failed_id = failed_document(client, owner, trip_id)
    stranger = login(client, "bob")
    base = f"/trips/{trip_id}/documents"

    responses = [
        client.post(base, headers=stranger),
        client.get(base, headers=stranger),
        client.get(f"{base}/{document_id}", headers=stranger),
        client.get(f"{base}/{document_id}/download", headers=stranger),
        client.post(f"{base}/{failed_id}/retry", headers=stranger),
    ]

    assert [r.status_code for r in responses] == [404] * 5
    assert document_count(trip_id) == 2 and row(failed_id)["status"] == "failed"


def test_no_login_gets_401_on_every_document_endpoint(client, docs_dir):
    owner, trip_id = make_trip(client, owner="alice")
    document_id = complete_document(client, owner, trip_id)
    base = f"/trips/{trip_id}/documents"

    responses = [
        client.post(base),
        client.get(base),
        client.get(f"{base}/{document_id}"),
        client.get(f"{base}/{document_id}/download"),
        client.post(f"{base}/{document_id}/retry"),
    ]

    assert [r.status_code for r in responses] == [401] * 5
    assert document_count(trip_id) == 1


def test_every_participant_can_list_read_and_download_a_complete_document(client, docs_dir):
    owner, viewer, editor, trip_id = team(client)
    document_id = complete_document(client, owner, trip_id)

    for headers in (owner, viewer, editor):
        assert [d["id"] for d in documents(client, headers, trip_id)] == [document_id]
        assert get_document(client, headers, trip_id, document_id)["status"] == "complete"
        response = download(client, headers, trip_id, document_id)
        assert response.status_code == 200 and response.content.startswith(b"%PDF")


def test_a_document_id_from_another_trip_or_an_unknown_id_is_404(client, docs_dir):
    owner, trip_id = make_trip(client, owner="alice")
    other_owner, other_trip = make_trip(client, owner="alice")
    other_document = complete_document(client, other_owner, other_trip)
    base = f"/trips/{trip_id}/documents"

    for document_id in (other_document, str(uuid.uuid4())):
        assert client.get(f"{base}/{document_id}", headers=owner).status_code == 404
        assert client.get(f"{base}/{document_id}/download", headers=owner).status_code == 404
        assert client.post(f"{base}/{document_id}/retry", headers=owner).status_code == 404
