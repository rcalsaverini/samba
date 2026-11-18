---
priority: 2
depends_on: [task-list-and-show-commands]
---
# Plan accept reject and work reject commands

Phase 2, first state-changing commands. They establish the pattern the other transition commands
follow: resolve the task, perform any effect outside Symphony, then fire the table event.

Read first: `docs/command-ideas.md` sections 5.1, 5.2, 5.3 and 6.3; SPEC §3.3 (write discipline),
§4.1 (table and observed hand moves), §11; `src/symphony/transitions.py` (`Machine.fire`) and the
id resolver from the `task list` task.

Decisions already made by the human:

- `symphony plan accept <id>`, `symphony plan reject <id>`, `symphony work reject <id>`.
- Table rows only change Symphony's own state. A command performs any outside effect (here:
  writing feedback text into the task file) and then fires the event through `Machine.fire`.
  There is no second path that moves tasks.
- Wrong state: exit code 1, no change, and print the legal human events for the task's current
  state (from the table). Usage errors: exit code 2.
- Each command prints the task file's new path.

Scope:

- `plan reject` and `work reject` take `--feedback TEXT`, or `--edit` to write it in `$EDITOR`.
  Feedback is a shared primitive (`task feedback` may become a command later): it appends to the
  task's `## Feedback` section under a new `### Round N` heading, creating the section if needed,
  so the agent can tell new feedback from old. Rejecting without any feedback is allowed but
  prints a warning.
- `work reject --fresh`: also clear the execution `session_id`, so rework starts a fresh session
  that reads the task file instead of resuming a long, expensive conversation. This needs either a
  table effect on a separate row or event, or a documented exception; the plan should propose the
  cleanest option in the table's terms.
- **Concurrency with a running orchestrator.** Commands run in a separate process while
  `symphony run` may be ticking. Today `observe()` compares each file's folder with the sidecar's
  `state` and treats differences as hand moves. Design the handoff so a command's move is never
  misread (for example applied twice, or reversed as illegal) whatever the timing. Possible
  directions: a lock file under `.symphony/`, an ordering of rename and sidecar write whose
  intermediate states `observe()` interprets correctly, or making `observe()` treat the effects as
  idempotent. Explain the choice and test it (a test with `symphony run` active while the command
  runs).

Acceptance criteria:

- Black-box tests for each command: success path (folder, sidecar effects, `## Log` line naming the
  event), wrong-state refusal with the legal events listed, feedback rounds appended correctly on
  repeated rejects, `--edit` with a fake `$EDITOR`, `--fresh` clearing the session, the
  concurrency test, and the id prefix resolver.
- SPEC §11 documents the commands and the command pattern ("outside effect, then fire").
- `uv run pyright` reports 0 errors and `uv run pytest -q` passes.

## Plan
### Approach

**Command pattern (documented in SPEC §11):** resolve id → take the repo lock → verify the task's folder has a human row for the event (else exit 1 and list the legal events) → perform the outside effect (write feedback into the task file) → `Machine.fire(...)` → print the new path. No command touches the folder or sidecar except via `fire`.

**Findings from reading the code**
- (Edited at review: the `task list`/`show` task has landed on this branch.) Reuse
  `views.resolve_task_id(store, text)` for ids and `transitions.human_events(src, side)` for the
  legal events. Do not add `resolve_id` or `legal_human_events`; extend the existing helpers if
  something is missing. The `views.py` table printer is also available.
- `Machine.fire` does rename, then sidecar save, then `## Log` line. `Orchestrator.observe()` (orchestrator.py:190) runs between those steps in the other process. The task is then in folder X while `sidecar.state` is still the old folder. `human_row(src, dst)` matches the command's own move (for example `plan-review -> work-todo`), so it is applied a second time as an "observed hand move". The effects run twice, a duplicate Log line is added, and the command's later `sidecar.save` clobbers the observer's write.
- Reordering alone does not fix this. Writing the sidecar `state` first makes observe see a reverse move (`work-todo -> plan-review`, an illegal move that gets renamed back). Rename first gives the double application above.

