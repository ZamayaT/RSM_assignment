"""Worker steps for documents: claim, render and store, recover. One function per step.

A document is only ever `complete` after its file is on disk under its final name and its size and SHA-256 are
saved in the same transaction. Claims use FOR UPDATE SKIP LOCKED, so two workers never render the same document.
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_engine
from app.document_render import render_pdf
from app.document_storage import TMP_SUFFIX, relative_path, remove_stale_temporary_files, write_file
from app.models import (
    DOCUMENT_COMPLETE,
    DOCUMENT_FAILED,
    DOCUMENT_IN_PROGRESS,
    DOCUMENT_WAITING,
    Document,
)

logger = logging.getLogger("app.documents")

MSG_GENERIC = "The document could not be generated. Please try again."
MSG_STORAGE = "The document file could not be stored. Please try again."
MSG_INTERRUPTED = "Generation was interrupted too many times."


def _now() -> datetime:
    return datetime.now(timezone.utc)


def claim_document(now: datetime | None = None) -> tuple[uuid.UUID, int] | None:
    """Step 1: take the oldest `waiting` document, mark it `in_progress` (attempts + 1) and commit.
    Returns (document id, attempt number), or None when nothing is waiting."""
    now = now or _now()
    with Session(get_engine(), expire_on_commit=False) as session:
        document = session.scalars(
            select(Document)
            .where(Document.status == DOCUMENT_WAITING)
            .order_by(Document.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        ).first()
        if document is None:
            return None
        document.status = DOCUMENT_IN_PROGRESS
        document.started_at = now
        document.attempts += 1
        document.updated_at = now
        session.commit()
        logger.info("document %s claimed (attempt %s)", document.id, document.attempts)
        return document.id, document.attempts


def _finish(document_id: uuid.UUID, attempt: int, **values) -> bool:
    """Set the end state, but only if this attempt still owns the document (it may have been reset and claimed
    again by someone else after being considered stuck)."""
    with Session(get_engine(), expire_on_commit=False) as session:
        result = session.execute(
            update(Document)
            .where(Document.id == document_id, Document.status == DOCUMENT_IN_PROGRESS, Document.attempts == attempt)
            .values(finished_at=_now(), updated_at=func.now(), **values)
        )
        session.commit()
        return result.rowcount == 1


def render_document(document_id: uuid.UUID, attempt: int) -> bool:
    """Steps 2 and 3: render from the stored snapshot, write the file, then (and only then) mark `complete`.
    Any error marks the document `failed` with a short message. Returns True when it ended `complete`."""
    try:
        with Session(get_engine(), expire_on_commit=False) as session:
            snapshot = session.scalar(select(Document.snapshot).where(Document.id == document_id))
        content = render_pdf(snapshot, str(document_id))
        stored = write_file(get_settings().documents_dir, document_id, content)
        done = _finish(
            document_id,
            attempt,
            status=DOCUMENT_COMPLETE,
            file_path=stored.path,
            size_bytes=stored.size,
            sha256=stored.sha256,
            failure_message=None,
        )
        if done:
            logger.info("document %s complete (%s bytes)", document_id, stored.size)
        return done
    except Exception as exc:
        logger.exception("document %s failed", document_id)
        message = MSG_STORAGE if isinstance(exc, OSError) else MSG_GENERIC
        _finish(document_id, attempt, status=DOCUMENT_FAILED, failure_message=message)
        return False


def process_next_document(now: datetime | None = None) -> bool:
    """Claim one waiting document and render it. Returns False when nothing was waiting."""
    claimed = claim_document(now)
    if claimed is None:
        return False
    render_document(*claimed)
    return True


def recover_stuck_documents(now: datetime | None = None) -> int:
    """`in_progress` for longer than the stuck window (the worker died or restarted): back to `waiting`, or
    `failed` once the maximum number of attempts is used up. Returns how many were touched."""
    now = now or _now()
    settings = get_settings()
    limit = now - timedelta(seconds=settings.document_stuck_seconds)
    with Session(get_engine(), expire_on_commit=False) as session:
        stuck = session.scalars(
            select(Document)
            .where(Document.status == DOCUMENT_IN_PROGRESS, Document.started_at < limit)
            .with_for_update(skip_locked=True)
        ).all()
        for document in stuck:
            if document.attempts >= settings.document_max_attempts:
                document.status = DOCUMENT_FAILED
                document.failure_message = MSG_INTERRUPTED
                document.finished_at = now
                logger.warning("document %s failed: interrupted %s times", document.id, document.attempts)
            else:
                document.status = DOCUMENT_WAITING
                logger.warning("document %s was stuck in progress: back to waiting", document.id)
            document.updated_at = now
        session.commit()
        return len(stuck)


def clean_temporary_files() -> int:
    """Delete temporary files older than the stuck window that no live job is writing."""
    with Session(get_engine()) as session:
        live = session.scalars(select(Document.id).where(Document.status == DOCUMENT_IN_PROGRESS)).all()
    keep = {relative_path(i) + TMP_SUFFIX for i in live}
    removed = remove_stale_temporary_files(get_settings().documents_dir, get_settings().document_stuck_seconds, keep)
    if removed:
        logger.info("removed %s stale temporary document file(s)", removed)
    return removed


def run_documents_once(now: datetime | None = None, limit: int = 20) -> int:
    """One worker pass for documents: recover, clean, then render what is waiting (bounded)."""
    recover_stuck_documents(now)
    clean_temporary_files()
    done = 0
    while done < limit and process_next_document(now):
        done += 1
    return done
