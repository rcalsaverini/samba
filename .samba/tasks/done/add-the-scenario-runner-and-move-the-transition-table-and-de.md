---
priority: 3
depends_on: ["introduce-the-ports-skeleton-the-clock-and-the-id-generator"]
---
# Add the scenario runner and move the transition table and dependency rules to the domain

Part 2 of 7 of the refactor that ADR 0011 starts. Read docs/adr/0011 and 0012 first, and 0005, 0009 and 0010 for context. Follow them; do not re-decide them.

Behavior does not change. The black-box suite must pass unchanged; if you must change a black-box test, say why in your log. Keep pyright strict at 0 errors. Layout: pure `src/samba/domain/`, use cases in `src/samba/app/`, ports in `src/samba/ports.py`, adapters in `src/samba/adapters/` (the skeleton exists from part 1).

Scope:
- Move the pure parts of `transitions.py` into `domain/`: the TRANSITIONS table, the effects (using the Clock port from part 1), `human_row`, `human_events`, the markdown table renderer. `Machine.fire` and `observe`, which do file IO, stay where they are for now and import from the domain.
- Make `deps.evaluate` pure: it takes a snapshot (task id, status, depends_on for every task) instead of a `TaskStore`. The store builds the snapshot. Move it to `domain/`.
- The scenario runner of ADR 0012: `tests/scenarios/*.json` plus `tests/test_scenarios.py`, which loads them and runs them in-process. It may import the domain and use cases only, never an adapter. Document the scenario format in the spec (architecture chapter).
- First scenarios: transition legality and effects (given a state and sidecar fields, an event and an actor, expect the destination, the effects and the guards), hand moves (`human_row`), the legal events per state, and the dependency evaluation (ready, waiting, discarded, cycle, unknown ids).
- Part 1 left `SystemClock()` defaults in `transitions.py` (`log_line`, `entry_line`, `Machine`) and in `tasks.py` (`SidecarStore`). Nothing in the domain may import `samba.adapters`, so for everything you move into `domain/` make the clock a required parameter and pass it explicitly from the callers (`Machine`, the orchestrator, the CLI). Defaults to the system adapter stay only in the adapter-side constructors (`SidecarStore`, `Orchestrator`) until part 6 builds the composition root. Check the domain list in `tests/test_architecture.py` catches an `adapters` import in a moved module.
- Add the moved modules to the list in `tests/test_architecture.py`.

Done when:
- The domain modules pass the architecture test, and `samba dev transitions` output is byte-identical (the states chapter embeds it).
- The scenarios cover every row of the table at least once.
- The spec step is done, and pyright and the tests pass.

## Plan
### Plan: scenario runner, domain move of transitions and deps

### Approach

The moved code cannot import `samba.tasks` today, because `tasks.py` imports `adapters.system`, `pathlib`, `os` and `datetime`. The rule in `tests/test_architecture.py` also bans `datetime`, `os`, `time` and `logging` in domain modules. So the domain has to own the small pure types the table depends on, and the clock port has to provide timestamp formatting.

Plan:

1. Create `src/samba/domain/` with these modules:
   - `states.py`: `State`, `STATES`, `Stage`, `CAUSE_*`, `todo_of`, `running_of`.
   - `questions.py`: `Question`, `qint`, `qstr`, `question_number`, `latest_round`, `round_questions`, `open_questions`, `add_questions`, `answer_question`, `dismiss_open`, `render_questions`, `round_pairs`.
   - `sidecar.py`: the `Sidecar` dataclass only. `SidecarStore` stays in `tasks.py`.
   - `transitions.py`: `Actor`, `Transition`, `_t`, `TRANSITIONS`, `EFFECTS`, `KNOWN_GUARDS` plus the import-time asserts, `EVENTS`, `log_line`, `entry_line`, `human_row`, `human_events`, the stage-guard helpers, `apply_row`, `TABLE_BEGIN`/`TABLE_END`, and `render_markdown_table`.
   - `deps.py`: `DepStatus`, a snapshot type and a pure `evaluate`.
