---
priority: 2
---
# Explicit transition table, observed hand moves and task dependencies

Phase 1, part 2 of `docs/command-ideas.md`. **Depends on "Migrate to stage x status folder
layout" being merged first**: plan against the new folder names.

Make the state machine explicit: one declarative transition table in code, used by the
orchestrator for every move, and used to interpret moves the human makes by hand in the file
browser.

Read first: `docs/command-ideas.md` sections 3.3 (hand moves paragraph), 3.4 (the table), 4.2 and
4.3 (own table, no library, and its shape). SPEC section 4.

Decisions already made by the human:

- Own table, no FSM library (doc section 4). Plain data (`Transition` rows with src, event, actor,
  dst, guard, effects), so the Rust rewrite can reuse it.
- Event names are the future command names (`plan.accept`, `work.reject`, `question.answer`,
  `task.retry`, ...), even though the commands themselves come in later tasks.
- Hand moves stay supported. The sidecar records the last known `state`; each tick, a task file
  found in a different folder is looked up as `(last state, folder)`. A row that exists is an
  observed event: apply its effects and log it. A pair not in the table is an illegal move: log it
  to the task's `## Log` and move the file back.
- All remaining inference (for example detecting approval from `last_outcome`) is removed in favour
  of table rows and their effects.
- Task dependencies are part of this task, as guards on the dispatch rows:
  - Front matter `depends_on: [task-id, ...]` (optional, human-owned).
  - `dispatch_plan` and `dispatch_work` fire only when every dependency is in `done` (merged, so
    the new worktree, branched from the base branch, already contains it). `discarded` does not
    count. A waiting task stays in its `-todo` folder; no new folder.
  - Unknown dependency id: treated as unmet, warning in `symphony.log` (a typo must never unblock).
  - A dependency in `discarded`: the dependent task goes to `stuck` with
    `blocked_cause = dependency_discarded`.
  - A dependency cycle: every task in the cycle goes to `stuck` with
    `blocked_cause = dependency_cycle`.
  - `symphony status` shows `waiting on <id>[, <id>...]` for a task held only by dependencies.

Scope of this task:

- The table in `tasks.py` (or a new module if the plan argues for it), and a single `fire(task_id,
  event)` path that does the rename, the sidecar effects and the `## Log` line.
- Orchestrator transitions go through `fire`.
- Observed hand moves and illegal-move reversal as described above. Moving a task out of a
  `-running` folder still stops its agent; decide (and spec) which targets are legal for that.
- SPEC section 4.1 shows the table as Markdown, generated from or checked against the code so they
  cannot drift.
- Tests: one parametrized black-box test per table row (set up the source state, cause the event,
  assert folder, sidecar effects and `## Log`), a test that every row is covered, and tests for
  illegal hand moves being moved back.
- Dependency tests: a task waits while its dependency is in any non-`done` folder and runs once it
  is in `done`; several dependencies (all must be done); unknown id stays waiting; discarded
  dependency goes to `stuck`; a two-task cycle goes to `stuck`; `status` shows `waiting on`;
  dependencies gate planning as well as execution.
- SPEC: a section on dependencies (front matter field, guard semantics, status display).

Out of scope: the new CLI commands (`plan accept`, `work accept`, ...). They come next and will call
`fire`.

Acceptance criteria:

- `uv run pyright` reports 0 errors and `uv run pytest -q` passes.
- No transition happens outside the table.
- Every row has a test; the coverage test fails if a row is added without one.
- Dependencies work as specified, with the tests listed above.

## Plan
### Approach

I read `orchestrator.py`, `tasks.py`, `cli.py` (`cmd_status`), `tests/conftest.py`, SPEC §2, §4, §5, §10, §14 and `docs/command-ideas.md` §3.3, §3.4, §4.2 and §4.3. Today `TaskStore.move` is called from about 10 places in `orchestrator.py` (startup recovery, `work()` on shutdown, `dispatch`, `_finish`, `_fail` twice). The dispatch-time inference (`plan_session_id and not plan_approved`, `last_outcome in (blocked, failed)`, the `require_plan` branch) is what the table replaces.

