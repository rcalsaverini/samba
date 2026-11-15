# Implementation notes

- Python 3.11+, standard library plus PyYAML, managed with `uv`. Single package, `asyncio` for
  subprocesses. Child processes start in their own session (`start_new_session=True`) and are
  killed with `os.killpg` (SIGTERM, then SIGKILL after 5 s).
- One event loop owns all state changes; workers report back through it.
- Moves are `os.rename` within the same filesystem (atomic).
- The validate command for Samba's own code: `uv run pyright` (strict) and `uv run pytest`.
- A Rust rewrite is expected later. The tests are in four levels (ADR 0016, architecture chapter,
  Test levels): most are unit and component tests in-process, and the small end-to-end level is the
  part that carries over to a rewrite: it builds a temporary git repo, writes `WORKFLOW.md`, runs
  the `samba` CLI as a subprocess (`SAMBA_CMD` replaces it), and asserts only on files, exit codes,
  output and the calls recorded by a fake `claude`. Nothing in it imports the Python package. The
  scenario files of ADR 0012 carry over too.
- The fake `claude` (`tests/fakes/fake_claude.py`) follows a per-task script of steps (outcome, cost, file
  writes, commits, exit code, `is_error`, missing result, hang, malformed lines, permission denials,
  missing session on resume) and records each invocation's argv for assertions.
- Samba checks `claude auth status` at startup and refuses to start when logged out.
- Test-only knob: `SAMBA_DEBUG_FIRE_DELAY=<seconds>` makes `MarkdownTasks.save` sleep between the rename and
  the sidecar write (so a transition's save is slow, not `Machine`), so a test can make the race the repo lock covers (task-files, Write discipline) deterministic. No test uses it since the suite was rewritten; the lock is tested directly (`tests/integration/test_lock_port.py`).

