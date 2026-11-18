---
priority: 3
depends_on: ["split-the-orchestrator-into-named-parts-and-a-thin-loop-adr"]
---
# Extract the workers and thin the orchestrator loop (ADR 0015, part 2)

Read CLAUDE.md, docs/spec/architecture.md, docs/spec/orchestrator.md and ADRs 0011 to 0015 first. Behavior does not change: the black-box suite, tests/scenarios/lifecycle.json and every other test stay green, and pyright stays at 0 errors. Plan steps may use only commands in the WORKFLOW.md allow list: no git mv, no sed -i, no mkdir, no pipes or redirects, no uv sync. If the work is too big for one run at the per-task cost cap, propose chained subtasks in the plan.

Part 2 of ADR 0015. Part 1 (the previous task) moved the rules into app/: Guard, Startup (with StartupError), PromptBuilder, Finisher and RunTask, and left the Orchestrator in entrypoints/orchestrator.py owning the loop and the asyncio workers while delegating to them. This task finishes the split: create entrypoints/workers.py with a Workers part (spawn, tracking of running tasks, the asyncio task for each worker, what happens to a cancelled worker: journal stopped, recover on shutdown, workspace removal when moved, run_task.crashed for any other exception, shutdown with return_exceptions, wait_all for tests), and reduce entrypoints/orchestrator.py to a thin Orchestrator of about a hundred lines that only wires the parts and runs: startup, then tick and sleep until stopped, with shutdown in a finally, plus exit-when-idle. It holds no rule: it must not import domain.policy, domain.prompts or domain.template. Workers and Tick share the same running dict and Notes instance. Update tests/test_scenarios.py to gather workers through the new part, keep lifecycle.json unchanged and the under-one-second test, add entrypoints/workers.py to the architecture test lists (entry point files, no direct clock, orchestrator violations) and add a size and no-rule test for entrypoints/orchestrator.py. Update the architecture and orchestrator spec chapters and the CLAUDE.md map so they describe the final split (Startup, Tick, RunTask with prompts and finish-or-fail, Workers for cancel and shutdown, Orchestrator for the wiring).

## Plan
### Approach
Pure move of job 3 (worker lifecycle) out of `Orchestrator` into `entrypoints/workers.py`. The Orchestrator is left with construction of the parts and the loop. The rules stay in `app/`. `Orchestrator` creates one `running: dict[str, Running]` and one `Notes(tasks, running)` and passes the same instances to both `Tick` and `Workers`. `Tick` receives `workers.spawn` as its `spawn` callback. Construction order: running, notes, machine, turns, builder, finisher, run_task, `Workers(run_task, machine, tasks, vcs, clock, journal, running, notes)`, `Startup`, `Tick(..., workers.spawn, ...)`.

### Steps
- [ ] Read CLAUDE.md, docs/spec/architecture.md, docs/spec/orchestrator.md, ADRs 0011 to 0015 (`samba adr show N`), `src/samba/entrypoints/orchestrator.py`, `src/samba/app/tick.py` (`Running`, `Notes`, `running_folder`, `runnable_todo`, `cleanup_workspaces`), and `tests/test_architecture.py`.
- [ ] Tests first. In `tests/test_architecture.py`:
  - add `"workers.py"` to `ENTRYPOINT_FILES`;
  - add `"entrypoints/workers.py"` to the list in `test_no_direct_clock_or_uuid_calls`;
  - add a `test_the_workers_import_no_io_adapter_or_old_module` that applies `orchestrator_violations` to `entrypoints/workers.py`. Extend the bad-file check if useful;
  - add `test_the_orchestrator_is_thin_and_holds_no_rule`: `entrypoints/orchestrator.py` has at most ~110 lines, and `imported_modules` contains none of `samba.domain.policy`, `samba.domain.prompts`, `samba.domain.template`. Reuse the existing `imported_modules` helper;
  - the existing orchestrator forbidden-imports test still applies.
