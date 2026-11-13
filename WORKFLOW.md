---
max_concurrent: 1
max_turns: 15
max_cost_usd_per_task: 5.0
hooks:
  after_create: uv sync -q
validate:
  command: uv run pyright && uv run pytest -q -n auto
  timeout_s: 600
claude:
  model: sonnet
  allow:
    - Edit
    - Write
    - "Bash(uv run pyright:*)"
    - "Bash(uv run pytest:*)"
    - "Bash(git add:*)"
    - "Bash(git commit:*)"
    - "Bash(git status:*)"
    - "Bash(git diff:*)"
    - "Bash(git log:*)"
    # Moving text between files without retyping it, and checking the result.
    - "Bash(git grep:*)"
    - "Bash(diff:*)"
    - "Bash(wc:*)"
    - "Bash(sed -n:*)"
    # Deleting tracked files. Safe here: agents work in worktrees on a branch you review.
    - "Bash(git rm:*)"
    # Moving tracked files (the target directory must exist: create it by writing a file in it).
    - "Bash(git mv:*)"
    # Trying the CLI in a scratch repo. Not `samba run` (an orchestrator inside a worktree) and
    # not `work accept` (it merges into a real base branch); their --help is allowed.
    - "Bash(uv run samba --help)"
    - "Bash(uv run samba task:*)"
    - "Bash(uv run samba plan:*)"
    - "Bash(uv run samba question:*)"
    - "Bash(uv run samba dev:*)"
    # Read-only ADR commands. Not accept, reject or supersede: accepting is a human decision.
    - "Bash(uv run samba adr list:*)"
    - "Bash(uv run samba adr show:*)"
    - "Bash(uv run samba work reject:*)"
    - "Bash(uv run samba work --help)"
    - "Bash(uv run samba work accept --help)"
    - "Bash(uv run samba run --help)"
    - "Bash(mktemp:*)"
    - "Bash(git init:*)"
    - "Bash(cp WORKFLOW.md:*)"
  turn_timeout_s: 3600
  stall_timeout_s: 600
---
You are working on Samba itself.

Task: {{ task.title }}

{{ task.body }}

Start by reading CLAUDE.md (the repo map) and the chapters of docs/spec/ the task points to
(start at docs/spec/README.md). Write the tests for the new behavior first, at the lowest level
that can show it (ADR 0016: unit, component, integration, end-to-end), then the implementation.
Keep existing tests passing and pyright at 0 errors.

Which tests to run: while working, only `uv run pytest -q tests/unit tests/component tests/checks`
(about a second), plus `uv run pytest -q tests/integration` when you change an adapter or what it
reads or writes on disk. Do not run `tests/e2e` or the whole suite yourself: when you report done,
Samba runs the full validation (`uv run pyright && uv run pytest -q -n auto`, end-to-end level
included) and, if it fails, sends you the failing tail so you can fix it and go on.

Updating the spec is a step of every task, not an option. Before reporting done, make the edits
listed in the plan's "Spec changes" section in docs/spec/ on this branch (or, without a plan,
the edits your change needs), and say in your task file's `## Log` what changed. The spec diff is
reviewed next to the code diff at `work accept`. If the task made a real decision (a choice
between alternatives with a lasting reason), also propose an ADR in docs/adr/ with status
proposed, one decision per file, as in ADR 0001.

Commit messages: never add a Co-Authored-By trailer or any other attribution line.

Decisions that shape the architecture live in docs/adr/. Before designing, run
`uv run samba adr list` and read the relevant ones with `uv run samba adr show N`.