**Design**

1. New module `src/symphony/transitions.py`. The table is plain data. It imports only `State` and `Stage` from `tasks.py`, to avoid a cycle.
   - `@dataclass(frozen=True) Transition(src, event, actor, dst, guard, effects)`.
   - `src` and `dst` are `State`. Rows with several sources or targets are expanded to one row per `(src, event)`, so the table is a flat list and the per-row test is trivial.
   - `dst` can depend on `last_stage`, for example `question.answer` and `task.retry`. Model this as separate rows with a guard string such as `last_stage=plan`. Each row is still unique on `(src, event, guard)`.
   - `guard` and `effects` are strings naming hand-implemented functions, as `docs/command-ideas.md` §4.3 says. There is no effect DSL.
   - Event names are the future command names: `dispatch_plan`, `dispatch_work`, `route_to_plan`, `planned`, `plan_blocked`, `done`, `work_blocked`, `budget`, `give_up`, `retry_plan`, `retry_work`, `recover`, `plan.accept`, `plan.reject`, `work.accept`, `work.reject`, `question.answer`, `task.retry`, `task.stop`, `task.discard`, plus dependency rows (below). The `new` row is omitted: it has no source folder.
   - A table that expands guard variants will have more rows than the 22 in the doc (§3.4). The tests count rows, so this does not matter.
2. Single path: `fire(task_id, event, *, note=None, **ctx) -> bool`, on a small `Machine` class in `transitions.py`. It holds the `TaskStore`, the `SidecarStore` and the log-line formatter.
   - It reads the current folder.
   - It finds the row by `(folder, event)` and evaluates the guard.
   - It applies the sidecar effects, then does the rename, then writes the `## Log` line and the `symphony.log` line.
   - It sets `sidecar.state = dst` (new field, see below).
   - It returns False if the file is no longer in `src`, matching the current `move` semantics. An event with no row raises or returns an error. This makes "no transition outside the table" true.
   - `TaskStore.move` becomes private to `fire` and to the illegal-move reversal path (rename it `_rename` or similar, and `grep` that no other caller remains).
   - Effects are named functions in a dict, for example `attempts=0`, `not_before=None`, `blocked_cause=<x>`, `plan_approved=True`, `clear_session`, `attempts+=1`, `retry_delay`, `last_stage=plan|work`. Each row's effects tuple names them.
   - Run-time effects that take values (`last_outcome`, `last_error`, cost summary text) are passed through `ctx`.
3. Sidecar: add `state: str | None` (last known folder). Update the `Sidecar` dataclass, SPEC §4.2, and the Rust-facing docs. `fire` writes it. Remove `last_outcome` inference everywhere. Keep `last_outcome` as a log-only field.
4. Hand moves, in `reconcile()` (a new `observe()` step, run first in each tick, before reconcile and dispatch):
   - For each task file in any folder, load the sidecar. If `side.state is None`, set it to the folder (first sight, including a hand-created task and migrated sidecars) and fire nothing.
   - If `side.state == folder`, nothing happens.
   - Otherwise look up `(side.state, folder)` among the rows with `actor == human` (a hand move is a human actor).
     - If a row exists: apply its effects, log "observed <event> (moved by hand from X to Y)", update `side.state`.
     - If none exists: append a `## Log` line "illegal move X -> Y, moved back to X", and rename the file back (no sidecar change). Also write a warning to `symphony.log`.
   - Moves out of `-running` by hand: legal targets are the matching `-todo` (`task.stop`, no attempt change) and `discarded` (`task.discard`). Targets `done`, `plan-review`, `work-review`, `question`, `stuck` and the other stage's folders are illegal and get moved back. The agent stop in `reconcile` still triggers when the file has left the running folder. Order matters: reversal moves the file back, so reconcile must not see the file as having left. Do `observe()` before the reconcile check, and for a running task whose file was moved to an illegal folder, move it back before reconcile so the agent keeps running. For a legal `task.stop` or `task.discard`, reconcile kills the agent as it does today. Settle this in SPEC §4.1/§5.2 and note it in the task `## Log`.
   - A file deleted by hand: unchanged from today (treated like `done`, SPEC §4.1 and §5.2, worktree removed). No table row. Spell this out in the SPEC.
   - `fire` must update `side.state` so Symphony's own moves are never seen as hand moves in the next tick. Use ordering: save the sidecar `state` before the rename if possible, otherwise save immediately after. The window between them is a race: `observe()` runs in the same event loop, and `fire` is synchronous, so there is no `await` between them and no race.
   - Any human row whose guard is `plan_approved` or `require_plan` also covers `work-todo -> plan-todo` (`route_to_plan`, actor symphony). Treat it as an in-tick Symphony event (see Dispatch).