**Concurrency choice: an advisory lock file `.symphony/lock` (`fcntl.flock`).**
- Every state-changing command holds it, blocking with a timeout of about 10 s (exit 1 with a message if it times out), for its whole resolve → check → feedback → `fire` section.
- `Orchestrator.observe()` takes it **non-blocking**. If a command holds it, skip the observe pass this tick and run it next tick. The loop never stalls, and a hand `mv` is only delayed by one tick.
- Why this choice: ordering tricks leave an intermediate state that `observe()` must guess about. Making observe idempotent would need a "pending command" marker, which is a lock by another name. The lock is about 20 lines, is correct for any timing, and is easy to port to Rust (flock exists there too).
- Narrow the claim: the orchestrator's own `fire` calls only touch todo and running tasks, and commands here only act on `*-review` tasks, so `observe()` is the only reader that can see a half-done command move. Say this in SPEC §3.3/§4.1. Hand moves (plain `mv`) stay lock-free and are still observed as before.
- Put the lock helper in a new small module `src/symphony/lock.py` (`repo_lock(symphony_dir, *, blocking, timeout)`, a context manager). Standard library only.
- Test hook: an env var `SYMPHONY_DEBUG_FIRE_DELAY` (seconds) makes `Machine.fire` sleep between the rename and the sidecar save when set. This makes the race deterministic in black-box tests without importing the package. Document it in SPEC §12 as a test-only knob. If you prefer no hook, the fallback test is to hold the lock from the test process via `fcntl.flock` (see tests).

**`--fresh` in the table's terms: a separate human event `work.reject_fresh`.**
- Add a row `_t("work-review", "work.reject_fresh", H, "work-todo", "", "session_id=None")` after `work.reject`. `"session_id=None"` already exists in `EFFECTS` (used by `plan.accept`), so no new effect is needed.
- `work.reject` stays first, so `human_row(work-review, work-todo)` still resolves a hand `mv` to the plain `work.reject` (no session reset), as today.
- `reject_fresh` is a command-only event that observation never selects. It needs no exception to "rows only change Symphony state". Note in SPEC §4.1 that it exists only for the command.
- Check that no test or doc generator assumes one human row per (src, dst) pair. The SPEC transition table is generated by `symphony transitions`, so regenerate the embedded block between the `<!-- transitions:begin/end -->` markers. A test likely guards that.
- Plan sessions: `plan reject` leaves `plan_session_id` alone (resuming the planning conversation is cheap). `--fresh` is not offered for `plan reject` and is out of scope.

**Feedback primitive** (`tasks.py`, reusable later by `task feedback`)
- `append_feedback(text, task_id)`: find `## Feedback` (create it before `## Log` if missing, mirroring `replace_section`). N = (number of existing `### Round <n>` headings in that section) + 1. Append `### Round N` followed by the text, separated by a blank line. Demote `#`/`##` headings in the text with `_demote`. Never rewrite earlier rounds.
- Give it a pure function (`append_to_feedback_section(text, body)`) plus a `TaskStore.append_feedback` wrapper, like `append_log`.
- Source of the text: `--feedback TEXT`, or `--edit`, which opens `$EDITOR` (`shlex.split`, falling back to `VISUAL`, then `vi`) on a temp file. Strip trailing blank lines and drop `#`-less template noise: use an empty file, no template. Providing both `--feedback` and `--edit` is a usage error (exit 2, argparse mutually exclusive group). If the editor exits non-zero, abort with exit 1 and change nothing.
- Empty or no feedback: allowed, add no Round heading, print a warning to stderr (`warning: rejecting without feedback`), still fire.
- Order inside the lock: check state, write feedback, fire. If `fire` returns False (a race with a hand move), print an error, exit 1, and say that the feedback was already written. Avoid this window by re-checking the folder right before fire, which is inside the lock anyway.
- Log line: `fire(..., message="feedback round N")` gives `plan.reject: plan-review -> plan-todo: feedback round N`. This names the event.

**CLI details** (`cli.py`)
- Nested subparsers: `plan {accept,reject}`, `work {reject}` (leave room for `work accept` later). Each takes `<id>` and `--repo`. `reject` takes `--feedback`/`--edit`; `work reject` also takes `--fresh`.
- Ids: `views.resolve_task_id` (exact id wins, then unique prefix; unknown or ambiguous is exit 2
  with candidates). Same behavior as `task show`.
- Legal events: `transitions.human_events(state, side)`, the same helper `task show` uses, so the
  two lists can never disagree. Keeping `work.reject_fresh` in the listing is fine.
- Wrong state: exit 1, stderr `<id> is in <state>; <event> not allowed. Legal events: a, b` (or `none` for running, done and similar states). No file or sidecar change.
- Success: print only the new path of the file (stdout), exit 0.
- Config errors keep the existing exit 2.
- Exit codes: 0 ok, 1 wrong state / lock timeout / editor failure, 2 usage / unknown or ambiguous id.

**SPEC updates (same change)**
- §11: add the three commands with flags, the exit codes, the command pattern ("resolve, outside effect, then fire; never a second path that moves tasks"), the lock, and the id-prefix rules.
- §3.3: Symphony also writes a task file on behalf of a human command, only for tasks in review folders (no agent runs there), and the repo lock.
- §4.1: the `work.reject_fresh` row (regenerate the embedded table), plus the sentence that `observe()` skips its pass while the lock is held.
- §12 (or §10): the debug delay env var, if added.
- Add a `## Log` line to the task file saying SPEC settled these details.
- `CLAUDE.md` map: add `lock.py`; no em-dashes in prose.