2. `tasks.py` re-imports the moved names (`from samba.domain.states import ...` and so on), so the callers `cli`, `views`, `orchestrator` and `claude` keep working without a mass edit. Prefer re-exports over rewriting every import, but pyright strict needs `__all__` or explicit `as` re-exports. Simpler: update the imports in the few callers.
3. `src/samba/transitions.py` becomes the IO shell: `DEBUG_FIRE_DELAY`, `kv`, `log`, `Machine` (`fire`, `observe`, `_guards_ok`) and `GuardFn`. It imports from `samba.domain.transitions`. It also re-exports `TRANSITIONS`, `human_row`, `human_events`, `log_line`, `render_markdown_table`, or the callers import them from the domain directly. Pick the latter and update the callers: `cli.py`, `views.py`, `orchestrator.py`.
4. Clock port: `datetime` is forbidden in the domain, but `now_iso` and `log_line` format local time. Add two formatting methods to the `Clock` Protocol in `ports.py`:
   - `iso_seconds() -> str`, local-offset ISO, for example `datetime.fromtimestamp(t).astimezone().isoformat(timespec="seconds")`.
   - `log_stamp() -> str`, `"%Y-%m-%d %H:%M"` in local time.
   - `SystemClock` in `adapters/system.py` implements both with the same formulas as today, so output is byte-identical.
   - The domain calls `clock.iso_seconds()` and `clock.log_stamp()` and never imports `datetime`.
   - Record this in the architecture chapter (Ports table) and in the task `## Log`.
5. Required clocks: in the domain, `log_line(message, clock)` and `entry_line(row, message, clock)` take a required `Clock` (no `None` default), and so do the question helpers (already required). `Machine.__init__` takes a required `clock`. Pass `SystemClock()` explicitly from the CLI call sites (`Machine(tasks, sidecars)` at roughly lines 221, 376 and 487) and `self.clock` from the orchestrator (already done). `cli.py` `log_line(...)` at about line 372 needs a clock argument. `orchestrator.py` line 225 `log_line(` needs `self.clock`, and line 94 already passes it. Only `SidecarStore` and `Orchestrator` keep `SystemClock` defaults. Remove the `SystemClock` import from `transitions.py`.
6. Pure `deps.evaluate`:
   - `@dataclass(frozen=True) class TaskRef: id, status: State, depends_on: tuple[str, ...]`.
   - `Snapshot = Mapping[str, TaskRef]`.
   - `evaluate(snapshot, task_id) -> DepStatus`. A missing id in `depends_on` means unknown (`state is None`). The task itself is in the snapshot.
   - Port the logic unchanged: the cycle check walks only tasks whose status is not `done`, then waiting, unknown and discarded as before.
   - `TaskStore` gets `deps_snapshot(task: Task) -> dict[str, TaskRef]`, which walks the `depends_on` closure from the task (`find` per id, as `_in_cycle` does today) so per-tick cost stays the same. Update the three call sites: `views.py` lines about 76 and 144, `orchestrator.py` lines about 103 and 288. Change them to `evaluate(self.tasks.deps_snapshot(task), task.id)`.
   - Delete the top-level `src/samba/deps.py`.
7. Scenario runner (`tests/test_scenarios.py`):
   - Allowed to import `samba.domain.*`, and `samba.app.*` later. Never `samba.adapters` or `samba.tasks`.
   - Needs a tiny in-test `FakeClock` (time and monotonic, plus the two formatters, fixed). Because the runner may not import an adapter, the fake lives in the test file.
   - Loads every `tests/scenarios/*.json`, parametrizes by file and scenario name, and dispatches on `kind`.
   - The scenario format is plain data. Each file is `{"kind": "...", "scenarios": [{"name": ..., ...}]}`.
