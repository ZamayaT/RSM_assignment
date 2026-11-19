"""Interrupted work, two workers, and lost or corrupted files: a document is never falsely reported as ready."""
import os
import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import document_steps
from app.db import get_engine
from app.document_storage import TMP_SUFFIX
from app.models import Document
from tests.document_helpers import (  # noqa: F401
    complete_document,
    docs_dir,
    documents,
    download,
    fresh_item,
    future,
    get_document,
    mock,
    pdf_text,
    process_all,
    request_document,
    retry,
    row,
    set_row,
)


def test_a_stuck_in_progress_document_is_reset_and_then_completed(client, docs_dir):
    headers, trip_id, offer, item = fresh_item(client)
    document_id = request_document(client, headers, trip_id).json()["id"]
    assert document_steps.claim_document() is not None  # the worker takes it and then "dies"
    assert get_document(client, headers, trip_id, document_id)["status"] == "in_progress"

    assert document_steps.recover_stuck_documents() == 0  # not stuck yet: still inside the window
    assert document_steps.recover_stuck_documents(future()) == 1

    assert get_document(client, headers, trip_id, document_id)["status"] == "waiting"
    process_all()
    done = get_document(client, headers, trip_id, document_id)
    assert done["status"] == "complete" and done["attempts"] == 2
    assert download(client, headers, trip_id, document_id).status_code == 200


def test_after_the_maximum_attempts_an_interrupted_document_fails_with_an_explanation(client, docs_dir, monkeypatch):
    headers, trip_id, offer, item = fresh_item(client)
    document_id = request_document(client, headers, trip_id).json()["id"]
    maximum = document_steps.get_settings().document_max_attempts

    for attempt in range(1, maximum + 1):
        assert document_steps.claim_document()[1] == attempt
        assert document_steps.recover_stuck_documents(future()) == 1
        expected = "failed" if attempt == maximum else "waiting"
        assert get_document(client, headers, trip_id, document_id)["status"] == expected

    failed = get_document(client, headers, trip_id, document_id)
    assert failed["failureMessage"] == "Generation was interrupted too many times."
    assert document_steps.process_next_document() is False  # it does not loop forever
    assert retry(client, headers, trip_id, document_id).status_code == 200  # the user can still retry
    process_all()
    assert get_document(client, headers, trip_id, document_id)["status"] == "complete"


def test_two_workers_never_render_the_same_document(client, docs_dir):
    first_headers, first_trip, _, _ = fresh_item(client)
    second_headers, second_trip, _, _ = fresh_item(client)
    first_id = request_document(client, first_headers, first_trip).json()["id"]
    second_id = request_document(client, second_headers, second_trip).json()["id"]

    with Session(get_engine()) as other_worker:  # another worker has the oldest document claimed right now
        locked = other_worker.scalars(
            select(Document).where(Document.status == "waiting").order_by(Document.created_at).limit(1).with_for_update()
        ).one()
        assert str(locked.id) == first_id
        claimed = document_steps.claim_document()
        assert claimed is not None and str(claimed[0]) == second_id  # skips the locked one
        assert document_steps.claim_document() is None  # nothing else is free


def test_simultaneous_claims_of_one_document_give_it_to_exactly_one_worker(client, docs_dir):
    headers, trip_id, offer, item = fresh_item(client)
    request_document(client, headers, trip_id)

    with ThreadPoolExecutor(6) as pool:
        claims = list(pool.map(lambda _: document_steps.claim_document(), range(6)))

    assert len([c for c in claims if c is not None]) == 1


def test_a_late_worker_cannot_complete_a_document_that_was_claimed_again(client, docs_dir):
    headers, trip_id, offer, item = fresh_item(client)
    document_id = request_document(client, headers, trip_id).json()["id"]
    slow_id, slow_attempt = document_steps.claim_document()
    document_steps.recover_stuck_documents(future())
    fast_id, fast_attempt = document_steps.claim_document()

    assert document_steps.render_document(fast_id, fast_attempt) is True
    assert document_steps.render_document(slow_id, slow_attempt) is False  # too late: ignored

    stored = row(document_id)
    assert stored["status"] == "complete" and stored["attempts"] == fast_attempt == 2
    assert download(client, headers, trip_id, document_id).status_code == 200


