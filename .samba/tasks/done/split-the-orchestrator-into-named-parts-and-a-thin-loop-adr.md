---
priority: 3
depends_on: ["add-entrypoints-rename-compose-to-bootstrap-enforce-the-root"]
---
# Split the orchestrator into named parts and a thin loop (ADR 0015)

Read CLAUDE.md, docs/spec/architecture.md and ADRs 0011 to 0015 first. Behavior does not change: the black-box suite and every other test stay green, and pyright stays at 0 errors. Update the architecture chapter, the orchestrator and cli spec chapters where they change, and the CLAUDE.md map in the same change. Plan steps may use only commands in the WORKFLOW.md allow list: no git mv, no sed -i, no mkdir, no pipes or redirects. Move a file by writing it at its new path and git rm of the old one, then fix imports with Edit (git grep finds them). If the work is too big for one run at the per-task cost cap, propose chained subtasks in the plan.

Implement ADR 0015. entrypoints/orchestrator.py holds four jobs in one class: startup checks, the poll loop, the lifecycle of asyncio workers, and the rules of one task run (turn setup and prompt variables, finish, and the retry, reflect or give-up decision). Split into: Startup (app/), RunTask (app/) with a prompt and turn-setup builder and a finish-or-fail rule in their own app/ modules, Workers (entrypoints/, the asyncio supervision including what happens to a cancelled worker), and a thin Orchestrator (entrypoints/) of about a hundred lines that only wires startup, tick and sleep. Tick stays as it is. App modules import no asyncio and no adapter (extend APP_MODULES in tests/test_architecture.py). Add unit or scenario tests that run Startup and RunTask with the existing fakes and no loop, keep tests/scenarios/lifecycle.json passing, and update the orchestrator and architecture spec chapters.

## Plan
### Approach

Behavior does not change. This task is step 1 of 2 of ADR 0015. The next task, created separately, adds `entrypoints/workers.py` and the thin Orchestrator of about 100 lines, the size test, and the `orch.workers.wait_all()` change in `tests/test_scenarios.py`. None of that is done here.

Here, every rule leaves `entrypoints/orchestrator.py` and moves, verbatim, into new `app/` modules. None of the new modules imports `asyncio`, an adapter, `os`, `pathlib`, `logging` or `subprocess`. The existing `Orchestrator` stays one class that owns the poll loop and the asyncio workers (`_spawn`, `work`, `_work`, `_on_worker_done`, `shutdown`, `run`, `tick`, `cleanup_workspaces`), but it builds the new parts and delegates to them.

New modules in `app/`:
- `app/guard.py`: `Guard(require_plan: bool, tasks: Tasks)`. `__call__(name, task) -> bool` is the `plan_required` and `deps_met` guard now in `Orchestrator._guard`. It is passed to `Machine`.
- `app/startup.py`: `StartupError` and `Startup(config_warnings, tasks, vcs, agent, machine, journal)`. `async run()` does the old `startup()`: `tasks.prepare()` (StoreError becomes StartupError), `vcs.repository_problem()`, `agent.ready()` (not ready leads to the same "claude auth status says not logged in; run `claude auth login`. <detail>" message), config warnings at `warning` level, `vcs.exclude_samba_dir()`, and `recover` ("recovered at startup", journal event `recovered`) for tasks left in `plan-running` or `work-running`.
- `app/prompt_builder.py`: `PromptBuilder(config, tasks, vcs)`. Methods: `variables(task, ws)`, `system_prompt(variables, task)`, `prompt(key, variables)` (with the questions fallback for custom `resume` and `plan_revise` prompts), `first_plan_prompt(variables)`, and `setup(task, ws, stage) -> TurnSetup` (the old `_setup`). It raises `TemplateError` as before.
- `app/finish.py`: `Finisher(policy, machine, turns, builder, tasks, vcs, journal)`. `finish(task, event, what, summary="")` is the old `_finish`. `fail(task, error)` is the old `_fail`: it computes the `RetryPolicy` decision, logs `attempt_failed`, then either fires `retry_plan` or `retry_work`, or reflects (via `should_reflect` and `turns.invoke` with the `give_up` prompt, suppressing `TemplateError`) and fires `give_up`.
- `app/run_task.py`: `RunTask(tasks, vcs, turns, builder, finisher, journal)`. `async run(task_id, on_turn)` is the old `_work`: get the task, `ensure_workspace` (WorkspaceError goes to `fail`), the `workspace_created` journal event, set workspace and branch and save, build the setup (TemplateError goes to `fail`), `turns.run`, then `fail` or `finish`. `async crashed(task_id, error)` logs `worker_crashed` through `journal.exception` and calls `fail(task, "internal error: ...")` if the task still exists.
- `app/tick.py`: replace `import asyncio` and `task: asyncio.Task[None]` with a `Cancellable` Protocol (`def cancel(self) -> bool`) and `task: Cancellable`. Nothing else changes.

