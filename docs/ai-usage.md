# AI usage and verification note

## What was used

- **Claude Code** (Anthropic's CLI and VS Code extension) wrote most of the code, tests and documents, working from change files agreed with the developer. Models: Claude Sonnet 5.5 and Claude Opus 5.5, both at medium effort.
- **The assistant's own model** is not a development tool: a real model through an OpenAI-compatible API (OpenRouter free model by default), configured in `.env`.

## The harness (committed in `claude/`)

- `claude/CLAUDE.md`: the rules the agent follows: plan a change and wait for approval, implement only the named task, tick it when done, keep `README.md` limited to what is implemented, never touch `assignment/`, no git commands that change state (the developer commits), small targeted edits, concise reports.
- `claude/PROJECT.md`: requirements, decisions, architecture, testing strategy and the build plan.
- `claude/changes/NN-*.md`: one file per development step with goal, scope, tasks as checkboxes, acceptance criteria and the technologies added. Each change was approved before any code was written.

Workflow: the developer defines a change, approves the plan, then says "Implement X" for a task or a whole change; the agent reads the change file, implements only that, runs the relevant checks, ticks the task and reports.

## How the output was verified

- **Tests**: `docker compose exec backend pytest` (342 tests) and `docker compose exec mock_provider pytest` (125), against a separate test database and the real mock over HTTP. They cover permissions on REST and MCP, optimistic locking, budget exactness, idempotent bookings and recovery, document jobs, search states and the read-only assistant layer.
- **Static checks**: `ruff check .` in both Python services and `npm run typecheck` in the frontend.
- **Deterministic evaluation**: `docker compose exec backend python -m evals.search` (10 cases, no model).
- **Developer review** of each plan and result, and manual use of the frontend (it has no automated tests).
- Results of the checks above were run again at the end of change 10 and all passed.

## What is not evidence

- The assistant tests use a **scripted** model; they prove our code (tool execution, step limit, permissions, error mapping, nothing written), not that a real model recommends well.
- The model-dependent evaluation (`python -m evals.assistant`) was run **once** (2026-11-19, `nvidia/nemotron-3-ultra-550b-a55b:free`, 1 run per scenario): 4 of 4 graded runs passed (cheapest-within-budget, nothing-suitable, provider-down, one-supplier-down), and the other 3 scenarios (book-request, itinerary-and-budget, over-budget) were **not evaluated** because the free daily limit (`free-models-per-day`) was reached. This is a small, single-run sample, not a pass rate for the whole suite; free models are inconsistent, so rerun it with `--runs 3` after the limit resets.
- The frontend was not tested automatically, and AI-written UI was checked only by manual use.

## Risks of AI-written code that were handled

- Tool results are treated as data, never instructions (system prompt), and the tools are read-only anyway.
- The model never chooses the user: tools take the identity from the bearer token, and the endpoint rejects any other `trip_id`.
- The API key is read only from the environment, is never printed or logged, and is not in the repository (`.env` is ignored).
