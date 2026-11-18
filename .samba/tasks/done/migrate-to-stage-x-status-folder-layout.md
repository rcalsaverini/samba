---
priority: 1
---
# Migrate to stage x status folder layout

Phase 1, part 1 of `docs/command-ideas.md`. Replace today's seven state folders with the ten
stage x status folders recommended in section 3.3 (option B), and remove the state that only
existed to make up for the old layout.

Read first: `docs/command-ideas.md` sections 3.1 (current transitions), 3.3 (recommendation and
layout), 3.4 (transition table, for the names and the `last_stage` rule). SPEC sections 2, 4, 5,
10, 11 and 14.

Decisions already made by the human:

- Folders: `plan-todo`, `plan-running`, `plan-review`, `work-todo`, `work-running`, `work-review`,
  `question`, `stuck`, `done`, `discarded`. The folder name is the complete state.
- `question` and `stuck` stay stage-free; the sidecar keeps `last_stage` (`plan | work`), set at
  dispatch, so a retried or answered task knows where to go back.
- Sidecar: add `blocked_cause` (`question | budget | gave_up` for now; part 2 adds
  `dependency_discarded` and `dependency_cycle`, so do not hard-code it as a closed set in a way
  that makes adding values awkward) and `last_stage`; remove `phase`;
  stop using the `planned` and `approved` values of `last_outcome`. Old sidecars still load.
- `done` means accepted (merged); `discarded` means abandoned. Both remove the worktree, neither
  deletes the branch.
- The SPEC changes to match the new model. Rewrite the affected sections rather than patching
  around the old names.

Scope of this task:

- `State`, `STATES`, `TaskStore.ensure`, all folder literals in the orchestrator and CLI
  (`new`, `new --plan`, `status`), recovery, shutdown, reconcile, cleanup, retries, give up,
  budget, planning and approval flows, using the new folders.
- Approval (`plan-review` to `work-todo`, by hand move for now) still has to start execution in a
  fresh session with `plan_approved` set. Implement it without the `last_outcome == "planned"`
  inference if the plan finds a clean way; otherwise keep a minimal inference and leave a note for
  part 2 (the explicit transition table), which replaces all inference.
- Migration: at startup, if any old folder (`plan`, `todo`, `running`, `review`, `blocked`) still
  holds task files, refuse to start and print a short `mv` recipe. Do not migrate automatically.
- Tests: rename folder names in `tests/test_blackbox.py`, `tests/test_planning.py` and
  `tests/conftest.py`. Behavior assertions stay the same unless the new model changes the behavior
  on purpose (for example `blocked` splitting into `question` and `stuck`); say which ones changed
  and why in `## Log`. Add tests for: question versus stuck routing, `done` versus `discarded`,
  `last_stage` routing of a retried or answered task, the old-folder startup refusal.
- Update `CLAUDE.md` if it names folders.

Out of scope (part 2, separate task): the explicit transition table in code, checking hand moves
against it, moving illegal hand moves back, and any new commands.

Acceptance criteria:

- `uv run pyright` reports 0 errors and `uv run pytest -q` passes.
- No code or test refers to the old folder names except the migration check and its test.
- SPEC sections 2, 4.1, 4.2, 5, 10, 11 and 14 describe the new layout consistently.
- `## Log` lists every test whose expected behavior changed, with the reason.

## Plan
### Approach

The folder name becomes the full state. `phase` goes away (the running folder says plan or work). `last_stage` (`plan|work`, set at dispatch) tells `question` and `stuck` tasks where to go back. `blocked_cause` (`question|budget|gave_up`) says why a task is in `question` or `stuck`. Stay open-ended: type it as `str | None` in the sidecar, and name the values as constants in one place (e.g. `tasks.py`), so part 2 can add `dependency_discarded` and `dependency_cycle` without touching a closed Literal.

New layout: `plan-todo, plan-running, plan-review, work-todo, work-running, work-review, question, stuck, done, discarded`.

**Approval without `last_outcome == "planned"` inference (clean way found).** After the planner finishes, Symphony moves `plan-running` to `plan-review`. A task in `work-todo` whose sidecar has `plan_session_id` set and `plan_approved` false can only have come from `plan-review` by hand (a new or reworked task never planned has no `plan_session_id`; a rework after approval has `plan_approved` true already). So at dispatch from `work-todo`: if `plan_session_id` and not `plan_approved`, then set `plan_approved=True` and `session_id=None`. This is still inference, but it uses a durable fact (a plan exists, it was not yet approved) and not the removed `planned`/`approved` outcome values. Add a short comment: "part 2 replaces this with the `plan.accept` row of the transition table". One caveat: a task that was planned, rejected and moved to `plan-todo`, then someone moves it to `work-todo` is indistinguishable from approval. That is the same as today and is an acceptable hand move for now. Do not use `last_outcome` for this at all.