8. Scenario kinds and files:
   - `transition.json` (`kind: "transition"`): `given` = `{state, sidecar: {fields}, deps_met: bool, plan_required: bool}`, `event`, `actor`, optional `ctx` (`error`, `delay`), and a `clock_time`. `expect` is either `{"fires": false}` or `{state, sidecar: {changed fields}, effects: [...], guards: [...]}`.
     - The runner picks the row the same way `Machine.fire` does (first row matching event, src, all guards, where guards are the stage guards via the domain helper plus `deps_met`/`plan_required` from `given`).
     - It applies the row with `apply_row`.
     - It asserts the destination, the changed sidecar fields and the list of effect names.
     - Cover every one of the 43 or so table rows at least once, including both `last_stage=*` and `unset` variants of `question.answer` and `task.retry`, and every `task.discard` source. Add a test in `test_scenarios.py` that fails when a row of `TRANSITIONS` is not hit by any scenario (key `(src, event, guard, dst)`), so coverage is enforced.
     - Also cover negative cases: a guard failing (`deps_met` false, `plan_required` false) and a wrong actor or state.
   - `human_row.json` (`kind: "human_row"`): `{src, dst, sidecar}` gives `{event}` or `null`. Include `work-review -> work-todo` expecting `work.reject` and not `work.reject_fresh`.
   - `human_events.json` (`kind: "human_events"`): `{state, sidecar}` gives the ordered list of events, one per state, with the `last_stage` variants for `question` and `stuck`.
   - `deps.json` (`kind: "deps"`): `{tasks: [{id, status, depends_on}], task: id}` gives `{kind, waiting, unknown}`. Cases: no deps, all done (ready), one todo (waiting), a discarded dep, a cycle (self, two-node and three-node), an unknown id (waiting with unknown), a cycle through a done task (not a cycle), and discarded beating waiting.
9. `tests/test_architecture.py`:
   - Set `DOMAIN_MODULES` to `["ports.py", "template.py", "prompts.py", "domain/__init__.py", "domain/states.py", "domain/questions.py", "domain/sidecar.py", "domain/transitions.py", "domain/deps.py"]`, and drop `deps.py`.
   - Add a test that writes a temporary module (use `tmp_path` and call the import-scan helper directly) containing `from samba.adapters.system import SystemClock` and `import datetime`, and assert the scanner flags both. This shows the check catches an `adapters` import in a moved module. Refactor the loop body into a helper `violations(path)` for this.
   - Keep `test_no_direct_clock_or_uuid_calls` (it covers `orchestrator.py` and `transitions.py`) and add the domain files to it.
   - Add a guard that `tests/test_scenarios.py` imports no `samba.adapters` or `samba.tasks`, via `imported_modules`.
10. Spec: update `docs/spec/architecture.md`.
    - Layers and "where each concern lives today": the domain now holds states, questions, sidecar, transitions and deps. `transitions.py` keeps only `Machine`.
    - Ports table: the new `Clock` methods.
    - New "Scenarios" section: file layout, the JSON format per kind (given, event, actor, expect), the runner rules (imports, fakes live in the test), and the coverage rule for table rows.
    - Update the architecture-test paragraph (new list).
    - Check `docs/spec/states.md` and `docs/spec/orchestrator.md` for references to `transitions.py`/`deps.py` paths and update them. The states chapter embeds `samba dev transitions` output, which must not change.
    - Update the CLAUDE.md map: add `domain/`, and adjust the `transitions.py` and `deps.py` entries. Prose has no em-dashes.
11. Log in the task file `## Log`: the Clock port additions, the `deps_snapshot` design, any black-box test change (none expected), and the spec edits.

