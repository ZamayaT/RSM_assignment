"""Generation flow: answered at once, built by the worker, complete only after the file exists; failures retry."""
from concurrent.futures import ThreadPoolExecutor

from app import document_steps
from tests.document_helpers import (  # noqa: F401
    complete_document,
    document_count,
    docs_dir,
    documents,
    download,
    fresh_item,
    get_document,
    mock,
    process_all,
    request_document,
    retry,
    row,
    sha256,
)


def trip_version(client, headers, trip_id) -> int:
    return client.get(f"/trips/{trip_id}", headers=headers).json()["version"]


def test_request_answers_at_once_with_a_waiting_document_and_no_file(client, docs_dir):
    headers, trip_id, offer, item = fresh_item(client)

    response = request_document(client, headers, trip_id)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "waiting" and body["requestedBy"]["displayName"] == "Alice"
    assert body["tripVersion"] == trip_version(client, headers, trip_id)
    assert list(docs_dir.iterdir()) == []  # nothing is rendered by the request itself
    assert row(body["id"])["file_path"] is None


def test_worker_step_builds_a_valid_pdf_and_marks_complete_only_after_the_file_exists(client, docs_dir, monkeypatch):
    headers, trip_id, offer, item = fresh_item(client)
    document_id = request_document(client, headers, trip_id).json()["id"]
    seen = {}
    real_write = document_steps.write_file

    def spy(directory, doc_id, content):
        seen["before"] = row(str(doc_id))["status"]
        stored = real_write(directory, doc_id, content)
        seen["file_exists"] = (docs_dir / stored.path).is_file()
        seen["after"] = row(str(doc_id))["status"]  # the file is there, the document is still not complete
        return stored

    monkeypatch.setattr(document_steps, "write_file", spy)

    assert document_steps.process_next_document() is True

    assert seen == {"before": "in_progress", "file_exists": True, "after": "in_progress"}
    stored = row(document_id)
    assert stored["status"] == "complete" and stored["finished_at"] is not None
    content = (docs_dir / stored["file_path"]).read_bytes()
    assert content.startswith(b"%PDF") and content.rstrip().endswith(b"%%EOF")
    assert stored["size_bytes"] == len(content) and stored["sha256"] == sha256(content)
    assert get_document(client, headers, trip_id, document_id)["sizeBytes"] == len(content)
    assert [p.name for p in docs_dir.iterdir()] == [f"{document_id}.pdf"]  # no temporary file left


def test_a_repeated_request_returns_the_same_live_document_and_creates_one_row(client, docs_dir):
    headers, trip_id, offer, item = fresh_item(client)

    first = request_document(client, headers, trip_id)
    second = request_document(client, headers, trip_id)

    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["id"] == second.json()["id"]
    assert document_count(trip_id) == 1


def test_simultaneous_requests_create_one_document(client, docs_dir):
    headers, trip_id, offer, item = fresh_item(client)

    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(lambda _: request_document(client, headers, trip_id), range(4)))

    assert sum(r.status_code == 201 for r in results) == 1
    assert {r.status_code for r in results} <= {200, 201}
    assert len({r.json()["id"] for r in results}) == 1
    assert document_count(trip_id) == 1


def test_after_completion_a_new_request_creates_a_new_document_with_a_new_snapshot(client, docs_dir):
    headers, trip_id, offer, item = fresh_item(client)
    first_id = complete_document(client, headers, trip_id)

    second = request_document(client, headers, trip_id)

    assert second.status_code == 201 and second.json()["id"] != first_id
    assert row(second.json()["id"])["snapshot"]["generatedAt"] >= row(first_id)["snapshot"]["generatedAt"]
    listed = documents(client, headers, trip_id)  # newest first, with who, when, version, status and size
    assert [d["id"] for d in listed] == [second.json()["id"], first_id]
    assert listed[1]["status"] == "complete" and listed[1]["sizeBytes"] > 0
    assert listed[0]["status"] == "waiting" and listed[0]["requestedBy"]["displayName"] == "Alice"
    assert listed[0]["tripVersion"] and listed[0]["snapshotAt"]


def test_failed_generation_has_a_message_and_retry_completes_it_from_the_same_snapshot(client, docs_dir, monkeypatch):
    headers, trip_id, offer, item = fresh_item(client)
    document_id = request_document(client, headers, trip_id).json()["id"]
    snapshot = row(document_id)["snapshot"]
    blocker = docs_dir / "blocker"
    blocker.write_text("a file, so nothing can be created below it")
    settings = document_steps.get_settings()
    good_directory = settings.documents_dir
    monkeypatch.setattr(settings, "documents_dir", str(blocker / "documents"))

    assert document_steps.process_next_document() is True

    failed = get_document(client, headers, trip_id, document_id)
    assert failed["status"] == "failed" and "could not be stored" in failed["failureMessage"]
    assert row(document_id)["file_path"] is None
    assert download(client, headers, trip_id, document_id).status_code == 409  # never served

    monkeypatch.setattr(settings, "documents_dir", good_directory)
    retried = retry(client, headers, trip_id, document_id)
    assert retried.status_code == 200 and retried.json()["status"] == "waiting"
    assert retried.json()["failureMessage"] is None

    process_all()
    done = get_document(client, headers, trip_id, document_id)
    assert done["status"] == "complete" and done["failureMessage"] is None
    assert row(document_id)["snapshot"] == snapshot  # the retry rendered the same point in time
    assert download(client, headers, trip_id, document_id).status_code == 200
    assert document_count(trip_id) == 1


def test_only_a_failed_document_can_be_retried(client, docs_dir):
    headers, trip_id, offer, item = fresh_item(client)
    live = request_document(client, headers, trip_id).json()["id"]
    assert retry(client, headers, trip_id, live).json()["code"] == "DOCUMENT_NOT_FAILED"
    process_all()
    assert retry(client, headers, trip_id, live).json()["code"] == "DOCUMENT_NOT_FAILED"


def test_a_document_that_is_not_complete_is_not_downloadable(client, docs_dir):
    headers, trip_id, offer, item = fresh_item(client)
    document_id = request_document(client, headers, trip_id).json()["id"]

    response = download(client, headers, trip_id, document_id)

    assert response.status_code == 409 and response.json()["code"] == "DOCUMENT_NOT_READY"


def test_download_is_a_pdf_with_a_descriptive_file_name(client, docs_dir):
    headers, trip_id, offer, item = fresh_item(client)
    document_id = complete_document(client, headers, trip_id)

    response = download(client, headers, trip_id, document_id)

    assert response.status_code == 200 and response.headers["content-type"] == "application/pdf"
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment") and f"_v2_{document_id[:8]}.pdf" in disposition
    assert response.content.startswith(b"%PDF")
    assert sha256(response.content) == row(document_id)["sha256"]
