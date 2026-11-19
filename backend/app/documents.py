"""Documents: request, list, status, download and retry endpoints.

The request only takes a snapshot and answers at once; the worker renders the PDF in the background. A document
is shown as ready only while its file exists, and is only sent after its size and SHA-256 have been verified.
"""
import uuid
from datetime import datetime

from fastapi import APIRouter, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import defer

from app.auth import CurrentUser
from app.config import get_settings
from app.document_render import file_stem
from app.document_snapshot import build_snapshot
from app.document_storage import file_exists, resolve_path, verify_file
from app.errors import ApiError
from app.models import (
    DOCUMENT_COMPLETE,
    DOCUMENT_FAILED,
    DOCUMENT_LIVE_STATUSES,
    DOCUMENT_WAITING,
    Document,
    User,
)
from app.trips import SessionDep, can_edit, can_read, get_trip_for_user, require

router = APIRouter(tags=["documents"])

MSG_UNAVAILABLE = "The stored file is missing or does not match its checksum."


class UserRef(BaseModel):
    id: str
    displayName: str


class DocumentOut(BaseModel):
    id: str
    tripId: str
    status: str
    tripVersion: int
    requestedBy: UserRef | None
    snapshotAt: datetime
    createdAt: datetime
    startedAt: datetime | None
    finishedAt: datetime | None
    sizeBytes: int | None
    failureMessage: str | None
    attempts: int


def _outs(session, documents: list[Document]) -> list[DocumentOut]:
    ids = {d.requested_by for d in documents if d.requested_by}
    users = {u.id: u for u in session.scalars(select(User).where(User.id.in_(ids)))} if ids else {}
    return [
        DocumentOut(
            id=str(d.id),
            tripId=str(d.trip_id),
            status=d.status,
            tripVersion=d.trip_version,
            requestedBy=None
            if d.requested_by not in users
            else UserRef(id=str(d.requested_by), displayName=users[d.requested_by].display_name),
            snapshotAt=d.snapshot_at,
            createdAt=d.created_at,
            startedAt=d.started_at,
            finishedAt=d.finished_at,
            sizeBytes=d.size_bytes,
            failureMessage=d.failure_message,
            attempts=d.attempts,
        )
        for d in documents
    ]


def _find(session, trip_id: uuid.UUID, document_id: uuid.UUID, lock: bool = False, with_snapshot: bool = False) -> Document:
    query = select(Document).where(Document.id == document_id, Document.trip_id == trip_id)
    if not with_snapshot:
        query = query.options(defer(Document.snapshot))
    if lock:
        query = query.with_for_update()
    document = session.scalars(query.execution_options(populate_existing=True)).first()
    if document is None:
        session.rollback()
        raise ApiError(404, "NOT_FOUND", "Document not found.")
    return document


def _mark_unavailable(session, document_id: uuid.UUID) -> None:
    """The file of a `complete` document is gone or altered: it is no longer ready."""
    session.execute(
        update(Document)
        .where(Document.id == document_id, Document.status == DOCUMENT_COMPLETE)
        .values(status=DOCUMENT_FAILED, failure_message=MSG_UNAVAILABLE, updated_at=func.now())
    )
    session.commit()


def _check_files(session, documents: list[Document]) -> list[Document]:
    """Cheap check: complete documents whose file is missing become `failed`, so they are never shown as ready."""
    directory = get_settings().documents_dir
    missing = [d.id for d in documents if d.status == DOCUMENT_COMPLETE and not file_exists(directory, d.file_path)]
    for document_id in missing:
        _mark_unavailable(session, document_id)
    if not missing:
        return documents
    return [_find(session, documents[0].trip_id, d.id) for d in documents]


def _live(session, trip_id: uuid.UUID) -> Document | None:
    return session.scalars(
        select(Document)
        .where(Document.trip_id == trip_id, Document.status.in_(DOCUMENT_LIVE_STATUSES))
        .options(defer(Document.snapshot))
        .execution_options(populate_existing=True)
    ).first()


# ---- Request, list, status ----