**`require_plan`**: in dispatch from `work-todo`, if `require_plan` and not `plan_approved` and not (`plan_session_id` present, which is the approval case above), route the task to the plan stage: claim as `plan-running` with `last_stage="plan"`. Keep this simple: it is one dispatch branch, as today. Part 2 turns it into the `route_to_plan` row.

**Attempts reset**: today it triggers on `last_outcome in (blocked, failed)`. Keep that rule (SPEC §5.4) but it now applies to tasks coming from `question` or `stuck` to the todo folders. Keep `last_outcome` values `blocked` and `failed` (the old `blocked` outcome still comes from the agent). Optionally also reset when `blocked_cause` is set, then clear `blocked_cause` at dispatch.

**Routing out of `question` and `stuck` by hand**: the human moves the file to `plan-todo` or `work-todo`. Since the task says `last_stage` decides where a retried or answered task goes back, and hand moves are by the human, there is nothing to route automatically in this task (the commands that read `last_stage` are part 2). So `last_stage` is stored and tested as a sidecar fact, plus used for recovery and retries. Test it as: after a work question the sidecar has `last_stage == "work"`; after a planner question `last_stage == "plan"`. Also use it in `_origin`: `plan-todo` if `last_stage == "plan"` else `work-todo`. Ask the human in `questions` if automatic routing is wanted in this task (default: no).

### Steps

- [x] Read SPEC §2, 4, 5, 10, 11, 14 and `docs/command-ideas.md` 3.3/3.4 once more; read `tests/test_blackbox.py`, `tests/test_planning.py`, `tests/fake_claude.py` in full (only grepped so far).
- [x] Write the failing black-box tests first (new file `tests/test_layout.py`, style of existing ones, no `symphony` import):
  - question vs stuck: agent `blocked` goes to `question` with `blocked_cause=question`; planner `blocked` goes to `question`, `last_stage=plan`; budget exceeded goes to `stuck` with `blocked_cause=budget`; give-up after `max_attempts` goes to `stuck` with `blocked_cause=gave_up`.
  - `done` vs `discarded`: move a `work-review` task to `done` and another to `discarded`; after a tick both worktrees are removed and both branches still exist.
  - `last_stage` routing: retry after failure returns a plan failure to `plan-todo` and a work failure to `work-todo`; shutdown and startup recovery do the same; sidecar `last_stage` set at dispatch.
  - old-folder refusal: put a file in each of `plan`, `todo`, `running`, `review`, `blocked`; `symphony run` exits non-zero, stderr names the folder and has an `mv` recipe, nothing was moved or started (no fake calls). Empty old folders do not block.
  - old sidecar loads: a sidecar with `phase`, `last_outcome: "planned"` (unknown fields ignored, no crash).
  - `symphony new` creates in `work-todo`, `new --plan` in `plan-todo`.
