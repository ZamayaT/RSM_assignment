# CLAUDE.md — Development Rules

Repository: RSM_assignment. Lightweight, change-driven workflow. No extra frameworks (no OpenSpec).

## Project Files (in `claude/`)
- `CLAUDE.md` — these rules (always follow).
- `PROJECT.md` — description, objectives, MVP scope, technologies, requirements. Read only when the task needs that context.
- `changes/` — one file per change (`changes/NN-short-name.md`). A change is one development step. Each file has a goal, scope, a checklist of small tasks, acceptance criteria, and a **Technologies implemented** section:
  ```
  - [ ] 1.1 Task description
  - [x] 1.2 Completed task
  ```
  - **Technologies implemented**: a simple list of the applications, dependencies, or important libraries added in that change, each with a one-line reason (why it is used / where). Keep it updated as tasks that add technologies are completed; list only what is actually implemented, and only new items (do not repeat ones from earlier changes).

## Workflow
1. **Plan**: When asked to define a change, create its file in `changes/` with the goal, scope, its tasks as `[ ]` checkboxes, acceptance criteria, and an empty **Technologies implemented** section.
2. **Approval**: Present a short plan and **wait for my explicit approval** before writing any code.
3. **Before each task**: Read the change file to confirm the task and see what is already done.
4. **Implement**: When I say "Implement X", work **only on X** (one task, or the whole change only if I name the change). Never start, prepare, or "while I'm here" fix other tasks unless I explicitly ask for multiple.
5. **Complete**: Tick the task `[x]` in the change file as soon as it is done. Report briefly.
6. **README**: `README.md` documents only what is already implemented. If a task changes setup, installation, requirements, configuration, ports, or run/test commands, update `README.md` in that same task (simple step description + copy-paste command). Never document planned features there.
7. Out-of-scope issues found along the way: mention them in one line; do not fix them.

## Assignment Folder
- `assignment/` is read-only reference material. Never modify, copy, move, or delete its files, and never make the application or mock read them at runtime.

## Token Efficiency
- Read only files relevant to the current task. Use Grep/Glob to locate code before reading; read line ranges for large files.
- Do not re-read `PROJECT.md` or re-analyze the project/codebase unless the task requires it or it changed.
- Do not re-read files you just edited.
- Do not repeat project analysis, summaries, or context I already know.
- Prefer small targeted edits over rewriting whole files.
- Avoid spawning subagents unless I ask.

## Communication
- Keep responses concise: no preamble, no restating the request, no long recaps.
- State what changed and what's next in a few lines. Ask questions only when blocked.

## Code Conventions
- Follow the technologies and requirements in `PROJECT.md`.
- Match existing code style; keep changes minimal and within MVP scope.
- Don't add dependencies, abstractions, or features not required by the task.
- Run relevant tests/build for the touched code before ticking a task; if not run, say so.

## Git
- Git is managed entirely by me. I create and switch branches, commit, merge, and push.
- Never run git commands that modify state (add, commit, push, merge, checkout/switch, branch, stash, reset, etc.).
- Work on whatever branch is currently checked out; it may change between tasks.
- Read-only commands (`git status`, `git diff`, `git log`) only when needed.
