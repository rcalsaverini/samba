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

## Verified Claude Code behavior (2.1.220, 2026-11-06)

Tested with throwaway repos and `--model haiku`:

- `-p --output-format stream-json` errors without `--verbose`.
- `--session-id <uuid>` sets the id; reusing an id errors ("already in use"); `--resume <id>` from a
  new process (and a different cwd) keeps conversation memory; unknown id gives exit 1,
  `subtype: error_during_execution`, stderr "No conversation found".
- `result.total_cost_usd` is per invocation.
- An auth failure gives exit 1, `is_error: true`, but `subtype: "success"`.
- `--add-dir <dir>` allows reading and editing files there; without it reads are denied.
- `--append-system-prompt` and the repo `CLAUDE.md` both apply in `-p` mode.
- Claude Code's built-in prompt makes the agent treat commits as needing the user's request, even
  with user config isolated; the protocol prompt must authorize commits explicitly.
- `--permission-mode dontAsk`: disallowed calls are denied, the run continues and exits 0, denials
  are listed in `result.permission_denials`, and the agent does not try to work around them.
- `permissions.allow` in the repo's `.claude/settings.json` is ignored in untrusted folders (stderr
  warning); `--allowedTools` and `--settings` allow rules are honored.
- `--json-schema` returns the parsed object in `result.structured_output`.
- Isolation results: see running-claude, User config isolation.
- Ancestor memory files (2026-11-07): run from a folder under `$HOME` with
  `--setting-sources project,local --strict-mcp-config`, the agent still saw a rule that exists
  only in `~/.claude/CLAUDE.md`; run from a folder under `/tmp`, it did not. Adding
  `--settings '{"claudeMdExcludes": [<each ancestor's CLAUDE.md, CLAUDE.local.md,
  .claude/CLAUDE.md>]}'` removed the user rule while the folder's own `CLAUDE.md` still loaded.
  `claudeMdExcludes` accepts absolute paths and globs.
- Read-only planning (planning, The planning run): `--permission-mode plan` runs headless without hanging, but its Write
  tool still succeeds by redirecting to `~/.claude/plans/<name>.md` (a file in the user's home), and
  it switched to a different model than `--model` asked for (17x the cost in the test).
  `dontAsk` with `--allowedTools Read Grep Glob` denies writes, still auto-allows read-only shell
  commands (`git log`, `git status`, `ls`), honors `--model`, and returns structured output.

