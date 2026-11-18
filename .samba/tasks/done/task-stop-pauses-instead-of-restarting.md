---
priority: 3
depends_on: [question-answer-and-task-retry-stop-discard-commands]
---
# Task stop pauses instead of restarting

`symphony task stop <id>` kills the running agent and fires `task.stop`, whose rows move
`plan-running -> plan-todo` and `work-running -> work-todo`. While an orchestrator is running, the
next tick dispatches the task again, so "stop" is in practice a restart. A human who stops a task
wants it to stay put until they say otherwise.

Read first: SPEC §4.1 (transition table), §11 (commands, `task stop`, `task retry`), §3.3;
`src/symphony/transitions.py`; `cmd_transition` and the `task stop` / `task retry` wiring in
`src/symphony/cli.py`; `tests/test_commands_phase2.py`.

Decisions already made by the human:

- `task.stop` moves `plan-running -> stuck` and `work-running -> stuck`, setting
  `last_stage` (plan or work) and a new `blocked_cause=stopped`. The agent is killed as today.
- `task retry` is how a stopped task resumes. The existing `task.retry` rows already send a stuck
  task back to its stage's todo folder using `last_stage`; reuse them, no new rows for resuming.
- `task retry` on a task with `blocked_cause=stopped` prints no hint (nothing to fix first).
- `task status` / `task list` should make the reason visible, so a stopped task is
  distinguishable from one stuck on budget or a dependency, if the listing already shows
  `blocked_cause`; do not add a new column just for this.
- Small fix in the same change: the `task discard` confirmation prompt names the resolved task id,
  not the prefix the user typed (it currently prints "Discard task ques?").

Acceptance:

- Black-box tests first: stop a running plan-stage and work-stage task (with and without an
  orchestrator running); the task lands in `stuck` with `blocked_cause=stopped` and the right
  `last_stage`; a following orchestrator tick does not dispatch it; `task retry` sends it back to
  the right todo folder and it is dispatched again. Discard prompt shows the full id.
- Update the transition table, regenerate the SPEC embed (`symphony transitions`), and update
  SPEC §11 text for `task stop`. No em-dashes.
- `uv run pyright` 0 errors, `uv run pytest -q` passes.

## Plan
### Approach
The orchestrator only dispatches todo folders, so moving a stopped task to `stuck` is enough to keep it put. No orchestrator change is expected: it already cancels an agent whose task left its running folder, and `stuck` is a folder it does not dispatch from. Resuming reuses the existing `task.retry` rows, which route by `last_stage`. `views.py:71` already renders `stuck (<cause>)` for `stuck` and `question` tasks, so `stuck (stopped)` appears in `task list` with no new column. Check `task show` too, which prints `blocked_cause` at `views.py:93`.

### Steps
- [ ] Tests first, in `tests/test_commands_phase2.py`, using the existing `seed`, `sb`, `wait_for`, `alive` and `stop` helpers:
  - [ ] Rewrite `test_stop_live_agent`, parametrized over plan and work:
    - run the orchestrator and wait for `*-running` and a live pid;
    - run `task stop`;
    - assert stdout is the `stuck/t1.md` path;
    - assert the pid dies, state is `stuck`, sidecar `blocked_cause == "stopped"`, and `last_stage` equals the stage;
    - assert the log has `task.stop: <running> -> stuck` exactly once;
    - sleep a few poll intervals and assert `len(sb.pids("t1")) == 1`, so it was not redispatched, and the state is still `stuck`;
    - then `sb.run("task", "retry", "t1")` and assert the task goes to `<stage>-todo`;
    - assert `sb.steps` supplies a second run and the orchestrator dispatches it again (`len(pids) == 2`);
    - assert stderr is empty for retry (no hint).
  - [ ] Rewrite `test_stop_without_orchestrator`, parametrized over plan and work. Seed `*-running` with `last_stage`, stop it, and assert the state is `stuck` with the right cause and stage. Then `sb.run_idle()` and assert it is still `stuck` and the fake was not called. Retry, run idle again, and assert it was dispatched (`work-review` or `plan-review`).
  - [ ] Add a `task retry` test for `blocked_cause="stopped"`: stderr is empty and `blocked_cause` is cleared.
  - [ ] Add a discard prompt test with a typed prefix such as `t` for the id `task-one`. The suite runs `symphony` as a subprocess with no TTY. Either use a pty (`pty`/`os.openpty`, as other tests may already do; grep `isatty` or `pty` in tests) and assert the output contains `Discard task <full id>?`, or fall back to a unit-free check if no pty helper exists.
  - [ ] Update the `test_commands_phase2.py:228` parametrize row `(["task","stop","t1"], "work-todo", "task.stop")`, which is an illegal-state-style check, if its destination changed (it likely moves to `stuck`). Also check `tests/test_transitions.py` for per-row parametrized cases on `task.stop` and update them.
- [ ] `src/symphony/tasks.py` (near line 24): add `CAUSE_STOPPED = "stopped"`.
- [ ] `src/symphony/transitions.py`:
  - [ ] Import `CAUSE_STOPPED`.
  - [ ] Add the effects `f"blocked_cause={CAUSE_STOPPED}": _set(blocked_cause=CAUSE_STOPPED)` to `EFFECTS` (line ~163).
  - [ ] Replace the rows at lines 117-118 with `_t("plan-running","task.stop",H,"stuck","","last_stage=plan","blocked_cause=stopped")` and the work equivalent. No `attempts` change and no `last_outcome` change.