5. Dispatch rewrite:
   - `dispatch_plan` fires for `plan-todo`, `dispatch_work` for `work-todo`.
   - `route_to_plan` (symphony): from `work-todo` when `planning.require_plan` and not `plan_approved`, move the task to `plan-todo`, then dispatch it as `dispatch_plan` in the same tick.
   - Delete the `approved` / `plan_session_id` inference. `plan.accept` (human row `plan-review -> work-todo`, effects `plan_approved=True`, clear `session_id`, `last_stage=work`) is the only way a plan becomes approved. Hand moves from `plan-review` hit that row through `observe()`. A task moved by hand `plan-todo -> work-todo` after a rejection has no row, so it is illegal and is moved back. This fixes the SPEC §14.3 "still an inference" caveat. Update §14.3.
   - The attempts reset on retry comes from the rows `question.answer` and `task.retry` (`attempts=0`) rather than checking `last_outcome` and `blocked_cause` at dispatch. `dispatch_*` effects: claim, `not_before=None`, `blocked_cause=None`, `last_stage`, `first_dispatched_at`. `last_error` is still cleared at the `*review` rows.
6. Dependencies:
   - `parse_task` reads `depends_on` from the front matter: a list of strings. A malformed value (not a list of strings) is ignored with a warning, like unknown keys. Add `depends_on: tuple[str, ...]` to `Task`.
   - A `dep_status(task) -> waiting(ids) | ready | discarded(id) | cycle` helper in `transitions.py` or `orchestrator.py`. It uses `TaskStore.state_of`.
     - Every id in `done`: ready.
     - Any id unknown: unmet and held (warn once per `(task, dep)` in `symphony.log`, so a typo never unblocks).
     - Any id in `discarded`: fire the new row `dependency_discarded` (`plan-todo`/`work-todo -> stuck`, effect `blocked_cause=dependency_discarded`). This takes priority over merely waiting.
     - A cycle (found by DFS over `depends_on` edges across non-done tasks): fire `dependency_cycle` (same sources, `stuck`, `blocked_cause=dependency_cycle`) for every task in the cycle. A self-dependency is a cycle.
     - Otherwise held in its `-todo` folder: no folder change, no log spam. Log once into `symphony.log` at most.
   - `dispatch_plan` and `dispatch_work` guards call `deps_met`. This also gates planning. Waiting tasks do not count toward `max_concurrent` and do not block `--exit-when-idle` from reaching "idle"? Decide: a task waiting on a dependency still counts as in `-todo`, so `--exit-when-idle` would never exit while a dependency is stuck in `question`. The simplest rule is to keep the exit condition as is (tasks in a todo folder keep the run alive), and add a regression test with an unmet dependency that is in a human-owned folder: exit-when-idle must not hang forever in tests. Make `exit-when-idle` ignore tasks held only by dependencies. A dependency in the same todo folder is not human-held, so it will run. Simplest correct rule: idle exit also when every remaining todo task is dependency-held and nothing is running. Document that in SPEC §11.
   - When the stuck dependent comes back by hand (`stuck -> work-todo` via `task.retry`), dependencies are checked again at dispatch.
   - `symphony status`: for a task in `plan-todo` or `work-todo` held only by dependencies, the LAST column shows `waiting on a, b`. When it is also in retry backoff, show the retry text. "Only by dependencies" means `not_before` is not in the future.
   - Add `depends_on` support to `Sandbox.add_task(..., depends_on=None)` in `tests/conftest.py`.