### Steps
- [ ] Read `docs/spec/states.md`, `docs/spec/orchestrator.md` (Dependencies), `docs/adr/0005`, `0009`, `0010`, and `tests/test_transitions.py` for overlap.
- [ ] Byte-identity of `samba dev transitions` is checked by the existing black-box `tests/test_transitions.py`, which compares it with the states chapter. No baseline file is needed. Do not redirect output to files or pipe commands: the allow list denies them and the denial becomes a question for the human.
- [ ] Write `tests/scenarios/*.json` and `tests/test_scenarios.py` first (they fail on import until the domain exists). Write the architecture test additions.
- [ ] Extend the `Clock` port and `SystemClock` with `iso_seconds` and `log_stamp`.
- [ ] Create `domain/states.py`, `questions.py`, `sidecar.py`. Make `tasks.py` import from them and drop its `datetime` use for `now_iso`.
- [ ] Create `domain/transitions.py` and slim `src/samba/transitions.py`. Make the clock required, with no `SystemClock` in `transitions.py`.
- [ ] Create `domain/deps.py` and `TaskStore.deps_snapshot`. Update `views.py` and `orchestrator.py`. Delete the old `deps.py`.
- [ ] Update the callers (`cli.py`, `views.py`, `orchestrator.py`) for imports and explicit clocks.
- [ ] Update `DOMAIN_MODULES` and the architecture tests.
- [ ] Update the spec (architecture chapter plus the references) and `CLAUDE.md`.
- [ ] Run `uv run pyright`, then `uv run pytest -q`. Write the log entry.

### Files to change
- New: `src/samba/domain/{__init__,states,questions,sidecar,transitions,deps}.py`, `tests/scenarios/{transition,human_row,human_events,deps}.json`, `tests/test_scenarios.py`.
- Edit: `src/samba/{transitions,tasks,ports,orchestrator,cli,views}.py`, `src/samba/adapters/system.py`, `tests/test_architecture.py`, `docs/spec/architecture.md` (plus `states.md` and `orchestrator.md` if they cite paths), `CLAUDE.md`.
- Delete: `src/samba/deps.py`.

### Risks
- **Timestamp format drift.** The new clock methods must reproduce the current formats exactly (the log stamp `%Y-%m-%d %H:%M`, and the question `asked_at` ISO with `astimezone()`). Copy the existing expressions verbatim into `SystemClock`.
- **Circular imports.** `tasks.py` imports domain, and domain must never import `tasks`. `config.py` stays out of the domain.
- **Sidecar loading.** `SidecarStore.load` uses `fields(Sidecar)`. The dataclass moves but stays the same, so this is unchanged. Keep the `default_factory` typing for pyright strict.
- **Import-time asserts** in the table module must still run (keep them in `domain/transitions.py`).
- **Row selection mirror.** `Machine.fire` picks the first matching row, and so does the scenario runner. Keep one shared helper in the domain (for example `find_row(src, event, guards_ok)`) so the runner and `fire` cannot diverge. `work.reject_fresh` must stay after `work.reject`.
- **`snapshot` cost.** Building the full snapshot for every task would add file reads, so use the closure-based `deps_snapshot`.
- **Scenario independence.** Keep the runner's `FakeClock` inside the test, because it cannot import an adapter.
- **Existing coverage test.** `tests/test_transitions.py` is black-box and reads `dev transitions`, so it must pass unchanged.

### How to verify
- `uv run pyright` reports 0 errors.
- `uv run pytest -q` passes, including the new `test_scenarios.py` row-coverage test and the architecture tests (the negative test proves an `adapters` or `datetime` import is caught).
- `tests/test_transitions.py` passes unchanged, so the output of `uv run samba dev transitions` still equals the table in the states chapter.
- `git diff` shows no change to `tests/test_blackbox.py` (and any other black-box test).
- `git grep -n "samba.adapters" -- src/samba/domain` finds nothing (use `git grep`: plain `grep` is not in the allow list).

### Suggested subtasks
None needed; the work is one coherent refactor. If it is too large, split into (a) the domain move plus architecture test and (b) the scenario runner plus scenarios plus spec.

