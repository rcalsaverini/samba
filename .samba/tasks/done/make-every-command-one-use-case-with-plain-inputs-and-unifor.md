---
priority: 3
depends_on: ["extract-the-workers-and-thin-the-orchestrator-loop-adr-0015"]
---
# Make every command one use case with plain inputs and uniform results (ADR 0013)

Read CLAUDE.md, docs/spec/architecture.md and ADRs 0011 to 0015 first. Behavior does not change: the black-box suite and every other test stay green, and pyright stays at 0 errors. Update the architecture chapter, the orchestrator and cli spec chapters where they change, and the CLAUDE.md map in the same change. Plan steps may use only commands in the WORKFLOW.md allow list: no git mv, no sed -i, no mkdir, no pipes or redirects. Move a file by writing it at its new path and git rm of the old one, then fix imports with Edit (git grep finds them). If the work is too big for one run at the per-task cost cap, propose chained subtasks in the plan.

Implement ADR 0013. entrypoints/cli.py resolves task ids in three places (cmd_transition, cmd_question_answer, cmd_work_accept), repeats the printing of a result (location, notes, refusal), and picks the use case with string comparisons. Move id and prefix resolution inside the use cases, so every command is one use case taking plain values (strings, numbers, booleans, never an argparse object) and returning one of a closed set of results: done (location and notes), table, text, written files, or a refusal with a kind. Make bootstrap return one object that exposes the use cases (today's Services, renamed if the plan finds a better name). Keep the Terminal port as the way a use case asks the person for a confirmation or a text, and a non-interactive caller passes yes or the text up front. The CLI becomes parse, one call, render, with one shared function that renders a result and returns the exit code. run and explore stay as they are. Add use case tests for the id-resolution cases (unique prefix, ambiguous, unknown) that were only reachable through the command line, and update the cli and architecture spec chapters.

## Plan
### Approach

This change lands in two steps (ADR 0013). **This task is step 1 only**:

- the closed result set;
- id and prefix resolution inside the use cases;
- the use case tests for it;
- the thinnest CLI change that keeps `samba` working.

**Step 2** is a separate next task: the named use cases (`app/task_commands.py`), the `Commands` object and the `AdrCommands` rename, the CLI rewrite to parse, one call, render, the architecture guard on `entrypoints/cli.py` and `app/`, and the final cli and architecture spec text. Do not do any of step 2 here.

Behavior does not change: the same `Refused` values and messages, the same exit codes, the same stdout and stderr. The black-box suite, `test_manual.py` and pyright stay green.

1. **Closed result set** in `app/results.py`: add `Done(location: str | None, notes: tuple[str, ...] = ())` and `Result = Done | Table | Text | Written | Refused`. Remove `StateChanged` (`change_state.py`), `Answered` (`answer_question.py`), `Accepted` and `DryRun` (`accept_work.py`) and `Created` (`create_task.py`). `Explored` stays, since `explore` is out of scope.
   - `DryRun` becomes `Text("\n".join(lines) + "\n")`.
   - `CreateTask` returns `Done(location)`.
2. **`find_task(tasks: Tasks, text: str) -> TaskId | Refused`** in `app/resolve.py`. It calls `resolve_task_id` and turns `ResolveError` into `usage(e.render())`. Keep `resolve_task_id`, `ResolveError`, `resolve_deps` and `resolve_states` as they are (`CreateTask` and `ListTasks` still use them).
3. **Plain-string use cases that resolve inside.**
   - `ChangeState.run(id: str, event, label, ...)`: `find_task` first, then the existing legality check, feedback and edit, confirmation, lock, re-check and fire. Do not reorder.
   - `AnswerQuestion.run(target: str, text, edit)`: `split_target(target)` (move or import it from `app/queries.py`; avoid a circular import), then `find_task`, then the existing `_check`.
   - `AcceptWork.run(id: str, ...)`: still `async`, `find_task` first. `app/` still imports no asyncio.
   - `ShowTask.run` and `ShowQuestion.run`: switch the `try/except ResolveError` to `find_task`.
   - `CreateTask`: only the result change.
4. **Thinnest CLI change** in `entrypoints/cli.py`.
   - Delete the `resolve_task_id` calls and the `ResolveError` import.
   - `cmd_transition`, `cmd_question_answer` and `cmd_work_accept` pass the typed string straight to the use case. The `split_target` call in the CLI goes away.
   - Replace the `Accepted` and `DryRun` branches with the new results. `_show` already handles `Text`, so `cmd_work_accept` can send `Text` through it. `Done` is printed (location to stdout, notes to stderr) by a single small `_done` helper that replaces the three copies.
   - `cmd_task_new` prints `Done.location`.
   - Keep the argparse tree, `--help` text, `Services` and `bootstrap.py` unchanged.

### Steps

- [ ] Read `CLAUDE.md`, ADRs 0011, 0013 and 0015 (`uv run samba adr show N`), `docs/spec/architecture.md` and `docs/spec/cli.md`.
- [ ] **Tests first.**
  - New `tests/test_app_resolve.py`: `find_task` with an exact id, a unique prefix (returns the full id), an exact id that is also a prefix of another (exact wins), ambiguous (`Refused("usage", ("samba: ambiguous task id 'x'; candidates:\n  a1\n  a2",))`) and unknown (`("samba: unknown task 'zz'",)`).
  - `tests/test_app_use_cases.py`, per use case (`ChangeState`, `AnswerQuestion`) and in `tests/test_app_accept_create.py` for `AcceptWork`: a unique prefix reaches the task and changes it, ambiguous and unknown are `usage` with exact messages, and nothing changes on refusal. For `AnswerQuestion` also `prefix/qid` and a bare prefix. Add the same three cases for `ShowTask` and `ShowQuestion` in `tests/test_app_queries.py`.
  - Update the existing assertions to the new results: `StateChanged(...)` becomes `Done(...)`, `Answered` becomes `Done`, `Accepted` becomes `Done`, and the `DryRun` assertions become `Text(...)`. `CreateTask` returns `Done`.
  - Update `tests/test_scenarios.py` `play()` for the string-id signatures and `Done`.
- [ ] Edit `app/results.py`, then `app/resolve.py` (`find_task`), then `change_state.py`, `answer_question.py`, `accept_work.py`, `queries.py` and `create_task.py`. Use `git grep "StateChanged\|Answered\|Accepted\|Created\|DryRun"` to find every import.
- [ ] Edit `entrypoints/cli.py` (thinnest change, as above).
- [ ] Run `uv run pyright`, then `uv run pytest -q`, as separate plain commands. Fix until 0 errors and all green.
- [ ] Spec edits (below).
- [ ] Append to this task's `## Log` what changed in the spec.

### Files to change

- `src/samba/app/results.py`
- `src/samba/app/resolve.py`
- `src/samba/app/change_state.py`
- `src/samba/app/answer_question.py`
- `src/samba/app/accept_work.py`
- `src/samba/app/queries.py`
- `src/samba/app/create_task.py`
- `src/samba/entrypoints/cli.py`
- `tests/test_app_resolve.py` (new)
- `tests/test_app_use_cases.py`
- `tests/test_app_accept_create.py`
- `tests/test_app_queries.py`
- `tests/test_scenarios.py`
- `docs/spec/architecture.md`
- `docs/spec/cli.md`
- `CLAUDE.md`: only the lines naming `StateChanged`, `Answered`, `Accepted` or the CLI resolving ids. The full map update belongs to step 2.

Nothing moves or gets deleted; any new file is written at its path. Use only allow-listed commands: `git grep`, no `git mv`, no `sed -i`, no `mkdir`, no pipes or redirects.

### Spec changes

Only what this part changes: the results and where resolution happens. State in both chapters that ADR 0013 lands in two steps.

- `docs/spec/architecture.md`, the composition-root and entry-point paragraph (~lines 29 to 38):
  - Use cases take the id (or `TASK[/QID]`) as typed and resolve it themselves.
  - They return one of `Done`, `Table`, `Text`, `Written` or `Refused`.
  - The CLI no longer resolves ids.
  - Add a sentence: the change lands in two steps; named use cases, the `Commands` object and the parse, call, render CLI follow in the next step.
  - The sentence "`resolves the id`" in the cli description is removed.
- `docs/spec/cli.md`, the command-pattern section (~lines 64 to 76): the first step of the pattern is resolved inside the use cases; the result list gains `Done` and `dry-run` output is a `Text` result. Note the two-step landing.
- `docs/spec/orchestrator.md`: none, because the orchestrator is not touched.
- `docs/manual.md`: none, because no command or flag changes.

### Risks

- **Message or exit drift.** An unresolved id must still print `samba: <message>` and exit 2. Mitigation: the exact `Refused` values in the new tests, plus the unchanged black-box suite.
- **Order of checks.** Resolve, then legality, then confirmation (`confirm_plan`, before the lock), with `--edit` before the lock. Do not reorder.
- **Circular import** if `split_target` is imported from `queries.py` into `answer_question.py`. Move it to `app/resolve.py` if so, and re-export nothing.
- **Test churn** from the renamed results. Edit mechanically and re-run per module.
- **Allow-list.** Use `git grep` only.
- **Scope creep.** `task_commands.py`, `Commands`, the architecture guard and the CLI rewrite are explicitly not part of this task.

### How to verify

- `uv run pyright` reports 0 errors.
- `uv run pytest -q` is fully green, with `tests/test_blackbox.py` and `tests/test_manual.py` unchanged.
- The new tests pass: unique prefix, ambiguous and unknown on `ChangeState`, `AnswerQuestion`, `AcceptWork`, `ShowTask` and `ShowQuestion`, plus `tests/test_app_resolve.py`.
- `git grep "resolve_task_id\|ResolveError" src/samba/entrypoints` returns nothing.
- `git grep "StateChanged\|Answered\|Accepted\|DryRun" src tests docs CLAUDE.md` returns nothing, apart from historical ADR text.
- The spec diff and the `## Log` entry are present.

### Suggested subtasks

None for this task: it is part 1 of 2. The next task (created by the human) does step 2:

- `app/task_commands.py` (`AcceptPlan`, `RejectPlan`, `RejectWork`, `RetryTask`, `StopTask`, `DiscardTask`);
- `Services` to `Commands` and `AdrServices` to `AdrCommands`;
- the CLI rewrite to parse, one call, render, with one shared `render`;
- the architecture guard on `entrypoints/cli.py` and `app/`;
- the final cli and architecture spec text and the `CLAUDE.md` map.

## Assumptions
- `TaskId` is a `str` subtype or `NewType`, so existing in-process callers that pass a `TaskId` still type-check against `id: str`. If pyright disagrees, wrap with `str(...)` in the tests.
- `Done` replaces `StateChanged`, `Answered`, `Accepted` and `Created`, all with fields `(location, notes)`. `Created.task_id` is unused by the CLI, which prints only `location`. Check with `git grep "\.task_id"` before dropping it.
- `DryRun(lines)` becomes `Text("\n".join(lines) + "\n")`, which prints byte-identically to printing each line.
- An unknown or ambiguous id is `usage(e.render())`, which prints `samba: <message>` and exits 2, as today.
- `ChangeState.run` and `AcceptWork.run` take `id: str` as the first parameter and resolve it before the legality check, so the order is resolve, legality, confirm, lock. The "has no file" branch of `check_legal` stays for the re-check under the lock.
- `Services` keeps its name and shape in this part. No new ADR is needed.

## Feedback
### Round 1

The plan is correct and matches ADR 0013, but it is too big for one run at the $5 cap. Follow your own suggested subtasks and plan ONLY part 1 in this task: the closed result set (Done and the Result alias, removing StateChanged, Answered, Accepted, Created and DryRun, with DryRun becoming Text), find_task in app/resolve.py, and plain-string use cases that resolve the id themselves (ChangeState, AnswerQuestion, AcceptWork, ShowTask, ShowQuestion, CreateTask returning Done), with the use case tests for unique prefix, ambiguous and unknown on each, tests/test_app_resolve.py, and the mechanical test updates those signature and result changes force. Keep the existing CLI working through the thinnest possible change (it passes the typed id string to the use case and renders the new results; no new bootstrap shape yet, Services keeps its name). The named use cases (app/task_commands.py), the Commands object and the AdrCommands rename, the CLI rewrite to parse, one call and render, the architecture guard on entrypoints/cli.py and app/, and the final cli and architecture spec text become a separate next task that I will create; do not do them here. Update only the spec text that describes what this part changes (the results and where resolution happens), and say in the plan and the spec that the change lands in two steps. Keep everything else in your plan (behavior unchanged, exact Refused values and messages, ChangeState legality check before confirmation, AcceptWork stays async, allow-listed commands only).

## Log
- 2026-11-11 15:09 samba: dispatch_plan: plan-todo -> plan-running
- 2026-11-11 15:09 samba: recover: plan-running -> plan-todo: stopped by shutdown
- 2026-11-11 15:09 samba: dispatch_plan: plan-todo -> plan-running
- 2026-11-11 15:10 samba: planned: plan-running -> plan-review: planned (turns 3, $0.33): Move id resolution into the use cases, collapse the result types into one closed set (Done, Table, Text, Written, Refused), add named use cases for the state-changing commands, and have bootstrap return one `Commands` object. The CLI then becomes parse, one call, one shared `render`. I suggest two chained subtasks, but the work may fit in one run.
- 2026-11-11 15:11 samba: plan.reject: plan-review -> plan-todo: feedback round 1
- 2026-11-11 15:11 samba: dispatch_plan: plan-todo -> plan-running
- 2026-11-11 15:11 samba: planned: plan-running -> plan-review: planned (turns 4, $0.78): Revised to part 1 of 2 only: a closed result set (`Done`, `Table`, `Text`, `Written`, `Refused`) and plain-string use cases that resolve the id themselves, with their tests. The existing CLI only passes the typed string and renders `Done` and `Text`; the named use cases, the `Commands` object, the CLI rewrite and the architecture guard are left to a separate next task.
- 2026-11-11 15:11 samba: plan.accept: plan-review -> work-todo
- 2026-11-11 15:12 samba: dispatch_work: work-todo -> work-running
- Work, part 1 of 2 done as planned: `Done` and `Result` in `app/results.py`; `StateChanged`, `Answered`, `Accepted`, `Created` removed, `DryRun` became `Text`; `find_task` and `split_target` (moved from `queries.py`) in `app/resolve.py`; `ChangeState`, `AnswerQuestion`, `AcceptWork`, `ShowTask`, `ShowQuestion` resolve ids themselves; CLI passes the typed string and uses one `_done` helper. New `tests/test_app_resolve.py` and prefix/ambiguous/unknown tests per use case.
- Spec: `docs/spec/architecture.md` (results, resolution in use cases, two-step landing) and `docs/spec/cli.md` (command pattern, results, two-step landing); `CLAUDE.md` lines for `app/resolve.py` and `app/results.py`. orchestrator.md and manual.md: no change. No new ADR (ADR 0013 covers it).
- 2026-11-11 15:48 samba: done: work-running -> work-review: validation passed (turns 5, $1.70): Step 1 of ADR 0013 is committed. Use cases take plain strings and resolve task ids and prefixes themselves, and return the closed result set (`Done`, `Table`, `Text`, `Written`, `Refused`). The CLI just passes the typed string and renders. Pyright shows 0 errors and the full pytest run passed (exit 0). Spec chapters architecture and cli and CLAUDE.md were updated.
- 2026-11-11 15:53 samba: work.accept: work-review -> done: merged 370975b, validated
