---
priority: 3
depends_on: [plan-accept-reject-and-work-reject-commands]
---
# Question answer and task retry stop discard commands

Phase 2. The remaining transition commands, following the pattern from the `plan accept` /
`reject` task (outside effect, then fire the table event; same exit codes and output).

Read first: `docs/command-ideas.md` sections 2.3, 5.2, 5.3 and 6.3; SPEC §4.1, §11, §15; the
`plan accept` / `reject` implementation and its feedback primitive.

Decisions already made by the human:

- `symphony question answer <id> "text"` (or `--edit`): appends the answer to `## Feedback` with
  the shared feedback primitive, then fires `question.answer`. The stage it returns to comes from
  the table (`last_stage`, or the `unset` rows).
- `symphony task retry <id>`: fires `task.retry` from `stuck`.
- `symphony task stop <id>`: fires `task.stop` on a running task; the orchestrator's reconcile
  stops the agent as it does for a hand move.
- `symphony task discard <id>`: fires `task.discard`; dangerous class, so it uses the same
  confirmation policy as `work accept` (`[y/N]` on a TTY, `--yes`, refusal without TTY).

Scope:

- `task retry` when the cause is `budget`: print a hint that the cap in `WORKFLOW.md` must be
  raised first, or the task will go straight back to `stuck`. Do not change the config.
- `task retry` when the cause is `dependency_discarded` or `dependency_cycle`: print a hint to edit
  `depends_on` first.
- `task stop` when no orchestrator is running: the task file is still moved (the next run's
  recovery logic must not misread it); document what happens.

Acceptance criteria:

- Black-box tests for each command: success path (folder, effects, `## Log` line naming the
  event), wrong-state refusal listing legal events, the answer text landing in `## Feedback` under
  a new round, `retry` hints per cause, `stop` with a live fake agent (the agent process is
  killed), `discard` confirmation behavior.
- SPEC §11 documents the commands.
- `uv run pyright` reports 0 errors and `uv run pytest -q` passes.

## Plan
### Approach

Reuse the existing command pattern in `src/symphony/cli.py::cmd_transition` (resolve id -> repo lock -> legality check against `human_events` -> outside effect -> `Machine.fire` -> print new path; exit 0/1/2 as in SPEC §11). No new transition rows: `question.answer`, `task.retry`, `task.stop`, `task.discard` already exist in the table (SPEC §4.1).

Differences from `plan reject`:
- `question answer` takes the text as a **required positional** (`question answer <id> "text"`) or `--edit` (mutually exclusive with the positional; make the positional `nargs="?"` and enforce "exactly one of text or --edit" with `parser.error` -> exit 2). Empty text (after strip) is a usage error (exit 2): an answer without text is pointless, unlike a reject. It uses the existing feedback primitive `tasks.append_feedback` (new `### Round N`), and the log line says `feedback round N`. Generalize `cmd_transition`'s `takes_feedback` into something like `feedback_mode: None | "optional" | "required"` so the "warning: rejecting without feedback" line only applies to reject. The destination (plan-todo/work-todo) comes from the table via `fire` (`last_stage`, or the `unset` rows).
  - Note: with `last_stage` unset, `fire` picks the first matching row (`plan-todo`). Decide and document: the command goes to `plan-todo` when stage is unset. Hand moves remain the way to choose `work-todo` in that case. Put this in SPEC §11. (Alternative if the human prefers: refuse with a hint to move by hand. Default to the first-row behavior, since it is what the table gives.)
- `task retry`: no feedback. After a successful `fire`, read the sidecar `blocked_cause` **captured before the fire** (the row clears it) and print hints on **stderr** (stdout stays only the new path):
  - `budget`: `hint: raise the budget cap in WORKFLOW.md first, or the task will go straight back to stuck` (name the actual keys: check `config.py` for the budget key names, e.g. max turns / max cost, and use them in the text). Do not touch config.
  - `dependency_discarded` / `dependency_cycle`: `hint: edit depends_on in the task file first; the dependency check will send it back to stuck otherwise`.
  - Other causes (`gave_up`, `question`, none): no hint.
  - Hints are printed after the move succeeds (retry is still done, exit 0). Keep this simple; hints are advisory.