`entrypoints/orchestrator.py` after this task: the constructor keeps its signature and builds `Guard`, `Machine`, `Notes`, `TurnFlow`, `PromptBuilder`, `Finisher`, `RunTask`, `Startup` and `Tick`. `startup()` calls `self.startup_check.run()`. `_work` is replaced by a call to `run_task.run(task_id, on_turn)`. The `CancelledError` branch stays here (journal `stopped`, `recover` on shutdown, workspace removal on `moved`). The `except Exception` branch calls `run_task.crashed`. The loop, `_spawn`, `_on_worker_done`, `shutdown` and `cleanup_workspaces` stay as they are. Remove `_guard`, `_setup`, `_first_plan_prompt`, `_finish`, `_fail`, `_variables`, `_system_prompt`, `_prompt`, and the imports that become unused. `StartupError` is no longer defined here.

### Steps

- [ ] Read CLAUDE.md, docs/spec/architecture.md, docs/spec/orchestrator.md, docs/spec/prompts.md and docs/adr/0011 to 0015 (use `git grep` and Read; `samba adr show` may not work in the sandbox). Read src/samba/entrypoints/orchestrator.py, app/tick.py, app/turn.py, app/machine.py, tests/test_scenarios.py (`play`), tests/test_architecture.py, and the fakes in tests/ (fake_tasks if present, fake_vcs, fake_agent, fake_validator, fake_journal, and `FakeClock`).
- [ ] Tests first. Write `tests/test_app_startup.py` with the existing fakes and a real `Machine`: store error, repository problem and not-logged-in agent each raise `StartupError` with today's message; config warnings are journaled at `warning` level; `plan-running` and `work-running` tasks are recovered to their todo folders with the log line "recovered at startup" and a `recovered` journal event; `exclude_samba_dir` is called. Use `asyncio.run` only as the test driver.
- [ ] Write `tests/test_app_run_task.py` with the same fakes: a plan run and a work run each end in the right transition with the log message "(turns N, $x)"; an `ensure_workspace` failure retries and later gives up at `max_attempts`; a TemplateError fails the attempt; `crashed` leads to a failed attempt with "internal error"; `reflect_on_give_up` sends the `give_up` prompt with resume only when `should_reflect` allows; `PromptBuilder` variables and prompts (answers appended to a custom `resume` prompt that lacks `{{ questions }}`, `APPROVED_PLAN_RULE` when `plan_approved`, plan stage with `max_turns=1` and validation disabled). Pin expected prompt texts from `docs/spec/prompts.md` and the existing black-box tests. Also add a small `Guard` test (`plan_required`, `deps_met`, unknown name is False).
- [ ] Extend `tests/test_architecture.py`: add `app/guard.py`, `app/startup.py`, `app/prompt_builder.py`, `app/finish.py` and `app/run_task.py` to `APP_MODULES`; add a test that no `APP_MODULES` entry imports `asyncio`, with a self-check on a tmp file like the existing "catches" tests; update the comment on `APP_FORBIDDEN`. Leave `ENTRYPOINT_FILES` as it is (no `workers.py` yet).
- [ ] Write the new app modules with Write, copying the logic verbatim from the old class. Edit `app/tick.py` for the `Cancellable` Protocol.
- [ ] Edit `entrypoints/orchestrator.py` to delegate as described. Edit `entrypoints/cli.py` to import `StartupError` from `samba.app.startup`. Find other users with `git grep -n "StartupError\|_guard\|orchestrator import"`.
- [ ] Edit `tests/test_scenarios.py::play` only as far as delegation requires: build the machine with a `Guard(config.policy.require_plan, tasks)` instead of `orch._guard`. Leave `orch.running` and the rest alone. `tests/scenarios/lifecycle.json` stays unchanged and passing, including the under-one-second test.
- [ ] Update the spec and CLAUDE.md (see Spec changes).
- [ ] Run `uv run pyright` (0 errors), then `uv run pytest -q`, as separate plain commands. Fix failures. Use no pipes, redirects, `git mv` or `sed -i`.
- [ ] Add a line to the task file's `## Log` saying what spec and CLAUDE.md changed.