7. SPEC §4.1 table:
   - Add a generator in `transitions.py`, `render_markdown_table() -> str`, plus a tiny entry point (`python -m symphony.transitions`) that prints it.
   - Add a SPEC fenced region between `<!-- transitions:begin -->` and `<!-- transitions:end -->`.
   - Add a black-box test that runs `python -m symphony.transitions` as a subprocess (it must not import the `symphony` package) and compares the output to the SPEC region. This also keeps the Rust rewrite able to reuse the check. A drift test only works if the CLI prints the table; alternatively add a hidden `symphony transitions` subcommand and use it from the test. Pick the subcommand (cleaner for a future rewrite). Document it in SPEC §11.
   - Rewrite the rest of SPEC §4.1 around the table: remove the ASCII diagram and the sentence "Hand moves are not checked against the diagram", and replace them with the observed-move rule.
   - Update SPEC §5.1, §5.2 (the dispatch step and the reconcile step), §5.4 (the attempts reset sentence), §14.2, §14.3, §14.10, §10 (status), §3.2 (front matter `depends_on`) and §4.2 (`state`, `blocked_cause` values `dependency_discarded` and `dependency_cycle`).
   - Add a new SPEC section "Dependencies" (the last of the main numbered sections, before "Later", or §15) covering the front matter field, the guard semantics, the unknown, discarded and cycle cases, and the status display.

### Steps

- [x] Read `tests/test_blackbox.py` end to end to learn the helpers and style (`run_idle`, `popen`, `steps`, sidecar and log assertions) and note which existing tests rely on moving a file by hand: the illegal-move rule will break any that does `plan-todo -> work-todo` or similar.
- [x] Write the failing black-box tests first (list below). Add `depends_on` to `Sandbox.add_task`.
- [x] Create `src/symphony/transitions.py`: `Transition`, `TRANSITIONS`, effect and guard registries, `Machine.fire`, `render_markdown_table`.
- [x] Add `depends_on` parsing to `tasks.py`, `Sidecar.state`, and the new `CAUSE_DEPENDENCY_DISCARDED` / `CAUSE_DEPENDENCY_CYCLE` constants.
- [x] Route every orchestrator move through `fire`: startup `recover`; shutdown `recover`; `dispatch_*` and `route_to_plan`; `_finish` (`planned`, `done`, `plan_blocked`, `work_blocked`, `budget`); `_fail` (`retry_*`, `give_up`). Remove the `LEGACY`-free inference code in `dispatch`.
- [x] Add `observe()` to the tick, with illegal-move reversal and `task.stop` / `task.discard` handling for `-running` folders.
- [x] Implement dependency evaluation (waiting, unknown, discarded, cycle) and wire it into the dispatch guards, the idle-exit condition and `cmd_status`.
- [x] Add the `symphony transitions` subcommand and the SPEC region, and update the SPEC sections listed above (no em-dashes).
- [x] Run `uv run pyright` (0 errors) and `uv run pytest -q`; run them as separate plain commands. Fix existing tests that depended on old inference (they should be updated to use legal hand moves such as `plan-review -> work-todo`).
- [x] Append a note to the task file's `## Log` listing the SPEC details settled here (legal moves out of `-running`, unknown and deleted files, idle exit with dependencies).

### Files to change