- [ ] `src/symphony/cli.py`: change the discard wiring (line ~461) to pass `confirm_plan="Discard task {id}"`. In `cmd_transition`, call `confirm(confirm_plan.format(id=task_id), ...)` so it uses the resolved id. `_retry_hint` needs no change: `stopped` already falls through to None.
- [ ] Verify the orchestrator path:
  - [ ] Read `orchestrator.py` for what it does when a running task's file is found in `stuck`: it should cancel the worker without writing a stale sidecar or logging "observed hand move" or "illegal move" (the old test asserts this).
  - [ ] Check that the cancelled worker's final `fire`, if any, cannot overwrite the sidecar (`give_up`, `budget`, `done` from `running` are not legal from `stuck`).
  - [ ] Make sure no code treats `stuck` plus a cause as something to auto-retry.
- [ ] SPEC.md:
  - [ ] §4.2 `blocked_cause` list (line ~303): add `stopped` (a human ran `task stop`) and say the field also covers stuck tasks that were stopped.
  - [ ] §4.1 text near lines 186 and 277: `task.stop` now targets `stuck` as well as the `discarded` mention. Re-read line 277 (it describes `task.stop` as a target that stops the agent) and fix the wording.
  - [ ] Regenerate the embedded table by running `uv run symphony transitions` and pasting the output over the table at lines ~200-233 (rows 232-233 change).
  - [ ] §11 `task stop` (lines 827-832): the task goes to `stuck` with `last_stage` set and `blocked_cause=stopped`. It is not redispatched; `task retry` resumes it. With the orchestrator running, the next tick cancels the agent. Keep the sentence about an agent left behind by a crashed orchestrator.
  - [ ] §11 `task retry` (line ~821): mention that `stopped` prints no hint, which is already implied by "Other causes print nothing".
  - [ ] §11 `task discard` prompt (line ~835): the prompt names the resolved task id.
  - [ ] Also fix the state description for `stuck` (grep SPEC for "stuck" in the state table around lines 160-170) so it lists stop as a way in.
  - [ ] No em-dashes anywhere.
- [ ] `docs/command-ideas.md:271` is a historical design doc: leave it unless there is a test that scans docs.
- [ ] Add to the task file `## Log` that the SPEC detail settled was `blocked_cause=stopped`, plus the stop destination.

### Files to change
- `src/symphony/tasks.py`, `src/symphony/transitions.py`, `src/symphony/cli.py`
- `SPEC.md` (§4.1 table regenerated, §4.2, §11)
- `tests/test_commands_phase2.py`, possibly `tests/test_transitions.py`
- Possibly `src/symphony/orchestrator.py` (only if the check above finds a problem)

### Risks
- A cancelled worker finishing late could write a result. Existing tests guard the stale sidecar case; keep that assertion for the `stuck` destination.
- Any test that expects `task.stop` to land in a todo folder breaks. Grep for `task.stop` and `"stop"` across `tests/`, including the table-driven tests that enumerate rows.
- The SPEC embed must match `symphony transitions` exactly. A test may compare them, so regenerate it rather than editing by hand.
- The pty test for the discard prompt can be flaky. Keep the timeouts short and check what helpers already exist.
- `stopped` is not in `question`'s hint logic. Make sure `task retry` from `stuck` with `last_stage` unset still routes through the existing fallback rows.

### How to verify
- `uv run pyright` reports 0 errors.
- `uv run pytest -q` passes, including the new tests.
- `uv run symphony transitions` output matches the SPEC embed.
- Grep SPEC.md and the edited files for em-dashes.

### Suggested subtasks
None: the change is small enough for one session.

## Log
- 2026-11-07 21:00 symphony: dispatch_plan: plan-todo -> plan-running
- 2026-11-07 21:01 symphony: planned: plan-running -> plan-review: planned (turns 1, $0.22): Change the two `task.stop` rows to land in `stuck` with `last_stage` set and a new `blocked_cause=stopped`, so `task retry` resumes the task through its existing rows. Also fix the discard prompt to show the resolved id, and update the tests and SPEC. Not yet run: the code paths below were read, but no tests were run.
- 2026-11-07 21:02 symphony: plan.accept: plan-review -> work-todo
- 2026-11-07 21:02 symphony: dispatch_work: work-todo -> work-running
- 2026-11-07 21:20 agent: all plan steps done (checkboxes not ticked individually). SPEC detail settled: `task.stop` goes `*-running -> stuck` with `last_stage=<stage>` and `blocked_cause=stopped`; hand-moving a running task to a todo folder is now illegal (moved back), only `stuck` or `discarded` are legal targets. No orchestrator change needed. Discard prompt uses the resolved id. SPEC §3.3, §4.1, §4.2, §11 and the embedded table updated; tests rewritten (test_commands_phase2.py, test_transitions.py). pyright 0 errors, pytest 244 passed.
- 2026-11-07 21:06 symphony: permission denied: Bash (sed -i 's/confirm_plan=f"Discard task {args.id}"/confirm_plan="Discard task {id}"/; s/code = confirm(confirm_plan, label)
- 2026-11-07 21:08 symphony: done: work-running -> work-review: validation passed (turns 2, $0.56): `task stop` now moves a running plan or work task to `stuck` with `last_stage` set and `blocked_cause=stopped`, so it is not redispatched. `task retry` resumes it through the existing rows and prints no hint. The discard prompt shows the resolved id. SPEC and the transition table are updated. pyright reports 0 errors and pytest passes (244 tests). The work is committed.
- 2026-11-07 21:41 symphony: work.accept: work-review -> done: merged 5a4b146, validated