### Files to change

- New: `src/samba/app/guard.py`, `app/startup.py`, `app/prompt_builder.py`, `app/finish.py`, `app/run_task.py`, `tests/test_app_startup.py`, `tests/test_app_run_task.py`.
- Edited: `src/samba/entrypoints/orchestrator.py`, `src/samba/entrypoints/cli.py`, `src/samba/app/tick.py`, `tests/test_architecture.py`, `tests/test_scenarios.py` (the guard only), `CLAUDE.md`, `docs/spec/architecture.md`, `docs/spec/orchestrator.md`.
- `bootstrap.py`: no change expected (same constructor signature).
- `docs/spec/cli.md`: one line, only if it names where `StartupError` or startup lives.
- Not in this task: `entrypoints/workers.py`, the thin Orchestrator, the size test, `orch.workers.wait_all()`. They are the next task.

### Spec changes

- `docs/spec/architecture.md`: say that the orchestrator split lands in two steps (ADR 0015). Replace "kept as it is until ADR 0015 splits it" with the state after step 1: `orchestrator.py` still holds the loop and the asyncio workers but delegates every rule to `app/` (`Startup`, `RunTask` with `PromptBuilder` and `Finisher`, `Guard`); `Workers` and the thin `Orchestrator` come in step 2. List the new app use cases. Update the `Journal` injection list (add `Startup`, `RunTask`, `Finisher`). In the guard section, say app modules import no `asyncio` and that `Running.task` is a `Cancellable`. Mention that `Startup` and `RunTask` are tested with the fakes without a loop.
- `docs/spec/orchestrator.md`: note which part owns what now (Startup for startup checks and recovery, Tick, RunTask for the run of one task with PromptBuilder and Finisher, the Orchestrator class still for the loop and the workers until step 2). The behavior text stays the same.
- `docs/spec/cli.md`: none, unless it names where `StartupError` lives; then one line.
- `CLAUDE.md` map: add `app/guard.py`, `app/startup.py`, `app/prompt_builder.py`, `app/finish.py`, `app/run_task.py` and the two new test files; change the `entrypoints/orchestrator.py` entry to "poll loop and asyncio workers; delegates the rules to `app/`; split further by the next task (ADR 0015)"; mention `StartupError` is in `app/startup.py`.

### Risks