- New: `src/symphony/transitions.py`.
- `src/symphony/tasks.py`: `Task.depends_on`, `parse_task`, `Sidecar.state`, cause constants, a private rename.
- `src/symphony/orchestrator.py`: all moves via `fire`, `observe()`, the dispatch rewrite, dependency guards, idle exit.
- `src/symphony/cli.py`: `waiting on` in status, `transitions` subcommand.
- `SPEC.md`: sections listed above, with the generated table region.
- `tests/conftest.py`: `add_task(depends_on=...)`, optional helpers for hand moves.
- `tests/test_blackbox.py`: new tests and updates to existing ones. This file must never import `symphony`.
- Possibly `tests/fake_claude.py` if a row needs a scripted outcome the fake cannot produce (it currently supports done, blocked, planned, failures).
- `CLAUDE.md` map: add `transitions.py`.

### Tests (written first)

- **Per-row parametrized test.** The parameter list is hard-coded in the test file as `(src, event, ...)` tuples, with a setup and a trigger per row. Triggers:
  - Symphony rows: script the fake claude, or place the task in the right state and call the real path.
    - `dispatch_*`, `planned`, `done`, `plan_blocked`, `work_blocked`, `give_up`, `retry_*`: scripted outcomes through `run_idle`.
    - `budget`: a fake step with high cost and a small cap.
    - `recover`: leave a file in `*-running` and start Symphony.
    - `route_to_plan`: `require_plan` set.
    - `dependency_discarded` and `dependency_cycle`: from the dependency tests.
  - Human rows: move the file by hand in the sandbox before running (observed event). Cover `plan.accept`, `plan.reject`, `work.accept`, `work.reject`, `question.answer`, `task.retry`, `task.stop` (live agent with the fake sleeping) and `task.discard`.
  - Assert folder, sidecar effects and the `## Log` line for each (the log line carries the event name).
- **Coverage test.** The test obtains the table through `symphony transitions` (JSON or Markdown) and asserts that every `(src, event, guard)` is in the parametrized list. It fails if a row is added without a test.
- **SPEC drift test.** The SPEC region equals the output of `symphony transitions`.
- **Illegal moves:** `work-todo -> done` by hand, `plan-todo -> work-todo` after a rejection, `done -> work-todo`, and `work-running -> work-review` (a live agent keeps running and the file is moved back). Each asserts the file is back, the `## Log` has the "illegal move" line and the sidecar `state` is unchanged. Also: a `work-running -> work-todo` hand move stops the agent and the task is observed as `task.stop`.
- **Dependencies:**
  - Waits while the dependency is in any non-`done` folder (parametrize over several folders) and runs once it is in `done` (move it by hand while Symphony is running, via `popen`).
  - Several dependencies (all must be done).
  - Unknown id stays waiting, with a warning in `symphony.log`.
  - A discarded dependency sends the dependent to `stuck` with `blocked_cause = dependency_discarded`.
  - A two-task cycle sends both to `stuck` with `blocked_cause = dependency_cycle`; also a self-dependency.
  - `symphony status` shows `waiting on a, b`.
  - Dependencies gate planning: a `plan-todo` task with an unmet dependency does not call the planner.
  - A `depends_on` entry already `done` at creation lets the task run immediately.
  - The dependent's worktree is branched from the base branch after the dependency's merge. Only the `done` gate needs checking here.

### Risks

