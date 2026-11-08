# Implementation notes

- Python 3.11+, standard library plus PyYAML, managed with `uv`. Single package, `asyncio` for
  subprocesses. Child processes start in their own session (`start_new_session=True`) and are
  killed with `os.killpg` (SIGTERM, then SIGKILL after 5 s).
- One event loop owns all state changes; workers report back through it.
- Moves are `os.rename` within the same filesystem (atomic).
- The validate command for Samba's own code: `uv run pyright` (strict) and `uv run pytest`.
- A Rust rewrite is expected later. To keep the tests reusable, the main suite is **black-box**:
  it builds a temporary git repo, writes `WORKFLOW.md` and task files, runs the `samba` CLI as a
  subprocess with `--exit-when-idle`, and asserts only on files (task folders, sidecars, task `## Log`,
  branches, worktrees) and on the calls recorded by a fake `claude`. Nothing in it imports the
  Python package. Unit tests of Python internals are kept few.
- The fake `claude` (`tests/fake_claude.py`) follows a per-task script of steps (outcome, cost, file
  writes, commits, exit code, `is_error`, missing result, hang, malformed lines, permission denials,
  missing session on resume) and records each invocation's argv for assertions.
- Samba checks `claude auth status` at startup and refuses to start when logged out.
- Test-only knob: `SAMBA_DEBUG_FIRE_DELAY=<seconds>` makes `fire` sleep between the rename and
  the sidecar save, so black-box tests can make the race the repo lock covers (task-files, Write discipline) deterministic.