- `task stop`: plain fire of `task.stop` (legal only in `plan-running`/`work-running`, so wrong-state refusal already lists legal events). With a live orchestrator, the next tick's `reconcile` sees the task file left its running folder and cancels the worker (`stop_reason="moved"`), exactly as for a hand move; `observe` does not misread it because `fire` saved sidecar `state`.
  - **No orchestrator running**: the file is moved to the todo folder and the sidecar updated. Next `symphony run` sees a normal todo task (recovery only touches `*-running` folders; the sidecar `state` matches, so no hand move is observed). Nothing kills an agent process left behind by a crashed orchestrator. Document that in SPEC §11 and print nothing extra.
- `task discard`: dangerous class. `work accept` (now on main) already confirms inline in `cmd_work_accept`: `--yes` skips; without a TTY on stdin and stdout it exits 2 with "needs confirmation: run it on a terminal or pass --yes; nothing changed"; otherwise it prompts `<plan>? [y/N] ` and anything but `y`/`yes` is exit 1 ("not confirmed; nothing changed"). Extract that block into one shared helper in `cli.py` (for example `confirm(prompt: str, command: str, yes: bool) -> int | None`, returning the exit code to stop with, or None to proceed), switch `cmd_work_accept` to it with unchanged behavior and messages (`tests/test_work_accept.py` must stay green untouched), and use it for discard. Do not write a second confirmation implementation. Order: resolve id and legality check first (wrong state is exit 1 with no prompt), then confirm, then take the lock and re-check, then fire. A declined prompt: exit 1, nothing changed, same message as `work accept`. Discarding a running task stops the agent through reconcile; the worktree is removed by `cleanup_workspaces` once the agent stops and the branch is kept (§5.2).