- **Race between `fire` and `observe`.** Both run on the event loop and `fire` is synchronous (rename plus sidecar save, no `await`), so `observe()` can't see a half-done move. Keep `fire` free of `await`.
- **A human editing a running task out of its folder** while `observe()` reverses an illegal move: write discipline (SPEC §3.3) allows writing to the file only when no agent runs. The `## Log` line for an illegal move on a `-running` task is written while an agent may be running, which breaks §3.3. Mitigation: append the reversal line after the worker ends, or buffer it (store a pending note in memory and write it when the worker finishes), or write it only to `symphony.log` for running tasks. Settle and spec this. Plan: buffer in `Running`, flush in `work()`'s `finally` path.
- **Existing sidecars have no `state`.** First sight records the current folder and fires nothing, so there is no false illegal move at upgrade. A sidecar written by a pre-change run whose task was moved by hand before the upgrade is not detected. That is acceptable for one user.
- **Races in shared dir:** a sidecar `state` that is stale because a task was moved by hand while Symphony was off. On startup Symphony runs `observe()` for the first tick, so offline hand moves are interpreted too, with the same row lookup. This is intended. Make sure the recovery step (`*-running -> *-todo`) runs before `observe()` so recovery is not seen as an illegal move.
- **`task.stop` vs recovery:** both are the same `*-running -> *-todo` edge, but with different actors. The table should keep `recover` (symphony) and `task.stop` (human) as separate rows. `observe()` only matches `actor == human` rows.
- **Cycle detection across `done` tasks.** Only walk edges through tasks that are not `done`. A cycle that includes a `done` task cannot exist in practice.
- **Idle exit with dependency-held tasks** can hang forever if a dependency is waiting on a human; spec and test it as above.
- **Existing tests** that move files by hand through now-illegal pairs need updating. Review them one by one rather than loosening the table.
- The model-ID or CLI constraints from the docs do not matter here: Symphony still drives the same `claude` argv.

### How to verify

- `uv run pyright` reports 0 errors.
- `uv run pytest -q` passes (about 25 seconds today, expect a little more).
- `grep -rn "\.move(" src/symphony` shows no caller outside `transitions.py`.
- `grep -n "plan_session_id and not" src/symphony/orchestrator.py` finds nothing, and `last_outcome` is not read anywhere to decide a destination.
- The coverage test fails when a dummy row is temporarily added to `TRANSITIONS`, and the SPEC drift test fails when the SPEC region is edited.
- Manually: create two tasks with `depends_on`, run `symphony status` and see `waiting on <id>`, move the dependency to `done` by hand and see the dependent dispatch.

### Suggested subtasks

If the change is too large for one session, split it in this order: (1) table, `fire`, orchestrator moves, SPEC §4.1 generated table, per-row and coverage tests; (2) observed hand moves and illegal-move reversal; (3) dependencies. Each part keeps pyright and pytest green.

## Feedback

- Approved, with one correction: table rows must only change Symphony's own state (folder,
  sidecar, Log). Effects outside Symphony (git merge for `work.accept`, appending answer text
  for `question.answer`) are NOT row effects: the future commands perform them and then fire the
  event. An observed hand move only fires the event, so dragging work-review -> done never merges.
  State this in the SPEC.
- Answers: 1) yes, public `symphony transitions`; 2) yes, defer the Log line; 3) yes, treat
  dependency-held-only as idle.

### Round 2

- When the sidecar has no `last_stage` (tasks from before the migration, or put into `stuck` or
  `question` by hand), the `task.retry` and `question.answer` rows must accept either `-todo`
  target: the folder the human chose decides the stage, and `last_stage` is then set from it.
  Today such a task can only leave `stuck` or `question` for `discarded`; every other move is
  reversed as illegal.
- Add black-box tests for both rows with `last_stage` missing (to `plan-todo` and to `work-todo`),
  and update SPEC and the generated table accordingly.

## Questions
Not blocking, but worth confirming:

1. Should `symphony transitions` be a public CLI subcommand (my default, so the SPEC drift test and the Rust rewrite can reuse it), or should the drift check be internal only?
   Yes
2. An illegal move on a `-running` task: I plan to move the file back and defer the `## Log` line until the worker ends (SPEC §3.3 write discipline). Is that acceptable?
   Yes
3. `--exit-when-idle` with a task held only by dependencies and nothing running: I plan to treat that as idle so runs don't hang. Is that right?
   Yes

