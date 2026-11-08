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
  turn_timeout_s: 3600
  stall_timeout_s: 600
---
You are working on Symphony itself.

Task: {{ task.title }}

{{ task.body }}

Start by reading CLAUDE.md (the repo map) and the parts of SPEC.md the task points to. Write the
black-box tests for the new behavior first, then the implementation. Keep existing tests passing and
pyright at 0 errors. Update SPEC.md in the same change if your implementation had to settle a detail
the spec left open, and say so in your task file's `## Log`.
