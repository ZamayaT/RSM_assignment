"""Document files on the shared volume: write atomically, verify, clean up.

A file only gets its final name `<id>.pdf` after its content is on disk; until then it is `<id>.pdf.tmp`.
The database stores the relative path, size and SHA-256 so a lost or altered file is detected.
"""
import hashlib
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

TMP_SUFFIX = ".tmp"


@dataclass(frozen=True)
class StoredFile:
    path: str  # relative to the documents directory
    size: int
    sha256: str


def relative_path(document_id: uuid.UUID) -> str:
    return f"{document_id}.pdf"


def write_file(directory: str | Path, document_id: uuid.UUID, content: bytes) -> StoredFile:
    """Write to `<id>.pdf.tmp`, flush it to disk, then rename it to `<id>.pdf` (atomic on one volume)."""
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    final = root / relative_path(document_id)
    temporary = final.with_name(final.name + TMP_SUFFIX)
    with open(temporary, "wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, final)
    return StoredFile(final.name, len(content), hashlib.sha256(content).hexdigest())


def _resolve(directory: str | Path, path: str) -> Path | None:
    """The absolute file for a stored relative path; None if it would point outside the directory."""
    root = Path(directory).resolve()
    full = (root / path).resolve()
    return full if root in full.parents else None


def file_exists(directory: str | Path, path: str | None) -> bool:
    """Cheap check used by the list: the file is there."""
    if not path:
        return False
    full = _resolve(directory, path)
    return full is not None and full.is_file()


def verify_file(directory: str | Path, path: str | None, size: int | None, sha256: str | None) -> bool:
    """True only if the file exists and its size and SHA-256 equal the stored values."""
    if not path or size is None or not sha256:
        return False
    full = _resolve(directory, path)
    if full is None or not full.is_file() or full.stat().st_size != size:
        return False
    digest = hashlib.sha256()
    with open(full, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest() == sha256


def remove_stale_temporary_files(directory: str | Path, older_than_seconds: float, keep: set[str] | None = None) -> int:
    """Delete `*.pdf.tmp` files not modified for `older_than_seconds`, except names in `keep` (live jobs)."""
    root = Path(directory)
    if not root.is_dir():
        return 0
    removed = 0
    now = time.time()
    for entry in root.glob(f"*.pdf{TMP_SUFFIX}"):
        if keep and entry.name in keep:
            continue
        try:
            if now - entry.stat().st_mtime >= older_than_seconds:
                entry.unlink()
                removed += 1
        except FileNotFoundError:
            pass
    return removed
