# Symphony

Local orchestrator that runs Claude Code headless on markdown task files, one git worktree per task.

## Map

- `SPEC.md`: the source of truth for behavior. Read the sections relevant to your task before
  changing code, and update the spec in the same change when behavior changes.
- `src/symphony/`
  - `cli.py`: `run`, `status`, `new`, `task list|show` (aliases `list`, `show`) commands.
  - `views.py`: read-only shared helpers: table printer, state-prefix matcher, task id resolver
    (`resolve_task_id`, reused by every command taking an id), `task show` renderer.
  - `config.py`: loads and validates `WORKFLOW.md` (front matter + prompt body).
  - `tasks.py`: folder-based task store, `## Log` editing, sidecar state (`Sidecar`).
  - `orchestrator.py`: poll loop, dispatch, workers, retries, transitions.
  - `transitions.py`: the transition table (plain data) and `Machine.fire`, the only path that moves
    a task (SPEC §4.1). `symphony transitions` prints it; SPEC embeds the output.
  - `lock.py`: `repo_lock`, the `.symphony/lock` flock shared by commands and orchestrator ticks.
  - `deps.py`: `depends_on` evaluation (SPEC §15).
  - `claude.py`: builds the `claude` argv, runs it, parses stream-json (`RunResult`).
  - `workspace.py`: git worktrees outside the repo; `proc.py`: subprocess helpers (process groups).
  - `prompts.py`: built-in prompts, the protocol prompt, the outcome schema.
  - `template.py`: strict `{{ name }}` rendering.
- `tests/`
  - `test_blackbox.py`: the main suite. It runs the `symphony` CLI as a subprocess and asserts only
    on files and on calls recorded by the fake. **It must never import the `symphony` package**:
    the suite is meant to be reused unchanged against a future rewrite in another language.
  - `conftest.py`: the `Sandbox` fixture (temp git repo, WORKFLOW.md, tasks, helpers).
  - `fake_claude.py`: scripted fake of the `claude` CLI. Standard library only.

## Checks

Run these as separate, plain commands (no pipes or `&&`):

- `uv run pyright` (strict mode, must report 0 errors)
- `uv run pytest -q` (about 25 seconds)

## Conventions

- Python 3.11+, fully typed; no `Any` leaking into public signatures, use `cast` at JSON/YAML
  boundaries.
- New behavior gets a black-box test first, in the style of the existing ones.
- Prose in docs and prompts: no em-dashes.