- [x] Rename folders in `tests/conftest.py` (`STATES`, `add_task` default `work-todo`), `tests/test_blackbox.py`, `tests/test_planning.py`. Replace the `phase` assertions (`test_planning.py:73`, `:189` where the sidecar `phase: plan` seed becomes `last_stage: plan` plus the task placed in `plan-todo`) and the `last_outcome == "planned"` assertion (line 37). Record each changed expectation for the Log.
- [x] `tasks.py`: new `State` and `STATES`; `Sidecar`: remove `phase`, add `last_stage: str | None`, `blocked_cause: str | None`; `load` already ignores unknown keys (old `phase` is dropped silently, verify). Add `LEGACY_STATES = ("plan","todo","running","review","blocked")` and a `TaskStore.legacy_nonempty()` helper that returns the old folders holding `*.md` files. Helper to give the running folder and todo folder for a stage (`running_of(stage)`, `todo_of(stage)`).
- [x] `orchestrator.py`: startup check first (before `ensure`; refuse with `StartupError` listing the folders and an `mv` recipe such as `mv .symphony/tasks/todo/*.md .symphony/tasks/work-todo/`; mapping: plan to plan-todo, todo to work-todo, running to the matching todo folder (recovery), review to work-review, blocked to question or stuck by hand). Note `plan-review` and `done` keep their names and are not legacy. Then update recovery (both running folders, via `last_stage`), `run` idle test (`work-todo` and `plan-todo`), `reconcile` (compare with the running folder the task was dispatched into; store per task in `Running` the folder it lives in), `cleanup_workspaces` (remove when state is None, `done` or `discarded`), `dispatch` (both todo folders, set `last_stage`, move to the right running folder, approval and `require_plan` rules above), `work`/`_work`/`_plan` selection by `last_stage` instead of `phase`, `_finish` and `_fail` and `_origin` (take the running folder from `last_stage`), `_finish` sets `blocked_cause`; question vs stuck routing: agent or planner `blocked` goes to `question`, budget and give-up go to `stuck`. Cancel handling: `reason == "moved"` removes the worktree when the new state is None, `done` or `discarded`. `_variables`: `task.path` must point to the current running folder, not literal `"running"`. Drop `side.phase` uses in logs (log `stage=` instead; keep the `dispatch` log line field `phase` renamed to `stage` only if no test greps it).
- [x] `cli.py`: `cmd_status` shows folder name as state (no `running (phase)`), retry note for both todo folders, and `blocked_cause` shown in the LAST column or in the state for `question` and `stuck`; `cmd_new` uses `work-todo`/`plan-todo`; help strings.
- [x] `prompts.py` and `claude.py`: only user-facing text that names folders (check `PROTOCOL`, `TASK_TEMPLATE`, e.g. "move to blocked"); `Outcome` literal stays (agent protocol unchanged).
- [x] SPEC: rewrite §2 (layout), §4.1 (states table, diagram), §4.2 (sidecar fields), §5.1 to 5.4, §10, §11, §14.2, 14.3, 14.6, 14.8, 14.10 against the new model; no patching of old names. Also fix stray mentions in §3, §13 (`todo/`), §6 and §7 as found by grep. State the approval rule and the note for part 2. Add the startup refusal to §5.1 and the `done`/`discarded` contract (worktree removed, branch kept). No em-dashes.
- [x] `CLAUDE.md`: check; it currently does not name state folders, so likely no change (confirm by grep). Update `docs/command-ideas.md` only if it states layout as pending (optional, one line).
- [x] Run `uv run pyright`, then `uv run pytest -q` as separate plain commands; fix until clean. Grep for the old folder names to confirm only the migration check and its test remain.
- [x] Fill `## Log` in the task file: every test whose expectation changed and why, and the SPEC details settled (approval rule, `blocked_cause` as open string, `last_stage` set at dispatch).

### Files to change

`src/symphony/tasks.py`, `orchestrator.py`, `cli.py`, possibly `prompts.py`; `SPEC.md`; `tests/conftest.py`, `tests/test_blackbox.py`, `tests/test_planning.py`, new `tests/test_layout.py` (or added to `test_blackbox.py`); `tests/fake_claude.py` unaffected; `CLAUDE.md` only if it names folders; `docs/command-ideas.md` optional.

### Risks

- Approval inference remains: a hand move `plan-todo` to `work-todo` after a plan exists but was never approved is read as approval. Documented, replaced in part 2.
- `reconcile` and the cancel path use the literal `"running"`; with two running folders, a task moving from `plan-running` to `work-running` by hand must count as "left" its dispatched folder. Track the dispatch folder in `Running`.
- Tests mixing `last_outcome` of `blocked` for stuck vs question: `blocked_cause` is the new discriminator; the `last_outcome` values stay to limit churn.
- `Sidecar(**...)` with `last_stage` or `blocked_cause` wrong types is not validated; keep the existing fallback.
- The startup refusal must run before `tasks.ensure()` and before recovery, and must only count `*.md` files, so empty old folders from earlier runs do not block.
- Tests with the sidecar seed `phase: plan` (planning tests) need `last_stage` instead, else recovery routes wrongly.
- Black-box tests must not import `symphony`; keep the fake claude standard-library only.

### How to verify

- `uv run pyright` reports 0 errors; `uv run pytest -q` passes (about 25 s).
- `grep -rnE "\b(todo|running|review|blocked)/|\"(plan|todo|running|review|blocked)\"" src tests SPEC.md` shows hits only in the migration check, its test, and prose that legitimately means the word (not a folder).
- Manually: create `.symphony/tasks/todo/x.md`, run `symphony run --exit-when-idle`, see refusal with `mv` recipe and no side effects.
- Task `## Log` lists changed test expectations.

### Suggested subtasks

None needed; the change is one mechanical but wide refactor and splitting it would leave the repo broken in between. If a split is wanted: (1) tests plus `tasks.py`/CLI, (2) orchestrator and SPEC.

## Questions
Should `last_stage` also drive automatic routing of hand moves out of `question` and `stuck` in this task? My plan assumes no: the human moves the file to `plan-todo` or `work-todo` themselves, and `last_stage` is used only for recovery, retries and as a stored fact for part 2's `question.answer` and `task.retry`.