## Assumptions
- `datetime` stays forbidden in the domain, so the `Clock` port gains two formatting methods (`iso_seconds`, `log_stamp`) rather than relaxing the architecture test.
- The domain also takes over `State`/`STATES`, the `CAUSE_*` constants, `Question` and its pure helpers, and the `Sidecar` dataclass. The table's effects need them and `tasks.py` is not importable from a pure domain module.
- `evaluate` takes a snapshot keyed by id plus the task id. `TaskStore.deps_snapshot` builds only the dependency closure of the task, to avoid extra disk reads per tick.
- The `kv` log helper and `DEBUG_FIRE_DELAY` stay in the IO shell `src/samba/transitions.py`, because they use `logging`, `os` or `time`.
- The scenario runner defines its own in-test fake clock, because it may not import `samba.adapters`.
- The `samba/app/` use-case package has nothing to hold yet and is not populated in this part.
- Decided by the reviewer after plan review: verification commands must fit the allow list in WORKFLOW.md (no `>` redirects, no pipes, `git grep` instead of `grep`), so no permission denial turns into a question. `domain/sidecar.py` is an interim home for the `Sidecar` dataclass: part 5 replaces it with the `Task` aggregate, so do not add behavior to it here.

## Log
- 2026-11-10 18:53 samba: dispatch_plan: plan-todo -> plan-running
- 2026-11-10 18:54 samba: planned: plan-running -> plan-review: planned (turns 1, $0.27): Create `samba/domain/` (states, questions, sidecar, transitions, deps), make `deps.evaluate` and the clock pure and explicit, keep `Machine`/`observe` as an IO shell, add a JSON scenario runner (`tests/scenarios/*.json` + `tests/test_scenarios.py`), and document the format in the architecture chapter.
- 2026-11-10 18:54 samba: plan.accept: plan-review -> work-todo
- 2026-11-10 18:54 samba: dispatch_work: work-todo -> work-running
- Work done, all steps of the plan ticked (pyright 0 errors, 406 tests pass). Decisions and deviations:
  - Clock port gained `iso_seconds()` and `log_stamp()`; `SystemClock` uses the old expressions verbatim. The domain calls them and never imports `datetime`. `now_iso` is gone from `tasks.py`.
  - Clocks are required in the domain (`log_line`, `entry_line`, question helpers). `Machine.__init__` is now `(tasks, sidecars, clock, guard=None)`, clock required and no `SystemClock` in `transitions.py`; the CLI passes `SystemClock()` explicitly. Only `SidecarStore` and `Orchestrator` keep the default.
  - `deps.evaluate(snapshot, task_id)` is pure over `Mapping[str, TaskRef]`; `TaskStore.deps_snapshot(task)` builds the closure of `depends_on` (does not expand done tasks, absent id = unknown). Old `src/samba/deps.py` deleted; views and orchestrator call sites updated.
  - Added `find_row(event, src, guard_holds)`, `guard_names`, `stage_guard_ok` (public) and `apply_row` (was `_apply`) to `domain/transitions.py`; `Machine.fire` uses `find_row`, so fire and the scenarios cannot diverge.
  - The unset-stage `question.answer`/`task.retry` rows to work-todo are shadowed by the plan-todo ones in `fire` (same guard, first row wins), so they are reachable only as observed hand moves. Scenarios reach them with `hand_move_to` (picks via `human_row`). Documented in the Scenarios section.
  - Callers import from `samba.domain.*` directly (no re-exports from `tasks.py`).
  - No black-box test changed; `tests/test_transitions.py` passes unchanged, so `dev transitions` output still matches the states chapter.
  - Spec edits: `architecture.md` (layers, Clock port, where concerns live, new Scenarios section, architecture-test paragraph), `states.md` (table path), `CLAUDE.md` map.
- 2026-11-10 19:02 samba: permission denied: Bash (mkdir src/samba/domain tests/scenarios)
- 2026-11-10 19:05 samba: done: work-running -> work-review: validation passed (turns 2, $1.41): The transition table, effects, row helpers and dependency rules now live in `src/samba/domain/`, and the JSON scenario runner (`tests/scenarios/*.json` + `tests/test_scenarios.py`) covers every table row. pyright reports 0 errors and all 406 tests pass, with no black-box test changed. The work is committed, and the architecture chapter, `states.md` and `CLAUDE.md` are updated.
- 2026-11-10 19:09 samba: work.accept: work-review -> done: merged d55fa46, validated
