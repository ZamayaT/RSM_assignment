# Change 08 — Documents

Status: Proposed

## Goal
An organizer or editor can generate a downloadable PDF summary of the trip (itinerary, costs and booking statuses) without blocking the application. The document is prepared in the background by the worker, its status (waiting, in progress, complete, failed) is always visible and is restored after a reload, and every participant can download completed documents. A document states which trip information and point in time it represents, and later edits never change it. Interrupted work, repeated requests, a lost file or a corrupted file never leave a document falsely reported as ready, and a failed generation can be retried. Covers FR-30 to FR-35, US-09, US-10 and the "Documents" view (`PROJECT.md` 4.10), and it is the second use of the background worker.

## Scope
- Backend (`backend/`): `documents` table (migration), request, list, status, download and retry endpoints, the trip snapshot, PDF rendering with ReportLab, file storage on a shared volume with checksum verification, and document steps in the existing worker (claim, render, recover stuck jobs, clean temporary files).
- Frontend (`frontend/`): a **Documents** tab in the trip workspace (generate, history, download, retry, automatic status updates) and the latest document status in the left info card.
- Docker Compose: a shared `documents_data` volume for `backend` and `worker`; configuration in `.env.example`.
- Tests for the guarantees below and README updates.

## Out of scope
- Other formats (only PDF), templates, branding, previews, emailing or sharing outside the participants.
- Deleting documents or retention rules: every generation is kept (a documented limit: the volume grows).
- Object storage (S3 and similar), virus scanning, encryption at rest.
- Documents for several trips at once; documents that include assistant conversations (change 9).
- Frontend automated tests (documented limit in `PROJECT.md` section 11); the frontend is checked manually.
- `assignment/` is read-only reference. The provider mock is not involved (the document is built from the application's own data; no provider call).

## Decisions already made (`PROJECT.md` 8.2)
PDF with ReportLab (pure Python); PostgreSQL job table plus the existing worker (`SELECT ... FOR UPDATE SKIP LOCKED`; stuck `in_progress` rows are reset to `waiting`); files on a local disk volume written to a temporary path and renamed when complete; path, size, SHA-256 checksum and status stored in PostgreSQL; a frozen JSON snapshot taken at request time with the trip `version`, timestamp and generating user; all generations kept as history visible to every participant; polling for status updates.

## Assumptions to confirm
- **Who and where**: organizer and editor generate and retry (`403` for viewers, `404` for non-participants, `401` without login); every participant lists, reads the status of and downloads documents. Endpoints: `POST /trips/{id}/documents`, `GET /trips/{id}/documents`, `GET /trips/{id}/documents/{docId}`, `GET /trips/{id}/documents/{docId}/download`, `POST /trips/{id}/documents/{docId}/retry`. Permissions use the same helpers as the other trip endpoints.
- **Snapshot, taken before answering**: the request reads the trip, itinerary items (in order, with status and warnings), the budget totals (the existing pure `Decimal` functions) and the latest booking attempt per item inside one transaction, with the trip row locked `FOR SHARE` so the saved `version` matches the content, then stores it as JSON in the `documents` row (status `waiting`) and answers `201` immediately. The PDF is rendered only from this snapshot, never from live data, so later edits and later price or booking changes cannot alter it. Money stays in decimal strings.
- **One live generation per trip**: enforced by the database (a unique index over documents in `waiting` or `in_progress`). A second request while one is live returns `200` with that existing document instead of creating another, so a double click or a repeated request never queues duplicates. Once it finishes (complete or failed), a new request creates a new document with a new snapshot.
- **Document content**: first line "Generated at <UTC time> by <user> from trip version N"; trip name, dates, destinations, travelers and budget; itinerary table (position, title, category, destination, schedule in UTC, cost, status label, warnings); costs (estimated, confirmed, combined, remaining or over budget, each item marked estimate or confirmed with its accepted price); bookings (latest attempt per item with status and accepted price, so unknown or pending outcomes are stated as such, never as confirmed); a short note that prices are estimates unless confirmed and that the document is a snapshot. Page numbers and the document id in the footer.
- **Retry reuses the snapshot**: retrying a failed document re-renders from the same frozen snapshot (same point in time); it does not take a new one. To represent newer data the user generates a new document.
- **Worker steps** (same process and loop as the booking steps, same claim pattern):
  1. Claim the oldest `waiting` document, set `in_progress`, record `started_at` and increase `attempts`, commit.
  2. Render the PDF to a temporary file in the documents directory (`<id>.pdf.tmp`), flush it to disk, compute size and SHA-256, then rename it to `<id>.pdf` (atomic on the same volume).
  3. In one transaction set `complete` with relative path, size, checksum and `finished_at`. Any exception sets `failed` with a short, user-safe message (details go to the log with the document id).
  - Rendering and the file are never visible as "complete" before step 3.
- **Stuck and interrupted jobs**: an `in_progress` document older than `DOCUMENT_STUCK_SECONDS` (default 120) goes back to `waiting` (the worker died or restarted); after `DOCUMENT_MAX_ATTEMPTS` (default 3) it becomes `failed` ("Generation was interrupted too many times") so it cannot loop forever. A restart of any service therefore never loses a request or leaves it in progress forever. Temporary files older than the stuck window with no live job are deleted at the start of a pass.
- **Download is verified**: before sending, the backend checks that the file exists and that its size and SHA-256 equal the stored values. If not, it does not send it: the document is marked `failed` ("The stored file is missing or does not match its checksum") and the response is `409 DOCUMENT_UNAVAILABLE`; the user can click **Retry**, which re-renders from the snapshot. The list endpoint also checks that complete documents still have their file (existence only, cheap) and marks missing ones `failed`, so a missing file is never shown as ready. The download is streamed with `Content-Disposition` and a name like `trip-<slug>-v<version>-<yyyymmdd-hhmmss>.pdf`. It requires the usual bearer token, so the browser downloads it with an authenticated request and saves the result (no token in the URL).
- **Status values**: `waiting`, `in_progress`, `complete`, `failed`; `failed` carries a message. `complete` is only ever set by the worker after the verified rename. The status of a document comes only from the database, so a reload or reconnect restores it.
- **Trip changed since**: each document shows its trip version; the Documents tab says "The trip has changed since this document" when the current trip version is higher, so nobody mistakes an old document for the current plan (the booking statuses change without bumping the version, so the note is about the plan, and the generation time is always shown).
- **Fonts and characters**: ReportLab's built-in Helvetica (covers Western European characters). Characters outside it (for example some notes written in other scripts) are replaced by `?` and this is documented as a limit; no font files are added. PDF page compression is turned off, so tests can check the text in the file without a PDF-reading library (files are small).
- **Storage**: the `documents_data` named volume is mounted at `/data/documents` in both `backend` and `worker` (`DOCUMENTS_DIR`). Only relative paths are stored in the database. `docker compose down` keeps documents; `docker compose down -v` deletes them with the database (the README says so).
- **Trip version**: requesting, rendering and retrying documents do not change the trip `version` (like bookings), so they never cause edit conflicts.
- **Tab position**: the new tab goes after Bookings: Itinerary, Budget, Bookings, **Documents**, Search, Participants.

## Tasks

### Data and storage
- [x] 1.1 Add ReportLab to `backend/requirements.txt`; settings (`DOCUMENTS_DIR`, `DOCUMENT_STUCK_SECONDS`, `DOCUMENT_MAX_ATTEMPTS`) in `config.py` and `.env.example`; `documents_data` volume mounted in `backend` and `worker` in `docker-compose.yml`.
- [x] 1.2 Migration and model for `documents` (id, trip, requested-by user, status, trip version, snapshot JSON, snapshot time, relative file path, size, SHA-256, failure message, attempts, `started_at`, `finished_at`, timestamps); a unique index for one live (`waiting` or `in_progress`) document per trip.

### Snapshot and rendering
- [x] 2.1 Snapshot builder: one transaction with the trip row locked `FOR SHARE`, reusing the existing itinerary, budget and bookings read code; JSON-safe and immutable once stored.
- [x] 2.2 PDF renderer (a pure function from snapshot to bytes): header line with time, user and trip version, trip data, itinerary, costs with estimate or confirmed, booking statuses, footer; unsupported characters replaced.
- [x] 2.3 File storage helpers: write to a temporary path, flush, compute SHA-256 and size, atomic rename; verify (exists, size, checksum); remove stale temporary files.

### API
- [x] 3.1 `POST /trips/{id}/documents` (organizer, editor): snapshot, `waiting` row, `201`; an existing live document returns `200` with it. `GET /trips/{id}/documents` (history, newest first, with who, when, trip version, status, failure message, size) and `GET .../{docId}` (status), for every participant; the list marks complete documents whose file is missing as `failed`.
- [x] 3.2 `GET .../{docId}/download` (every participant; only `complete`; verified; `409 DOCUMENT_UNAVAILABLE` and `failed` on a mismatch; a document that is not complete is refused with a clear error) and `POST .../{docId}/retry` (organizer, editor; only `failed`, back to `waiting` on the same snapshot).

### Worker
- [x] 4.1 Worker steps for documents next to the booking steps: claim `waiting` with `FOR UPDATE SKIP LOCKED`, render and store, mark `complete` or `failed`; one function per step so tests can run them without sleeping; logs carry the document id.
- [x] 4.2 Recovery: reset stuck `in_progress` documents to `waiting`, fail them after the maximum attempts, delete stale temporary files; the worker's startup and shutdown messages mention both jobs.

### Frontend
- [ ] 5.1 API calls and the **Documents** tab `/trips/:id/documents` (placed after Bookings): "Generate document" for organizer and editor, history table (who, when, trip version, status chip, failure message), "Download" for complete documents through an authenticated request that saves the file, "Retry" for failed ones (organizer and editor only), the "trip has changed since this document" note, loading, error and empty states.
- [ ] 5.2 Automatic status updates: polling every ~3 s while any document is `waiting` or `in_progress` (also after a reload), with messages that explain each state; a download refused with `DOCUMENT_UNAVAILABLE` shows why and refreshes the list. The workspace's left card shows the latest document status and refreshes after a generation (the tab calls the workspace `refresh()`).

### Tests and documentation
- [ ] 6.1 Generation flow tests: request returns `waiting` immediately, the worker step produces a valid PDF (`%PDF` header, `%%EOF`, stored size and checksum equal the file), `complete` only after the file exists; a repeated or simultaneous request returns the same live document and creates one row; failure (for example an unwritable directory) ends as `failed` with a message and Retry completes it from the same snapshot.
- [ ] 6.2 Snapshot tests: editing the itinerary, changing a price or confirming a booking after the request does not change the document's content; the PDF states the trip version and time; costs and booking statuses match the snapshot (a pending or unknown booking is never shown as confirmed).
- [ ] 6.3 Recovery and integrity tests: an `in_progress` document older than the stuck window is reset and then completed; after the maximum attempts it fails; two workers never render the same document (two sessions claiming at once); a deleted file and a modified file are both detected (download refused, document `failed`, Retry works); a leftover temporary file never makes a document `complete` and is cleaned up; a restart of the worker loses no request.
- [ ] 6.4 Permission tests: viewer `403` on generate and retry, non-participant `404` on every endpoint including download, no login `401`, every participant can list and download a complete document.
- [ ] 6.5 Update `README.md` (generate and download a document, the `worker` service also builds documents, the documents volume and `down -v`, how to try a failed generation, a stuck job and a corrupted file with copy-paste commands, the character and growth limits, and `docker compose down` when finished; only what is implemented) and `PROJECT.md` (4.4 and 4.10 wording if anything differs from what was built; section 10 stays the same).

## Acceptance criteria
- In the browser, in the **Documents** tab, an organizer or editor clicks **Generate document**; the page answers at once with a "Waiting" or "In progress" row, keeps using the application, and the row becomes **Complete** by itself; **Download** saves a PDF that shows the itinerary, the costs (estimated, confirmed, total and remaining) and the booking statuses, headed by "Generated at <time> by <user> from trip version N".
- Reloading the page, or opening it as another participant, shows the same history and statuses; viewers see the history and can download, but have no **Generate document** or **Retry**.
- After editing the itinerary or confirming a booking, a document generated earlier still shows the old content and says it was generated from an older trip version; a new document shows the new content.
- Clicking **Generate document** twice quickly, or two editors doing it at once, creates one document in progress, not two.
- If the worker stops while a document is in progress, it is picked up again after the stuck window and completes (or fails with an explanation after the maximum attempts); it never stays "In progress" forever and is never shown as ready without a file.
- If a generated file is deleted or altered on the volume, **Download** refuses it with an explanation, the document becomes **Failed**, and **Retry** produces a valid file.
- A non-participant gets `404` on every document endpoint, and a viewer gets `403` on generate and retry; the backend rejects these even when called directly.
- Every guarantee above is verified by tests run with `docker compose exec backend pytest`; the booking and itinerary tests still pass.
- `assignment/` is untouched.

## Technologies implemented
- ReportLab (Python): renders the PDF in the worker, pure Python with no system dependencies.
- `documents_data` Docker volume: shared by `backend` and `worker` to store the generated PDFs.