- Cost cap: this is a verbatim move plus two test files, which is what the cap allows. If it still runs over, commit the app modules and their tests first so the work is not lost.
- `Cancellable` typing: `asyncio.Task.cancel(msg=None) -> bool` satisfies the Protocol structurally. In `Orchestrator.shutdown` and `play`, `entry.task` is typed `Cancellable`, so `asyncio.gather(*(e.task ...))` will not type-check (it needs awaitables). In step 1 keep a typed `dict[str, asyncio.Task[None]]` of the workers in the Orchestrator (used for `gather`) next to `running`, or `cast` at that one point. In `play`, gather through a small public Orchestrator method (for example `await orch.wait_workers()`) rather than `e.task`. This is a delegation-driven test change and is replaced by `workers.wait_all()` in step 2.
- Cancellation ordering: the done-callback pops `running` and releases notes, `stop_reason` is read in the cancel handler before the callback runs, and `recover` on shutdown happens inside the worker. Keep this exactly as it is.
- `Notes.add` depends on `running` membership, so Tick and the Orchestrator must keep sharing the same `running` dict and `Notes`.
- The storage-vocabulary test scans app modules for `Path`, `mtime`, `sidecar` and `front matter`. Avoid those words in code of the new modules (comments are stripped).
- Moving `StartupError` could break `cli.py` and the black-box tests that check the startup error messages and exit code.
- `test_every_domain_and_app_module_is_listed` fails until `APP_MODULES` is updated, so update it in the same change.

### How to verify

- `uv run pyright` reports 0 errors.
- `uv run pytest -q` is green: the black-box suite, the lifecycle scenarios, `test_architecture`, `test_manual`, `test_app_startup` and `test_app_run_task`.
- `git grep -n asyncio src/samba/app` returns nothing.
- `git grep -n "_guard\|_finish\|_fail\|_setup\|_variables" src/samba/entrypoints/orchestrator.py` returns nothing, and the old rule code is gone from it.
- `git grep -n "orchestrator import StartupError"` returns nothing.
- The CLAUDE.md map and the architecture and orchestrator chapters describe the new files and say the split lands in two steps.

## Assumptions
- `samba adr show 15` failed in the planning sandbox (installed samba is stale), so I read docs/adr/0015-*.md directly. I did not open ADRs 0011 to 0014, the spec chapters beyond grep hits, or tests/test_blackbox.py.
- "App modules import no asyncio" requires touching app/tick.py: `Running.task: asyncio.Task[None]` is its only asyncio use. I replace it with a small `Cancellable` Protocol (`def cancel(self) -> bool`). This changes a type only, and Tick's logic is untouched.
- `Notes` and `Running` stay in app/tick.py. The Orchestrator still owns `running` and `notes` and passes them to Tick.
- `StartupError` moves to `app/startup.py`. `entrypoints/cli.py` imports it from there. The old `entrypoints/orchestrator.py` no longer defines it. Importing it from there is not kept as a re-export.
- In this task the Orchestrator keeps its public surface (`startup()`, `tick()`, `cleanup_workspaces()`, `run()`, `running`, `work()`, `shutdown()`) and its constructor signature, so `bootstrap.py` needs no change. The scenario runner needs one change: `orch._guard` becomes a `Guard` built in `play`. `await asyncio.gather(*(e.task for e in orch.running.values()))` still works because `Running.task` is still an asyncio task at runtime; that is checked by pyright on the test only if the Protocol typing allows it (see Risks).
- Module names (`guard`, `startup`, `prompt_builder`, `finish`, `run_task`) are my choice. ADR 0015 fixes only the class names.
- The worker's catch-all (`except Exception`) and the cancelled-worker handling stay in the Orchestrator for now, and move to Workers in the next task. The catch-all calls `RunTask.crashed`.
- No new ADR is needed: ADR 0015 already records the decision. The spec text says the split lands in two steps.

## Feedback
### Round 1