@router.post("/trips/{trip_id}/documents", status_code=201)
def request_document(trip_id: uuid.UUID, user: CurrentUser, session: SessionDep, response: Response) -> DocumentOut:
    _, role = get_trip_for_user(session, trip_id, user)
    require(can_edit(role), "You are not allowed to generate documents on this trip.")

    def existing() -> DocumentOut:
        live = _live(session, trip_id)
        if live is None:
            raise ApiError(409, "DOCUMENT_CONFLICT", "The document could not be requested. Please try again.")
        out = _outs(session, [live])[0]
        session.rollback()
        response.status_code = 200
        return out

    # A generation is already waiting or running: the same document, never a second one.
    if _live(session, trip_id) is not None:
        return existing()

    snapshot = build_snapshot(session, trip_id, user)
    document = Document(
        trip_id=trip_id,
        requested_by=user.id,
        status=DOCUMENT_WAITING,
        trip_version=snapshot.trip_version,
        snapshot=snapshot.data,
        snapshot_at=snapshot.taken_at,
        attempts=0,
    )
    session.add(document)
    try:
        session.commit()
    except IntegrityError:  # two requests at once: the database allows only one live document per trip
        session.rollback()
        return existing()
    return _outs(session, [_find(session, trip_id, document.id)])[0]


@router.get("/trips/{trip_id}/documents")
def list_documents(trip_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> list[DocumentOut]:
    _, role = get_trip_for_user(session, trip_id, user)
    require(can_read(role))
    documents = list(
        session.scalars(
            select(Document)
            .where(Document.trip_id == trip_id)
            .options(defer(Document.snapshot))
            .order_by(Document.created_at.desc(), Document.id)
        )
    )
    return _outs(session, _check_files(session, documents))


@router.get("/trips/{trip_id}/documents/{document_id}")
def get_document(trip_id: uuid.UUID, document_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> DocumentOut:
    _, role = get_trip_for_user(session, trip_id, user)
    require(can_read(role))
    document = _find(session, trip_id, document_id)
    return _outs(session, _check_files(session, [document]))[0]


# ---- Download and retry ----


def _file_name(document: Document) -> str:
    return file_stem(document.snapshot["trip"]["name"], document.trip_version, str(document.id)) + ".pdf"


@router.get("/trips/{trip_id}/documents/{document_id}/download")
def download_document(trip_id: uuid.UUID, document_id: uuid.UUID, user: CurrentUser, session: SessionDep):
    _, role = get_trip_for_user(session, trip_id, user)
    require(can_read(role))
    document = _find(session, trip_id, document_id, with_snapshot=True)
    if document.status != DOCUMENT_COMPLETE:
        session.rollback()
        raise ApiError(409, "DOCUMENT_NOT_READY", "This document is not ready to download.", {"status": document.status})
    directory = get_settings().documents_dir
    if not verify_file(directory, document.file_path, document.size_bytes, document.sha256):
        _mark_unavailable(session, document.id)
        raise ApiError(
            409, "DOCUMENT_UNAVAILABLE", MSG_UNAVAILABLE + " You can retry the generation.", {"status": DOCUMENT_FAILED}
        )
    path = resolve_path(directory, document.file_path)
    name = _file_name(document)
    session.rollback()
    return FileResponse(path, media_type="application/pdf", filename=name)


@router.post("/trips/{trip_id}/documents/{document_id}/retry")
def retry_document(trip_id: uuid.UUID, document_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> DocumentOut:
    _, role = get_trip_for_user(session, trip_id, user)
    require(can_edit(role), "You are not allowed to retry documents on this trip.")
    document = _find(session, trip_id, document_id, lock=True)
    if document.status != DOCUMENT_FAILED:
        session.rollback()
        raise ApiError(409, "DOCUMENT_NOT_FAILED", "Only a failed document can be retried.", {"status": document.status})
    # Same frozen snapshot: the document keeps the point in time it was requested at.
    document.status = DOCUMENT_WAITING
    document.failure_message = None
    document.file_path = None
    document.size_bytes = None
    document.sha256 = None
    document.attempts = 0
    document.started_at = None
    document.finished_at = None
    document.updated_at = func.now()
    try:
        session.commit()
    except IntegrityError:  # another document of this trip is being generated
        session.rollback()
        raise ApiError(409, "DOCUMENT_IN_PROGRESS", "Another document is being generated for this trip. Try again when it finishes.")
    return _outs(session, [_find(session, trip_id, document_id)])[0]