def test_a_deleted_file_is_detected_and_retry_produces_a_valid_file(client, docs_dir):
    headers, trip_id, offer, item = fresh_item(client)
    document_id = complete_document(client, headers, trip_id)
    (docs_dir / row(document_id)["file_path"]).unlink()

    response = download(client, headers, trip_id, document_id)

    assert response.status_code == 409 and response.json()["code"] == "DOCUMENT_UNAVAILABLE"
    failed = get_document(client, headers, trip_id, document_id)
    assert failed["status"] == "failed" and "missing or does not match" in failed["failureMessage"]
    assert retry(client, headers, trip_id, document_id).status_code == 200
    process_all()
    again = download(client, headers, trip_id, document_id)
    assert again.status_code == 200 and again.content.startswith(b"%PDF")


def test_the_list_never_shows_a_document_as_ready_when_its_file_is_missing(client, docs_dir):
    headers, trip_id, offer, item = fresh_item(client)
    document_id = complete_document(client, headers, trip_id)
    assert documents(client, headers, trip_id)[0]["status"] == "complete"
    (docs_dir / row(document_id)["file_path"]).unlink()

    listed = documents(client, headers, trip_id)

    assert listed[0]["status"] == "failed" and row(document_id)["status"] == "failed"


def test_a_modified_file_is_detected_by_its_checksum(client, docs_dir):
    headers, trip_id, offer, item = fresh_item(client)
    document_id = complete_document(client, headers, trip_id)
    path = docs_dir / row(document_id)["file_path"]
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0x01  # same size, one bit different
    path.write_bytes(bytes(data))

    response = download(client, headers, trip_id, document_id)

    assert response.status_code == 409 and response.json()["code"] == "DOCUMENT_UNAVAILABLE"
    assert get_document(client, headers, trip_id, document_id)["status"] == "failed"
    assert retry(client, headers, trip_id, document_id).status_code == 200
    process_all()
    good = download(client, headers, trip_id, document_id)
    assert good.status_code == 200 and "Summer in Lisbon" in pdf_text(good.content)


def test_a_leftover_temporary_file_never_makes_a_document_complete_and_is_cleaned_up(client, docs_dir):
    headers, trip_id, offer, item = fresh_item(client)
    document_id = request_document(client, headers, trip_id).json()["id"]
    document_steps.claim_document()  # the worker wrote a temporary file and died before the rename
    leftover = docs_dir / f"{document_id}.pdf{TMP_SUFFIX}"
    leftover.write_bytes(b"%PDF-partial")
    old = time.time() - 5000
    os.utime(leftover, (old, old))
    stray = docs_dir / f"{'0' * 8}-stray.pdf{TMP_SUFFIX}"  # belongs to no live job
    stray.write_bytes(b"x")
    os.utime(stray, (old, old))
    fresh = docs_dir / f"fresh.pdf{TMP_SUFFIX}"  # recent: might still be being written
    fresh.write_bytes(b"x")

    assert get_document(client, headers, trip_id, document_id)["status"] == "in_progress"
    assert download(client, headers, trip_id, document_id).status_code == 409
    document_steps.clean_temporary_files()
    assert not stray.exists() and fresh.exists()
    assert leftover.exists()  # a live job may still be writing it

    document_steps.recover_stuck_documents(future())
    document_steps.clean_temporary_files()
    assert not leftover.exists()
    process_all()
    assert get_document(client, headers, trip_id, document_id)["status"] == "complete"
    assert (docs_dir / f"{document_id}.pdf").read_bytes().startswith(b"%PDF-1")


def test_a_worker_restart_loses_no_request(client, docs_dir):
    headers, trip_id, offer, item = fresh_item(client)
    waiting = request_document(client, headers, trip_id).json()["id"]
    assert get_document(client, headers, trip_id, waiting)["status"] == "waiting"  # nobody is working on it yet

    # A worker takes it and is killed; the restarted worker's first pass recovers and finishes it.
    document_steps.claim_document()
    assert document_steps.run_documents_once(now=future()) == 1

    assert get_document(client, headers, trip_id, waiting)["status"] == "complete"
    set_row(waiting, started_at=None)
    assert [d["id"] for d in documents(client, headers, trip_id)] == [waiting]
