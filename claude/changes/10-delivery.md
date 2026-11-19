# Change 10 — Delivery

Status: Done (all tasks complete)

## Goal
A reviewer can set up the project from a clean clone, understand the key decisions and guarantees, follow a demo of the main workflow and selected failure and concurrency scenarios, and see how AI was used and how its output was verified. Covers the deliverables 5 to 8 of `PROJECT.md` section 12 (README completeness, architecture note, demo walkthrough, AI usage and verification note) and a final consistency pass.

## Scope
- `README.md`: only what is implemented, plus the **proposed deployment approach** (a short outline: hosting, secrets, database backups, what to change for production).
- `docs/architecture.md`: short architecture note (key decisions, alternatives considered, guarantees, known limitations).
- `docs/demo.md`: demo walkthrough with copy-paste steps (main workflow, a supplier failure, an unknown booking outcome, two simultaneous saves, a permission denial, the assistant).
- `docs/ai-usage.md`: short AI usage and verification note (tools and models used, how `claude/` works, how the output was checked).
- A final consistency pass over `README.md`, `PROJECT.md`, `.env.example` and the change files.

## Out of scope
- New features, refactors or new dependencies.
- Actually deploying anywhere (the deployment approach is a proposal only).
- Frontend automated tests (documented limit in `PROJECT.md` section 11).
- `assignment/` is read-only reference and stays untouched.

## Assumptions to confirm
- The notes live in a new `docs/` folder and the README links to them (changeable to README sections if preferred).
- The deployment proposal is a concrete but short outline (about one page), not a full infrastructure design.
- The demo uses the seeded users (`alice`, `bob`, `carol`) and the mock's `/control` endpoints for the failure scenarios.
- The AI never uses the developer's API key: `python -m evals.assistant` is not run by it and no pass rate is claimed in the notes, which only describe how to run it.

## Tasks

### Documentation
- [x] 1.1 `docs/architecture.md`: components and how they talk, key decisions with the alternatives rejected, guarantees (idempotent bookings and recovery, optimistic locking, permissions on REST and MCP, document jobs and checksums, read-only assistant) and known limitations; every claim points to the code or test that shows it.
- [x] 1.2 `docs/demo.md`: demo walkthrough with copy-paste commands and expected results.
- [x] 1.3 `docs/ai-usage.md`: AI usage and verification note (tools, models, the `claude/` harness, what was checked by tests, evaluations and manual review).
- [x] 1.4 `README.md`: proposed deployment approach and links to `docs/`; keep it limited to what is implemented.

### Final checks
- [x] 2.1 Consistency pass: README, `PROJECT.md`, `.env.example` and change files match the implementation; leftover "planned" or "pending" wording removed; `assignment/` unchanged (`git status`/`git diff` read-only).
- [x] 2.2 Clean-run check: from a clean state (`docker compose down -v`, then `up --build`) the documented commands work: `pytest` (backend and mock), `ruff check .`, frontend `typecheck`, `evals.search`, and `evals.assistant` if a key is set; report the results.

## Acceptance criteria
- A reviewer following only the README gets the stack running and the tests passing.
- `docs/architecture.md` states each key decision, its alternative and each guarantee with where it is verified, and lists known limitations honestly.
- `docs/demo.md` can be followed step by step and shows the main workflow plus at least: a supplier failure, a concurrent save conflict, an unknown booking outcome and a permission denial.
- `docs/ai-usage.md` says which AI tools and models were used and how the output was verified, without overstating (the scripted-model tests are not evidence of assistant quality).
- No document describes something that is not implemented.
- `assignment/` is untouched.

## Technologies implemented