- [ ] Update `tests/test_scenarios.py` (line ~414): replace `await orch.wait_workers()` with `await orch.workers.wait_all()`. Keep `lifecycle.json` unchanged and keep the under-one-second test. Run it and watch it fail until the code exists.
- [ ] Create `src/samba/entrypoints/workers.py` with `class Workers`:
  - ctor takes `run_task: RunTask`, `machine: Machine`, `tasks: Tasks`, `vcs: Vcs`, `clock: Clock`, `journal: Journal`, `running: dict[str, Running]`, `notes: Notes`;
  - `spawn(task)`: create the asyncio task for `self._work(task.id)`, record it in `_workers`, set `running[task.id] = Running(task=worker, started_at=clock.monotonic(), folder=running_folder(task))`, and add the done callback (pop from running and `_workers`, `notes.release`);
  - `_work(task_id)`: move the current `work` body unchanged (`on_turn` updating `entry.turn`; `CancelledError` branch: journal `stopped`, `recover` on reason shutdown, `remove_workspace` suppressing `WorkspaceError` when reason is moved and status is in (None, done, discarded); `Exception`: `await run_task.crashed(task_id, e)`);
  - `_status(task_id)`;
  - `async shutdown()`: same as now (return early if none running; set stop_reason shutdown where None; cancel; `gather(..., return_exceptions=True)`);
  - `async wait_all()`: `gather` of the current workers (for tests).
- [ ] Rewrite `src/samba/entrypoints/orchestrator.py` to wiring only. Drop the imports of asyncio details that are no longer needed (keep `asyncio.sleep`), contextlib, functools, `Task`, `TaskId`, `State`, `WorkspaceError`. Do not import `domain.policy`, `domain.prompts` or `domain.template`. Public surface: `__init__` (same signature, builds the parts), `workers` attribute, `startup()`, `tick()`, `cleanup_workspaces()`, `run(exit_when_idle=False)` (startup, journal `started`, loop: tick; if exit_when_idle and not running and not `ticker.runnable_todo()`: cleanup, journal `idle_exit`, return; sleep `poll_interval_s`; `finally: await workers.shutdown()`). Update the module docstring to describe the final split. Aim for ~100 lines.
- [ ] Run `uv run pyright` (0 errors) and `uv run pytest -q` as separate plain commands. Fix drift (e.g. `bootstrap.py` needs no change).
- [ ] Update docs (see Spec changes), then add a `## Log` line in the task file about the spec and CLAUDE.md edits.
- [ ] Re-run pyright and pytest. `tests/test_manual.py` is unaffected (no CLI change).

### Files to change
- new `src/samba/entrypoints/workers.py`
- `src/samba/entrypoints/orchestrator.py` (rewrite, thin)
- `tests/test_architecture.py`, `tests/test_scenarios.py`
- `docs/spec/architecture.md`, `docs/spec/orchestrator.md`, `CLAUDE.md`
- Possibly `docs/spec/README.md` only if its one-liners mention the old split (the current line for orchestrator.md already says workers; likely no change).

### Spec changes
- `docs/spec/architecture.md`: the Entry points row now lists `workers.py` and describes `orchestrator.py` as the thin wiring and loop. Rewrite "Orchestrator parts" as the final split: a table with Startup, Tick, RunTask (with PromptBuilder and Finisher), Guard, Workers (spawn, tracking, cancel handling, shutdown, `wait_all`) and Orchestrator (wiring, loop, idle exit); remove the "Step 1 (done) / Step 2 (a separate task)" wording. In "The architecture test" list add `workers.py` to the entrypoint files and to the no-direct-clock and no-I/O import checks, plus the new size and no-rule check of `orchestrator.py` (no `domain.policy`, `domain.prompts`, `domain.template`, about 100 lines). Fix the line at ~144 that says `orchestrator.py (poll loop, workers)`, and the Journal row (add `Workers`, since it journals `stopped`).
- `docs/spec/orchestrator.md`: replace the intro (lines 3 to 8) so it says who owns what in the final split: `Startup`, `Tick`, `RunTask`, `Workers` (cancel and shutdown behaviour), `Orchestrator` (wiring only). State that behavior is unchanged.
- `CLAUDE.md` map: update the `entrypoints/orchestrator.py` bullet (thin wiring and loop, no rules), add `entrypoints/workers.py` (`Workers`: spawn, running dict shared with `Tick`, cancelled-worker handling, `shutdown`, `wait_all`), and the `test_architecture.py` and `test_scenarios.py` bullets if they name the old split. Prose without em-dashes.