## Log
- 2026-11-07 00:28 symphony: planned, moved to plan-review (turns 1, $0.31): Plan for a declarative transition table in a new `transitions.py`, with a single `fire()` path used by the orchestrator, observed hand moves with illegal-move reversal, and `depends_on` guards on the dispatch rows. Tests are written first, and the SPEC table is checked against the code.
- Implementation notes (SPEC details settled, all in SPEC §4.1, §5, §11, §15):
  - Legal hand moves out of `*-running`: the matching todo folder (`task.stop`) and `discarded` (`task.discard`). Every other target is illegal: the file is moved back before reconcile, so the agent keeps running. This changed two existing tests (`running -> done` became `running -> discarded`).
  - Log lines for events observed on a task with a live agent are held in memory (`pending_notes`) and appended in the worker-done callback (SPEC §3.3).
  - A deleted task file has no row: treated like `done`, as before.
  - `--exit-when-idle` ignores todo tasks held only by dependencies (SPEC §11, §15). A test that moves a dependency to `done` live uses `run` without the flag.
  - Guards are real: `deps_met` and `plan_required` are evaluated by `Machine` through a callback from the orchestrator, and `last_stage=...` from the sidecar. `give_up` gained the `attempts+=1` effect so `_fail` no longer mutates the sidecar. `dependency_*` rows set `last_stage` from their source so a later `task.retry` can pick the right todo folder.
  - `symphony transitions` takes `--repo` (ignored) so the black-box harness can call it like other commands. The SPEC drift test compares whitespace-normalized lines.
  - New `src/symphony/deps.py` holds `depends_on` evaluation (waiting, unknown, discarded, cycle). `TaskStore.move` is only called from `Machine.fire` and the illegal-move reversal in `Orchestrator.observe`.
  - Verified: `uv run pyright` 0 errors, `uv run pytest -q` 143 passed.
- Round 2: added guard `last_stage=unset` rows for `question.answer` and `task.retry` (either todo folder accepted, the chosen folder sets `last_stage`); `last_stage=plan|work` now match exactly (the old "missing means work" fallback is gone). SPEC §4.1 text and table updated. Tests: four new human-row cases (both rows, both targets, `last_stage` missing); the test table keys now include the destination. pyright 0 errors, pytest 147 passed.
- 2026-11-07 00:43 symphony: permission denied: Bash (python3 - <<'EOF'
import re
p='src/symphony/tasks.py'
s=open(p).read()
s=s.replace('CAUSE_GAVE_UP = "gave_up"\n','CAUSE_)
- 2026-11-07 00:43 symphony: permission denied: Bash (uv run python -m symphony transitions)
- 2026-11-07 00:44 symphony: validation passed, moved to work-review (turns 2, $2.28): Every task move now goes through one `fire()` path over a declarative table in `transitions.py`. The table has 37 rows, `symphony transitions` prints it, and SPEC §4.1 embeds it with a test that fails on drift. Hand moves are observed per tick: a human row fires the event, and any other move is moved back and logged as illegal. `depends_on` gates dispatch, with waiting, unknown-id, discarded and cycle handling plus `waiting on` in `status`. `uv run pyright` reports 0 errors and `uv run pytest -q` passes (143 tests). The work is committed on the branch. I ran pyright and pytest myself, but not the combined `uv run pyright && uv run pytest -q` command the system will run.
- 2026-11-07 01:09 symphony: validation passed, moved to work-review (turns 3, $4.64): When a task has no `last_stage`, `question.answer` and `task.retry` now accept either `-todo` folder, and the folder chosen sets `last_stage`. A set `last_stage` still allows only its own stage's todo folder. SPEC §4.1 and the generated table are updated. I added black-box tests for both rows with `last_stage` missing, to both `plan-todo` and `work-todo`. `uv run pyright` reports 0 errors and `uv run pytest -q` passes (147 tests). I ran them as separate commands, not the combined one, and committed the work.