## Log
- 2026-11-07 00:00 symphony: planned, moved to plan-review (turns 1, $0.24): Plan to replace the seven state folders with ten stage x status folders, drop `phase`, add `blocked_cause` and `last_stage` to the sidecar, and refuse to start when old folders hold files. Approval is detected by an explicit rule with no `last_outcome == "planned"` inference. Tests come first, SPEC is rewritten in the same change.
- 2026-11-07 implementation: all ten folders in place, pyright 0 errors, pytest 70 passed.
  - Decision on the open question: no automatic routing out of `question`/`stuck`. `last_stage` is stored at dispatch and used for retry, shutdown and `_origin`; recovery uses the running folder itself (`plan-running` to `plan-todo`, `work-running` to `work-todo`).
  - Approval: a `work-todo` task with `plan_session_id` set and `plan_approved` false is approval (sets `plan_approved`, clears `session_id`). No `last_outcome` use. Documented in SPEC §14.3 rule 2, including the plan-todo-to-work-todo caveat; part 2 replaces it with `plan.accept`.
  - `blocked_cause` is an open `str | None`; values are constants in `tasks.py` (`CAUSE_QUESTION`, `CAUSE_BUDGET`, `CAUSE_GAVE_UP`). It is cleared at dispatch, and its presence also resets `attempts`.
  - Old-folder refusal runs first in `startup()` (before git/auth checks and before `ensure`), counts only `*.md`, prints an `mv` recipe.
  - `tests/fake_claude.py`: `task_log` now writes into `*-running/<id>.md` (it hard-coded `running/`).
  - `status` shows `question (question)` or `stuck (budget)` in STATE; the dispatch log field `phase` is now `stage`.
  - Tests whose expected behavior changed (all else is a pure folder rename):
    - `test_blackbox.py::test_blocked_moves_to_blocked` renamed `test_blocked_moves_to_question`: agent `blocked` now lands in `question`, not `blocked`.
    - `test_is_error_result_counts_as_failure`, `test_gives_up_after_max_attempts_with_reflection_turn`, `test_max_turns_exhausted_is_a_failure`, `test_turn_timeout_kills_agent`, `test_after_create_hook_failure_fails_attempt`, `test_template_unknown_variable_fails_attempt`: final state `stuck` (gave up) instead of `blocked`.
    - `test_budget_cap_blocks_task`: ends in `stuck`, and now also asserts `blocked_cause == "budget"`.
    - `test_blocked_task_moved_back_to_todo_resets_attempts` renamed `test_stuck_task_moved_back_to_todo_resets_attempts`: starts from `stuck`.
    - `test_planning.py::test_approval_runs_execution_in_a_new_session`: `phase == "execute"` replaced by `last_stage == "work"` (`phase` no longer exists).
    - `test_plan_task_ends_in_plan_review_read_only`: unchanged, `last_outcome == "planned"` is still written (kept as a run log, not used for routing).
    - `test_planner_blocked_with_questions_then_replan`: planner `blocked` lands in `question` (was `blocked`), asserts `last_stage == "plan"`; the answer is moved to `plan-todo`.
    - `test_planner_gives_up_without_reflection`, `test_missing_plan_text_is_a_failure`: final state `stuck`.
    - `test_recovery_replans_a_running_planning_task`: seeded as a `plan-running` file with sidecar `last_stage: plan` instead of `running` plus `phase: plan`.
    - `test_moving_task_out_of_running_stops_the_planner`: watches `plan-running`.
  - New tests in `tests/test_layout.py`: question vs stuck routing and causes (both stages), answered question clears the cause, status shows the cause, `done` vs `discarded` (worktree removed, branch kept, and a running task moved to `discarded`), retry and shutdown return to the stage's own todo folder, startup recovery of both running folders, old-folder refusal for each of the five folders, empty old folders do not block, old sidecar with `phase` and `last_outcome: approved` still loads.
  - `CLAUDE.md` does not name state folders: no change. `docs/command-ideas.md` untouched.
- 2026-11-07 00:14 symphony: permission denied: Bash (python3 - <<'EOF'
import re
p='src/symphony/tasks.py'
s=open(p).read()
s=s.replace('''State = Literal["plan", "plan-revi)
- 2026-11-07 00:14 symphony: validation passed, moved to review (turns 2, $1.63): Replaced the seven state folders with the ten stage x status folders, dropped `phase`, added `last_stage` and `blocked_cause`, and made startup refuse old folders that still hold tasks, with an `mv` recipe. `uv run pyright` reports 0 errors and `uv run pytest -q` passes (70 tests); SPEC sections 2, 4, 5, 10, 11 and 14 are rewritten, and the commit is on the branch. The `## Log` lists each test whose expected behavior changed.