### Risks
- Shared-state wiring: `Tick`, `Workers` and `Notes` must use the very same `running` dict object. A copy would break the idle exit and the `moved` stop logic. Create it once in `Orchestrator.__init__`.
- The `spawn` callback is passed to `Tick` before use, so `Workers` must be built before `Tick`. This is why it is created after `run_task`.
- Done-callback ordering: it must keep popping `running` and `_workers` and releasing notes, otherwise the idle-exit and the lifecycle test (under one second) hang or slow down.
- Hitting ~100 lines: the constructor wiring is long. Group imports tightly and keep the docstrings short. If it goes a little over, adjust the test ceiling (about 110) instead of moving rules.
- The no-direct-clock regex scans `workers.py`: only `self.clock.monotonic()` is allowed (a method on the injected port, not `time.monotonic(`).
- Allow-list: use only `git grep`, `uv run pyright`, `uv run pytest -q`, Read/Edit/Write tools. No `git mv`, `sed -i`, `mkdir`, pipes or redirects.

### How to verify
- `uv run pyright` reports 0 errors.
- `uv run pytest -q` is green, including `tests/test_blackbox.py`, `tests/test_scenarios.py` (lifecycle.json unchanged, under-one-second test), `tests/test_app_startup.py`, `tests/test_app_run_task.py` and `tests/test_architecture.py` with the new tests.
- `git grep -n "wait_workers\|orch.work\b"` finds nothing in the repo.
- `wc`-like check by the new architecture test: `entrypoints/orchestrator.py` is at most ~110 lines and imports none of `samba.domain.policy`, `samba.domain.prompts`, `samba.domain.template`.

### Suggested subtasks
None; the task fits in one run.

## Assumptions
- Single run is enough: it is a mechanical move plus tests and docs, so no subtasks are needed.
- `Orchestrator` keeps public `startup()`, `tick()` and `run(exit_when_idle)`; the test calls `orch.workers.wait_all()` instead of `orch.wait_workers()`. Nothing outside tests/test_scenarios.py and bootstrap.py uses other attributes (checked by grep: `running`, `notes`, `machine`, `run_task`, `ticker`, `work`, `_spawn` have no outside users).
- `Orchestrator.__init__` keeps its current signature, so bootstrap.py is unchanged.
- The ~100 line bound for the orchestrator test is a ceiling of about 110 lines, counting the file as written.
- No ADR is needed: ADR 0015 already records the decision.
- `cleanup_workspaces` on idle exit stays reachable through `Tick`. Workers holds no clock-derived rule beyond `clock.monotonic()` for `started_at`.

## Log
- 2026-11-11 14:57 samba: dispatch_plan: plan-todo -> plan-running
- 2026-11-11 14:57 samba: planned: plan-running -> plan-review: planned (turns 1, $0.16): Move the asyncio worker supervision from entrypoints/orchestrator.py into a new entrypoints/workers.py (`Workers`). Reduce the Orchestrator to about 100 lines of wiring and the loop, add the architecture guards, and update the spec and CLAUDE.md. Behavior is unchanged, and the work fits in one run.
- 2026-11-11 14:58 samba: plan.accept: plan-review -> work-todo
- 2026-11-11 14:58 samba: dispatch_work: work-todo -> work-running
- Implemented as planned: new entrypoints/workers.py (`Workers`), thin Orchestrator (~80 lines), architecture tests (workers.py in lists, thin/no-rule test), test_scenarios uses `orch.workers.wait_all()`. pyright 0 errors, full pytest green (693).
- Spec changes: docs/spec/architecture.md (entry points row, Journal row, Orchestrator parts table with Tick/Workers/Orchestrator, architecture test list), docs/spec/orchestrator.md (intro), CLAUDE.md map (orchestrator.py and workers.py bullets). No ADR: ADR 0015 covers it.
- 2026-11-11 15:05 samba: done: work-running -> work-review: validation passed (turns 2, $0.46): I moved the worker lifecycle into a new `entrypoints/workers.py` (`Workers`) and cut `entrypoints/orchestrator.py` to about 80 lines of wiring and the poll loop. `uv run pyright` reports 0 errors and the full `uv run pytest -q` passed (693 tests), including `lifecycle.json` and the under-one-second test. I edited the architecture spec chapter, the orchestrator spec chapter and the CLAUDE.md map. I added a size and no-rule test for the orchestrator and put `workers.py` in the architecture test lists.
- 2026-11-11 15:09 samba: work.accept: work-review -> done: merged 8329025, validated