### Steps
- [ ] Read SPEC §3.3, §4.1, §11, §12 once more at the start, and `src/symphony/views.py`
  (`resolve_task_id`) and `transitions.human_events`, which this task reuses.
- [ ] Write black-box tests first (tests/test_blackbox.py, CLI subprocess only, no `symphony` imports). Use `sb.add_task(..., state="plan-review")`, `sb.write_sidecar`, `sb.run(...)`, `sb.state_of`, `sb.task_text`, `sb.log_section`, `sb.sidecar`.
  - [ ] `plan accept`: success path (folder `work-todo`, sidecar `plan_approved` true, `session_id` null, `state` `work-todo`, Log line contains `plan.accept`, stdout is the new path, exit 0).
  - [ ] `plan reject --feedback`: folder `plan-todo`, `## Feedback` has `### Round 1` and the text, Log line names `plan.reject`.
  - [ ] `work reject --feedback`: folder `work-todo`, session_id kept.
  - [ ] Repeated rejects (reject, force the task back to review, reject): Round 1 and Round 2 both present, in order, earlier text untouched. Also with a pre-existing `## Feedback` section holding human prose, and with the section missing (created before `## Log`).
  - [ ] Reject without feedback: exit 0, warning on stderr, no Round heading added.
  - [ ] `--edit` with a fake `$EDITOR` (a tiny shell/python script that writes text into the path argument) and with an editor that fails (exit 1, nothing changes). `--feedback` + `--edit` together exits 2.
  - [ ] `work reject --fresh`: `session_id` null in the sidecar, Log line names `work.reject_fresh`. Without `--fresh` the session id is kept.
  - [ ] Wrong state (for each command, for example a task in `work-todo`, `done`, `plan-running`): exit 1, file did not move, sidecar and file text unchanged, stderr lists the legal events (for `work-review`, includes `work.accept` and `work.reject`).
  - [ ] Id resolver: unique prefix works, exact match beats a longer sibling prefix, ambiguous prefix exits 2 and lists candidates, unknown id exits 2.
  - [ ] Hand-move compatibility: `mv work-review/x.md work-todo/` with `symphony run` still logs `work.reject: ... observed hand move` and keeps the session.
  - [ ] Concurrency: start `symphony run` (short poll interval; check the config key name in config.py/WORKFLOW.md fixtures) with a task in `plan-review` and `SYMPHONY_DEBUG_FIRE_DELAY=1.5` in the command's env. While the command is inside the delay, the orchestrator ticks several times. Assert afterward: exactly one `plan.accept` Log line, no `observed hand move` and no `illegal move` lines, `attempts`/effects applied once, task ends in `work-todo` or later (dispatched). Repeat for `plan reject` and `work reject`. Add a second variant that holds `.symphony/lock` from the test process with `fcntl.flock` for a while: the command blocks and finishes after release, and the orchestrator keeps ticking without an observe pass. Add a lock timeout test only if cheap.
  - [ ] `symphony transitions` / SPEC table sync test (if one exists) still passes with the new row.
- [ ] Implement `lock.py`; wire it into `Orchestrator.observe()` (non-blocking, skip on contention, log at debug).
- [ ] Add the `work.reject_fresh` row and the debug delay in `Machine.fire` (read env once).
- [ ] Implement `append_to_feedback_section` and `TaskStore.append_feedback`, plus unit-style coverage through the CLI tests (no package imports in the black-box suite).
- [ ] Implement editor handling and the three commands in `cli.py` (ids via `resolve_task_id`), with a shared `_transition_command` helper so later commands (`work accept`, `question answer`, `task retry`) reuse the pattern.
- [ ] Update SPEC.md (§3.3, §4.1 with the regenerated table, §11, §12), `CLAUDE.md` map, and the task file `## Log`.
- [ ] Run `uv run pyright` (0 errors, strict, no `Any` in public signatures; use `cast` at JSON/YAML boundaries) and `uv run pytest -q`, as separate plain commands.

### Files to change
- `src/symphony/cli.py`: new subcommands, `resolve_task_id` call, editor helper, exit codes.
- `src/symphony/transitions.py`: `work.reject_fresh` row, optional fire delay hook.
- `src/symphony/tasks.py`: `append_to_feedback_section`, `TaskStore.append_feedback`.
- `src/symphony/lock.py` (new): `repo_lock`.
- `src/symphony/orchestrator.py`: non-blocking lock around `observe()`.
- `tests/test_blackbox.py` (and `tests/conftest.py` for a lock/editor helper if useful).
- `SPEC.md`, `CLAUDE.md`, and the task file's `## Log`.

