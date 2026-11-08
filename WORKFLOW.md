---
max_concurrent: 1
max_turns: 15
max_cost_usd_per_task: 5.0
hooks:
  after_create: uv sync -q
validate:
  command: uv run pyright && uv run pytest -q
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
    # Trying the CLI in a scratch repo. Not `samba run` (an orchestrator inside a worktree) and
    # not `work accept` (it merges into a real base branch); their --help is allowed.
    - "Bash(uv run samba --help)"
    - "Bash(uv run samba task:*)"
    - "Bash(uv run samba plan:*)"
    - "Bash(uv run samba question:*)"
    - "Bash(uv run samba dev:*)"
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
(start at docs/spec/README.md). Write the black-box tests for the new behavior first, then the
implementation. Keep existing tests passing and pyright at 0 errors. Update the spec in docs/spec/ in the same change if your implementation had to settle a detail
the spec left open, and say so in your task file's `## Log`.