**Spec §3.3 detail to settle**: `task stop` and `task discard` on a running task make the command append the `## Log` line to a task file whose agent is still alive (until the orchestrator's next tick cancels it). §3.3 currently allows commands to write only feedback into review folders. Fire moves the file first, so the log append goes to the new path (`work-todo`/`discarded`), which the agent does not hold; the residual risk is a read-modify-write race with an agent that has already rewritten its file. Accept it (the file is no longer in the running folder, the worker is about to be cancelled) and amend §3.3: "a command may also fire `task.stop` or `task.discard` on a running task; the `## Log` line is written by the command, after the move". Mention this in the task `## Log` as a spec detail settled.

Also verify (do not assume) that a cancelled worker does not re-save a stale in-memory sidecar over the command's saved one: after `task stop` with a live agent the sidecar must have `state == work-todo` and `attempts == 0`. If the worker's cancel path saves the sidecar, fix it so it does not touch state/attempts on `stop_reason == "moved"`.

### Steps

- [ ] Read `tests/test_commands.py`, `tests/test_transitions.py` (hand-move stop test at line ~220) and `tests/test_layout.py:105` for the style; read `config.py` for the budget cap key names to cite in the hint.
- [ ] **Tests first.** Extend `tests/fake_claude.py` (stdlib only) to also record its pid in the calls record (`{"argv":..., "cwd":..., "pid": os.getpid()}`; `Sandbox.calls` only reads `argv` so existing tests are unaffected) and add `Sandbox.pids(task_id)` in `conftest.py`. Add a new file `tests/test_commands_phase2.py` (black-box, no `symphony` import) with:
  - [ ] `question answer`: success for `last_stage=plan` -> `plan-todo`, `work` -> `work-todo`, unset -> `plan-todo`; stdout is the new path; `## Feedback` has `### Round 1` with the text (and Round 2 on a repeat, headings demoted); `## Log` has `question.answer: question -> <dst>: feedback round 1`; sidecar `attempts == 0`, `blocked_cause` None, `state` updated; `--edit` via the fake editor; no text and no `--edit` -> exit 2; text plus `--edit` -> exit 2; empty text -> exit 2; none of those change anything.
  - [ ] `task retry`: success from `stuck` for both stages (`attempts` reset, `blocked_cause` cleared, log line `task.retry: stuck -> work-todo`); hint per cause (`budget` mentions `WORKFLOW.md`; `dependency_discarded` and `dependency_cycle` mention `depends_on`; `gave_up` prints no hint); `WORKFLOW.md` byte-identical after `retry`; stdout is only the path.
  - [ ] `task stop`: with a live orchestrator (`sb.popen("run")`, step `{"hang": 30}`), wait for the pid in calls, run `task stop`, assert exit 0, folder `work-todo` (or `plan-todo` for a plan task), the agent pid is dead (poll `os.kill(pid, 0)` raising `ProcessLookupError`), log line `task.stop: work-running -> work-todo` appears exactly once with no `observed hand move`/`illegal move`, sidecar `attempts == 0`. Use `SYMPHONY_DEBUG_FIRE_DELAY` only if needed for a race test. Without an orchestrator: seed a `work-running` task with sidecar, run `task stop`, assert file moved and sidecar `state` updated, then `run_idle` runs it normally with no hand-move line.
  - [ ] `task discard`: `--yes` succeeds from several states (`work-review`, `stuck`, `work-running`), folder `discarded`, log line, branch kept after `run_idle` cleanup; without `--yes` and without a TTY -> exit 2, nothing changed; with a pty (stdlib `pty`/`os.openpty`, passed as stdin) answering `y` -> discarded, answering `n`/empty -> exit 1, nothing changed, prompt text contains `[y/N]`; wrong state (`done`, `discarded`) -> exit 1 listing `Legal events: none` without prompting. Discard of a running task with a live agent kills the agent pid. (Needs a `Sandbox.run` variant or a small `subprocess.run(..., stdin=<slave fd>)` helper inside the test file to give a TTY stdin.)
  - [ ] Wrong-state refusal parametrized per command (`question answer` in `work-todo`, `task retry` in `work-review`, `task stop` in `work-todo`, `task discard` in `done`): exit 1, stdout empty, `<id> is in <state>; <event> not allowed. Legal events: ...`, files and sidecar unchanged.
  - [ ] Concurrency: add the two non-destructive commands (`question answer`, `task retry`) to a `CONCURRENT`-style test with a running orchestrator (as `test_command_while_orchestrator_runs`) so the lock behavior is covered.
- [ ] Run the new tests and confirm they fail for the right reason.
- [ ] **Implementation** in `src/symphony/cli.py`: new subparsers `question answer`, `task retry|stop|discard` (with `--yes` on discard) under the existing `task` group, `--repo` on all of them (add to the loop at line ~239), dispatch in `main`, generalized feedback handling in `cmd_transition`, `confirm_dangerous`, pre-fire `blocked_cause` capture + hint printing for retry. Keep pyright strict clean (use `cast` at argparse boundaries like the existing code). Update the `task` parser help text (`task commands: list, show, ...`).
- [ ] Check `views.py` `render_show`'s `events:` output still matches (it derives from the table, so nothing to change); update any help strings.
- [ ] **SPEC.md**: §11 usage block (four new commands with flags), extend the command-pattern paragraph, document: answer text rules and the `unset` destination, `--yes`/TTY/exit 2 policy shared with `work accept`, retry hints per cause (on stderr, after the move), `task stop` with and without orchestrator (including that an orphaned agent from a crashed orchestrator is not killed), and the discard-of-running behavior. Amend §3.3 as described. Keep no em-dashes. `symphony transitions` output is unchanged, so the drift test stays green.
- [ ] Append a note to the task file's `## Log` (done by the executing agent) naming the spec details settled: unset-stage destination for `question answer`, empty answer is exit 2, hints on stderr, and the §3.3 amendment.
- [ ] Run `uv run pyright` (0 errors) and `uv run pytest -q` separately.

### Files to change

- `src/symphony/cli.py` (commands, parsers, confirmation helper, hint output)
- `SPEC.md` (§11, §3.3, possibly a sentence in §4.1 near `last_stage=unset`)
- `tests/test_commands_phase2.py` (new), `tests/conftest.py` (`pids` helper), `tests/fake_claude.py` (record pid; stdlib only)
- Possibly `src/symphony/orchestrator.py` only if the cancelled-worker sidecar check above finds a stale overwrite.
- `docs/command-ideas.md` needs no change.

### Risks

- **Stale sidecar overwrite**: a cancelled worker holding an in-memory `Sidecar` could save over the state the command wrote. Covered by the `task stop` test asserting sidecar `state` and `attempts`.
- **Log append to a live-agent file** (§3.3): accepted and documented, see above.
- **`unset` stage with `question answer` / `task retry`**: `fire` always picks the first row (`plan-todo`). Documented; hand move remains the way to choose work.
- **TTY tests**: pty handling can be flaky; use a short timeout, close the master fd, and keep these tests small. The prompt must read from stdin, not `/dev/tty`, so the tests can drive it.
- **Hint wording tied to config key names**: check `config.py` so the text names real keys.
- The fake agent's pid record must not break `Sandbox.calls` (it reads only `argv`) or reuse of the fake against a future rewrite.
- Hard-limit note: tests use synthetic tasks only; no customer data or secrets are involved.

### How to verify

- `uv run pytest -q tests/test_commands_phase2.py` first (fail before implementation, pass after), then `uv run pytest -q` (about 25 s) and `uv run pyright` as separate plain commands.
- Manual smoke in a temp repo: `symphony new`, hand-set a task into `stuck` with each cause, run `symphony task retry` and read the hints; `symphony task discard X` on a TTY shows `[y/N]`, piped stdin without `--yes` exits 2.
- Check that `symphony transitions` still matches the SPEC table (existing drift test).

### Suggested subtasks

None needed; this fits one change. If it grows, split `task discard` plus the confirmation helper from the other three.

## Questions
None blocking. Confirm if you disagree with these defaults: (1) `question answer` / `task retry` with `last_stage` unset go to the plan-todo folder (first table row); (2) an empty answer text is a usage error (exit 2); (3) retry hints go to stderr after the move, keeping stdout as only the new path.

## Log
- 2026-11-07 01:54 symphony: dispatch_plan: plan-todo -> plan-running
- 2026-11-07 01:55 symphony: planned: plan-running -> plan-review: planned (turns 1, $0.33): Add `question answer`, `task retry`, `task stop` and `task discard` by generalizing `cmd_transition` in `cli.py`, plus a shared confirmation helper, a pid record in the fake agent, black-box tests written first, and a SPEC §11 and §3.3 update. No open questions; two spec details (stop without orchestrator, command writing a running task's file) are settled in the plan.
- 2026-11-07 20:15 symphony: plan.accept: plan-review -> work-todo
- 2026-11-07 20:15 symphony: dispatch_work: work-todo -> work-running
- agent: implemented all four commands (cli.py), shared `confirm` helper (work accept switched to it, unchanged behavior), tests in tests/test_commands_phase2.py (fake agent now records its pid), SPEC §11 and §3.3 updated. Spec details settled: `question answer` with `last_stage` unset goes to plan-todo (first table row); empty/missing answer text is exit 2; retry hints go to stderr after the move; §3.3 amended so `task stop`/`task discard` on a running task write their log line after the move. Verified the cancelled worker does not rewrite the sidecar on `moved` (test asserts attempts 0 and the redispatched state). pyright 0 errors, 240 tests pass.
- 2026-11-07 20:20 symphony: permission denied: Bash (python3 - <<'E'
import re
p='tests/fake_claude.py'
s=open(p).read()
s=s.replace('json.dumps({"argv": argv, "cwd": str(cw)
- 2026-11-07 20:22 symphony: done: work-running -> work-review: validation passed (turns 2, $0.89): I added `question answer`, `task retry`, `task stop` and `task discard`, with a shared `[y/N]` confirmation helper that `work accept` now uses too, and committed it on the branch. I also added SPEC §11 and §3.3 updates and 32 black-box tests in `tests/test_commands_phase2.py`. `uv run pyright` reports 0 errors and `uv run pytest -q` passes (240 tests). I settled three details the spec left open, and each is in SPEC §11 and the task `## Log`: - **Unset stage:** `question answer` and `task retry` go to `plan-todo` when `last_stage` is unset, because that is the first row in the table. - **Empty answer:** an empty or missing answer to `question answer` is a usage error (exit 2) and changes nothing. - **Retry hints:** `task retry` prints its hints to stderr after the move, so stdout stays only the new path. Two behaviors worth knowing: - **`task stop` with a live agent:** the agent is killed and the task is dispatched again like any todo task. The cancelled worker does not overwrite the sidecar. - **§3.3 amendment:** `task stop` and `task discard` on a running task write their `## Log` line after the file move, so a small race with the agent is accepted.
- 2026-11-07 20:27 symphony: work.accept: work-review -> done: merged cdfb18b, validated