### Risks
- **Lock scope:** only `observe()` is guarded. If a future change makes the orchestrator fire events on review tasks, it must take the lock too. Say so in SPEC.
- **`flock` on odd filesystems** (network mounts): acceptable for a local tool. The lock file is created under `.symphony/`, which must be git-ignored, as it already is. Windows is out of scope (fcntl).
- **Skipped observe pass** delays hand-move interpretation by one tick when a command holds the lock. Harmless, but tests that assert timing of observed moves must not hold the lock.
- **Duplicate human rows:** `human_row` takes the first match, so row order matters. Keep `work.reject` before `work.reject_fresh`. Add a note in a code comment.
- **Test hook in production code:** the delay env var is inert unless set. If review objects, use the `flock`-from-test variant only.
- **Feedback written, fire fails:** a hand `mv` racing in before the lock is taken is handled by the in-lock state check. A residual failure leaves the feedback in place and exits 1 with a message.
- **Resolver duplication** if the `task list` task lands in parallel: reconcile at merge time and keep one implementation.
- Headings in user feedback (`# ` and `## `) are demoted to `###` so they cannot split the sections, but `### Round 9` typed inside feedback would confuse round counting. Count only headings of the exact form `### Round <digits>` at the start of a line, and accept that rare case.

### How to verify
- `uv run pyright` reports 0 errors.
- `uv run pytest -q` passes (about 25 s), including the new tests listed above.
- Manual spot check in a scratch repo: create a task in `plan-review`, run `symphony run` in one terminal, run `symphony plan reject x --feedback "..."` twice in a loop with a re-queue in between. Check that `.symphony/symphony.log` has no `illegal_move` entries and that each Log line appears once.
- `symphony transitions` output matches the table embedded in SPEC.

### Suggested subtasks
Not required (the change is about one coherent PR). If splitting: (1) lock plus `observe()` guard plus concurrency test, (2) feedback primitive plus `plan reject`, (3) `plan accept`, `work reject`, `--fresh`.

## Log
- 2026-11-07 01:34 symphony: dispatch_plan: plan-todo -> plan-running
- 2026-11-07 01:36 symphony: planned: plan-running -> plan-review: planned (turns 1, $0.24): Add `plan accept`, `plan reject` and `work reject` as thin commands (resolve, take lock, check state, write feedback, `Machine.fire`). A `.symphony/lock` file serialises them against the orchestrator's `observe()`. `--fresh` becomes a separate table event, `work.reject_fresh`.
- 2026-11-07 01:39 symphony: plan.accept: plan-review -> work-todo: observed hand move
- 2026-11-07 01:39 symphony: dispatch_work: work-todo -> work-running
- Deviation from the plan, settled in SPEC §3.3: the repo lock makes the orchestrator skip the whole tick (observe, reconcile, cleanup, dispatch), not only `observe()`. Reason: after the command's rename the task sits in `work-todo`/`plan-todo`, so `dispatch` could claim it before the command saved the sidecar, and the command's later save would clobber that. Commands also call `tasks.ensure()` since the destination folder may not exist without a running orchestrator.
- SPEC settled: §3.3 (repo lock, feedback writes), §4.1 (`work.reject_fresh` is command-only, table regenerated by hand), §11 (command pattern, exit codes, feedback rounds, `--edit`), §12 (`SYMPHONY_DEBUG_FIRE_DELAY`). Added `COMMAND_ONLY` to the row coverage test. pyright 0 errors, pytest 187 passed.
- 2026-11-07 01:45 symphony: permission denied: Bash (python3 - <<'EOF'
import re
p='tests/test_commands.py'
s=open(p).read()
s=s.replace('''    sb.move("t1", "work-todo", "w)
- 2026-11-07 01:46 symphony: done: work-running -> work-review: validation passed (turns 2, $1.03): Added `plan accept`, `plan reject` and `work reject [--fresh]`. Each resolves the id, takes the `.symphony/lock` flock, writes `### Round N` feedback, then fires the table event through `Machine.fire`. `--fresh` fires a new command-only row, `work.reject_fresh`, which also clears `session_id`. The orchestrator skips the whole tick while the lock is held, which differs from the plan, and the reason is in `## Log`. SPEC §3.3, §4.1, §11 and §12 and the CLAUDE.md map are updated. `uv run pyright` reports 0 errors, and `uv run pytest -q` passes (187 tests), including the new `tests/test_commands.py` with the concurrency tests. I didn't run the concurrency tests with the lock removed, so I haven't shown they fail without it. The SPEC transition table row for `work.reject_fresh` was added by hand, not regenerated with `symphony transitions`, though the SPEC-sync test passes.
- 2026-11-07 01:53 symphony: work.accept: work-review -> done: observed hand move