The plan is correct and matches ADR 0015, but it is too big for one run at the $5 cap. Follow your own suggested subtasks and plan ONLY part 1 in this task: the app parts (app/guard.py, app/startup.py with StartupError, app/prompt_builder.py, app/finish.py, app/run_task.py), the Cancellable Protocol in app/tick.py, their tests (tests/test_app_startup.py, tests/test_app_run_task.py), the APP_MODULES and no-asyncio architecture tests, and the spec and CLAUDE.md updates for those modules. In this task the existing Orchestrator in entrypoints/orchestrator.py stays one class that still owns the loop and the asyncio workers (_spawn, work, shutdown), but it delegates every rule to the new parts: Guard for the machine guard, Startup for startup, RunTask for the run of one task (with PromptBuilder and Finisher behind it). Update entrypoints/cli.py to import StartupError from samba.app.startup, and adapt tests/test_scenarios.py only as much as the delegation requires (for example the guard now comes from Guard). entrypoints/workers.py, the thin Orchestrator of about 100 lines, the size test, and the orch.workers.wait_all() change in test_scenarios become a separate next task that I will create; do not do them here, and say in the plan and in the spec text that the orchestrator split lands in two steps. Keep everything else in your plan (verbatim moves, behavior unchanged, lifecycle.json unchanged and passing, avoid Path, mtime, sidecar and front matter in app modules, allow-listed commands only).

## Log
- 2026-11-11 14:41 samba: dispatch_plan: plan-todo -> plan-running
- 2026-11-11 14:42 samba: planned: plan-running -> plan-review: planned (turns 1, $0.27): Split entrypoints/orchestrator.py into app/ Startup, RunTask (with PromptBuilder and Finisher modules) and a Guard, an entrypoints/ Workers, and a ~100 line Orchestrator. Tick gets only a Protocol in place of asyncio.Task so app/ imports no asyncio. Tests for Startup and RunTask run on the fakes without a loop. One run should fit the cap, with a fallback split into two subtasks.
- 2026-11-11 14:43 samba: plan.reject: plan-review -> plan-todo: feedback round 1
- 2026-11-11 14:43 samba: dispatch_plan: plan-todo -> plan-running
- 2026-11-11 14:43 samba: planned: plan-running -> plan-review: planned (turns 2, $0.67): Revised plan covers only part 1 of the split: the app/ parts (Guard, Startup, PromptBuilder, Finisher, RunTask), the Cancellable Protocol in Tick, their tests and the spec and CLAUDE.md updates. The existing Orchestrator keeps the loop and the asyncio workers but delegates every rule to the new parts. Workers and the thin Orchestrator are left to a separate next task.
- 2026-11-11 14:44 samba: plan.accept: plan-review -> work-todo
- 2026-11-11 14:44 samba: dispatch_work: work-todo -> work-running
- Work, step 1 of ADR 0015 done: new app/guard, startup (StartupError), prompt_builder, finish, run_task; Cancellable Protocol in app/tick.py; Orchestrator delegates and keeps the loop and workers (plus a small public `wait_workers()` and a private `_workers` dict, since `Running.task` is a Cancellable and cannot be gathered; step 2 replaces them). Tests: tests/test_app_startup.py, tests/test_app_run_task.py, no-asyncio check in test_architecture.py, test_scenarios.py uses Guard and wait_workers. pyright 0 errors, pytest 691 passed before the spec edits.
- Spec changes: docs/spec/architecture.md (Orchestrator parts section, two-step split, Journal injection list, no-asyncio rule for app modules), docs/spec/orchestrator.md (who owns what), CLAUDE.md map (new modules and test files, orchestrator entry). cli.md names no startup location: unchanged. No new ADR: ADR 0015 records the decision.
- 2026-11-11 14:53 samba: done: work-running -> work-review: validation passed (turns 3, $1.50): Step 1 of ADR 0015 is done and committed. The orchestrator's rules now live in new `app/` modules (`Guard`, `Startup` with `StartupError`, `PromptBuilder`, `Finisher`, `RunTask`), and `Orchestrator` keeps the loop and the asyncio workers and delegates to them. pyright reports 0 errors and pytest passed (691) before the spec edits; I re-ran only `test_architecture` and `test_manual` afterwards. The new tests `test_app_startup.py` and `test_app_run_task.py` run on the fakes without a loop, and the architecture test now forbids `asyncio` in `app/`. Spec chapters (`architecture`, `orchestrator`) and the `CLAUDE.md` map are updated to say the split lands in two steps.
- 2026-11-11 14:57 samba: work.accept: work-review -> done: merged 1f4c2e3, validated
