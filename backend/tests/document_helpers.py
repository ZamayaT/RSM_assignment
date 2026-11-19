"""Shared helpers for the document tests. Files go to a temporary directory, never to the real volume."""
import hashlib
import re
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app import document_steps
from app.config import get_settings
from app.db import get_engine
from tests.booking_helpers import (  # noqa: F401
    book_current,
    control,
    fresh_item,
    itinerary,
    make_trip,
    mock,
    share,
)
from tests.conftest import login  # noqa: F401


@pytest.fixture
def docs_dir(tmp_path, monkeypatch):
    """Documents are written to a fresh temporary directory for the test."""
    monkeypatch.setattr(get_settings(), "documents_dir", str(tmp_path))
    return tmp_path


def future(seconds: int = 1000) -> datetime:
    """A 'now' far enough ahead that a claimed document counts as stuck, so tests never sleep."""
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)


def request_document(client, headers, trip_id):
    return client.post(f"/trips/{trip_id}/documents", headers=headers)


def documents(client, headers, trip_id) -> list[dict]:
    response = client.get(f"/trips/{trip_id}/documents", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def get_document(client, headers, trip_id, document_id) -> dict:
    response = client.get(f"/trips/{trip_id}/documents/{document_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def download(client, headers, trip_id, document_id):
    return client.get(f"/trips/{trip_id}/documents/{document_id}/download", headers=headers)


def retry(client, headers, trip_id, document_id):
    return client.post(f"/trips/{trip_id}/documents/{document_id}/retry", headers=headers)


def row(document_id: str) -> dict:
    with get_engine().connect() as connection:
        return dict(
            connection.execute(text("SELECT * FROM documents WHERE id = :i"), {"i": document_id}).mappings().one()
        )


def document_count(trip_id: str) -> int:
    with get_engine().connect() as connection:
        return connection.execute(text("SELECT count(*) FROM documents WHERE trip_id = :t"), {"t": trip_id}).scalar_one()


def set_row(document_id: str, **columns) -> None:
    assignments = ", ".join(f"{name} = :{name}" for name in columns)
    with get_engine().begin() as connection:
        connection.execute(text(f"UPDATE documents SET {assignments} WHERE id = :i"), {**columns, "i": document_id})


def process_all() -> int:
    done = 0
    while document_steps.process_next_document():
        done += 1
    return done


def complete_document(client, headers, trip_id) -> str:
    """Request a document and let the worker finish it. Returns its id."""
    response = request_document(client, headers, trip_id)
    assert response.status_code in (200, 201), response.text
    process_all()
    document = get_document(client, headers, trip_id, response.json()["id"])
    assert document["status"] == "complete", document
    return document["id"]


def unescape(match) -> str:
    code = match.group(1)
    return chr(int(code, 8)) if len(code) == 3 and code.isdigit() else code


def pdf_text(content: bytes) -> str:
    """The text shown in a PDF written by the renderer (uncompressed, one string per text line)."""
    raw = content.decode("latin-1")
    parts = re.findall(r"\(((?:\\.|[^\\)])*)\) Tj", raw)
    return "\n".join(re.sub(r"\\([0-7]{3}|.)", unescape, part) for part in parts)


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
