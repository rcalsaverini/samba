---
priority: 3
depends_on: ["make-every-command-one-use-case-with-plain-inputs-and-unifor"]
---
# Name the commands, shape Commands and make the CLI parse, call and render (ADR 0013, part 2)

Read CLAUDE.md, docs/spec/architecture.md, docs/spec/cli.md and ADRs 0011 to 0015 first. Behavior does not change: the black-box suite, tests/scenarios and every other test stay green, and pyright stays at 0 errors. Plan steps may use only commands in the WORKFLOW.md allow list: no git mv, no sed -i, no mkdir, no pipes or redirects, no uv sync. If the work is too big for one run at the per-task cost cap, propose chained subtasks in the plan.

Part 2 of ADR 0013. Part 1 (the previous task) made the result set closed (Done, Table, Text, Written, Refused) and moved id and prefix resolution inside the use cases, which now take plain strings. This task finishes it. (1) Add app/task_commands.py with one thin use case per command, named for what the person does, over ChangeState: AcceptPlan, RejectPlan, RejectWork (a fresh flag picks work.reject or work.reject_fresh), RetryTask (hints on), StopTask and DiscardTask (confirmation text and yes). The event strings, labels and FeedbackMode move out of cli.py into them. (2) bootstrap returns one Commands object that exposes only use cases (the ones above plus ListTasks, ShowTask, ListQuestions, ShowQuestion, AnswerQuestion, AcceptWork, CreateTask); today's Services is renamed. The orchestrator is not a use case: it comes from a separate bootstrap function used only by samba run, so the Commands object stays the contract that a web page or MCP server could use. Rename AdrServices to AdrCommands. (3) Rewrite entrypoints/cli.py to parse, one call, render: each leaf parser binds one call that passes plain values to exactly one use case (no if/elif chain on command names), and one shared render(result) function maps Done, Table, Text, Written and Refused to output and the exit code (0, 1 for refused, 2 for usage). Delete the cmd_transition, cmd_question_answer, cmd_work_accept, cmd_task_new and _show helpers. run, explore and dev transitions keep their own small paths. Keep the argparse help text unchanged. (4) Extend tests/test_architecture.py: entrypoints/cli.py imports neither samba.app.resolve nor samba.domain.task_id, and app/ modules never import argparse. (5) Update the architecture and cli spec chapters and the CLAUDE.md map: build returns Commands, every command is one use case with plain values and the closed result set, the CLI is parse, call and render, the Terminal port stays the way a use case asks for a confirmation or text (a non-interactive caller passes yes or the text up front), run and explore are outside the contract, and no entry point calls another.

## Plan
### Approach

Behavior does not change, so the black-box suite (tests/test_blackbox.py, test_manual.py, scenarios) is the safety net. The only new tests are architecture guards, written first. Implement in this order: guard tests (red), `app/task_commands.py`, `bootstrap.py`, `entrypoints/cli.py`, docs. Everything fits in one run (about 6 source files, 4 docs), so no chained subtasks are needed.

Design decisions:

- **task_commands.py.** Each class holds a `ChangeState` and has a typed `run(id: str, ...)` that calls `self.change_state.run(id, EVENT, LABEL, ...)`. The event strings, labels and `FeedbackMode` choices live as class constants or inline in these classes, not in cli.py.
  - `AcceptPlan.run(id)`: event and label `plan.accept`, feedback mode none.
  - `RejectPlan.run(id, feedback, edit)`: `plan.reject`, feedback mode optional.
  - `RejectWork.run(id, feedback, edit, fresh)`: event is `work.reject_fresh` if `fresh` else `work.reject`; the label is always `work.reject`; feedback mode optional.
  - `RetryTask.run(id)`: `task.retry`, `hints=True`.
  - `StopTask.run(id)`: `task.stop`.
  - `DiscardTask.run(id, yes)`: `task.discard`, `confirm_plan="Discard task {id}"`, passes `yes`.
  - All return `Done | Refused`.
  - They stay in `app/` (no asyncio, pathlib or adapter imports). Add `app/task_commands.py` to `APP_MODULES` in tests/test_architecture.py (`test_every_domain_and_app_module_is_listed` fails otherwise).
  - Keep `FeedbackMode` defined in change_state.py (the `ChangeState` signature uses it); the CLI no longer imports it.
- **Commands (bootstrap.py).**
  - Frozen dataclass `Commands` with only use cases: `accept_plan, reject_plan, reject_work, retry_task, stop_task, discard_task, list_tasks, show_task, list_questions, show_question, answer_question, accept_work, create_task`.
  - It holds no `config`, `tasks`, `change_state` or `orchestrator`.
  - `build(repo) -> Commands` calls a private shared helper that builds the parts (config, locations, tasks, machine, terminal, lock, clock, vcs, validator).
  - New `build_orchestrator(repo) -> Orchestrator`, used only by `samba run`. It builds the same parts with `LogJournal` and the agent runner. Share the wiring through a small private `_Parts` dataclass or helper so nothing is duplicated.
  - `build` has no `for_run` flag any more, so the journal is always `NullJournal` there; `build_orchestrator` uses `LogJournal`.
  - The orchestrator must still get the same `tasks`, `vcs`, `validator`, `lock` and `journal` it gets today.
  - Rename `AdrServices` to `AdrCommands`. Update the module docstring.
  - The `ConfigError` path is the same: both build functions raise it, and cli.py maps it to exit 2.
- **cli.py: parse, one call, render.**
  - Each leaf parser binds one call with `p.set_defaults(call=...)`, for example `lambda c, a: c.accept_plan.run(a.id)`. Passing only plain values (str, bool, int, list[str], None) to exactly one use case.
  - `AcceptWork` is async: its binding wraps `asyncio.run(c.accept_work.run(...))`.
  - Also bind `needs` (`"commands"` or `"adr"`) so `main` builds `build_adr` for ADR leaves and `build` for the rest. No if/elif on command names.
  - Parser-building code stays as is, so help text is unchanged. Keep the `--repo` loop. The `question answer` text-and-`--edit` conflict check can remain a parser-level `p_qans.error` (exit 2, same as today).
  - One shared `render(result: Result) -> int`:
    - `Done`: location on stdout, notes on stderr, return 0.
    - `Table`: `print_table(rows, shutil.get_terminal_size().columns, flex=...)`, return 0.
    - `Text`: `sys.stdout.write`, return 0.
    - `Written`: one file per line on stdout, return 0.
    - `Refused`: messages on stderr, return 2 if usage else 1.
  - `run`, `explore` and `dev transitions` keep small separate paths:
    - `run` calls `build_orchestrator` and keeps the existing `cmd_run` signal and asyncio code, now taking an `Orchestrator`.
    - `explore` keeps `cmd_explore` (the `Explored` exit code and `Refused` via render or `_report`).
    - `dev transitions` prints the table.
  - These three are dispatched before the generic call path, by the `needs` marker (`"run"`, `"explore"`, `"dev"`), not by command-name chains.
  - Delete `cmd_transition`, `cmd_question_answer`, `cmd_work_accept`, `cmd_task_new`, `_show`, `_done`, `_report`, and `cmd_adr`.
  - cli.py must not import `samba.app.resolve`, `samba.domain.task_id`, or `samba.app.change_state`. `Machine`, `human_events` and the like must stay absent (an existing test checks this).
  - No entry point calls another: cli.py does not import `entrypoints.orchestrator` directly; the Orchestrator type arrives via `bootstrap`.

### Steps

- [ ] Read CLAUDE.md, docs/spec/architecture.md, docs/spec/cli.md, `uv run samba adr show 13` (and 11, 12, 14, 15), and the current cli.py, bootstrap.py, change_state.py.
- [ ] Extend tests/test_architecture.py first: (a) `entrypoints/cli.py` imports neither `samba.app.resolve` nor `samba.domain.task_id`; (b) no `app/` module imports `argparse`; (c) add `app/task_commands.py` to `APP_MODULES`. Add tmp_path-based "catches it" tests like the neighbouring ones for (a) and (b), plus a check that cli.py does not import another entry point (`samba.entrypoints.orchestrator` or `samba.entrypoints.workers`); it may import its own helper `samba.entrypoints.table` (and `render` if it is split out). Run `uv run pytest -q tests/test_architecture.py` and confirm the module-listing test is red until task_commands.py exists.
- [ ] Create src/samba/app/task_commands.py with `AcceptPlan`, `RejectPlan`, `RejectWork`, `RetryTask`, `StopTask`, `DiscardTask` as described.
- [ ] Add direct unit tests in tests/test_app_use_cases.py (it already builds `ChangeState` over the fakes): `RejectWork(fresh=True)` fires `work.reject_fresh`, `RejectWork` otherwise fires `work.reject`, `RetryTask` returns the budget hint note, `DiscardTask` with `yes=False` and no tty is declined, and `AcceptPlan` moves a plan-review task. Mirror the existing ChangeState tests; no `samba` import in the black-box files.
- [ ] Rewrite bootstrap.py: `Commands`, `build`, `build_orchestrator`, `AdrCommands`, `build_adr`, `build_explore` (unchanged).
- [ ] Rewrite entrypoints/cli.py as described. Keep the help strings character for character. Check the parser section against `git diff` to confirm no help string changed.
- [ ] Run `uv run pyright` (0 errors) and `uv run pytest -q`. Fix any drift. `tests/test_manual.py` compares `--help` output with docs/manual.md; docs/manual.md needs no change unless a command name changed, which it does not.
- [ ] Update docs: docs/spec/architecture.md, docs/spec/cli.md and CLAUDE.md (see Spec changes). Check no em-dashes were added.
- [ ] Append a line to the task file's `## Log` summarizing the spec changes.
- [ ] If ADR 0013 still says "today's `Services`" in a way that now reads wrong, leave accepted ADR text alone. Propose no new ADR unless a real alternative was chosen (the only candidate, `build_orchestrator` as separate function, is already dictated by the task).
- [ ] Commit with a message without any attribution trailer.

### Files to change

- `src/samba/app/task_commands.py` (new)
- `src/samba/bootstrap.py`
- `src/samba/entrypoints/cli.py`
- `tests/test_architecture.py`
- `tests/test_app_use_cases.py` (new unit tests for the named use cases)
- `docs/spec/architecture.md`, `docs/spec/cli.md`, `CLAUDE.md`
- The task file `## Log`

No test imports `Services` or any `cmd_*` helper today (grep confirmed), so nothing else breaks.

### Spec changes

- `docs/spec/architecture.md`, dependency rule section: `build(repo)` returns `Commands`, which exposes only use cases (the six named state-changing ones, the four queries, `AnswerQuestion`, `AcceptWork`, `CreateTask`); `build_orchestrator(repo)` is a separate function used only by `samba run`; `AdrServices` becomes `AdrCommands`. Replace the "ADR 0013 lands in two steps ... follow in the next step" paragraph with the finished state.
- `docs/spec/architecture.md`: the CLI is parse, one call, render. Each leaf parser binds one call that passes plain values to one use case, and one `render(result)` maps `Done`, `Table`, `Text`, `Written` and `Refused` to output and the exit code (0, 1, 2). The `Terminal` port stays how a use case asks for a confirmation or text; a non-interactive caller (web page, MCP server) passes `yes` or the text up front. `run`, `explore` and `dev transitions` are outside the contract. No entry point calls another. Update the Entry points row in the Layers table if its wording mentions the old shape.
- `docs/spec/cli.md`, command pattern section (lines about 64-80): name the use cases (`AcceptPlan`, `RejectPlan`, `RejectWork`, `RetryTask`, `StopTask`, `DiscardTask` over `ChangeState`, plus `AnswerQuestion`, `AcceptWork`, `CreateTask`), and remove the "two steps" sentence.
- `CLAUDE.md` map: `build` returns `Commands`; the `entrypoints/cli.py` bullet (parse, call, render, no `cmd_*` helpers); add `app/task_commands.py` to the app list; mention `build_orchestrator` and `AdrCommands`; fix the `bootstrap.build(repo, for_run=True)` mention in the `log_journal.py` bullet to `build_orchestrator`.

### Risks

- **Journal for `samba run`.** Today `for_run=True` builds `LogJournal`. The new `build_orchestrator` must too, and `build` must stay journal-less. A lost `LogJournal` would silently drop samba.log; check `tests/test_blackbox.py` run tests, which cover log output.
- **Startup errors.** `StartupError` handling in `cmd_run` and `ConfigError` (exit 2) must keep the same codes. `build_orchestrator` raises `ConfigError`, which main maps to 2.
- **Parser help.** Any restructuring of parser code can change help text; `tests/test_manual.py` and blackbox help checks catch this. Edit only the binding lines.
- **Argparse and `set_defaults`.** Subparser defaults can be overwritten by a later `set_defaults`; bind on the leaf parsers only. The `args.call` attribute must not collide with option dests (`--feedback` etc.).
- **`work accept` async.** `asyncio.run` must stay in cli.py (app modules may not import asyncio).
- **pyright strict.** Typed lambdas over `argparse.Namespace` attribute reads need `cast` or `str(...)`/`bool(...)` wrapping, as the current code does. Avoid `Any` leaking.
- **Architecture test names.** The existing `test_the_cli_adapter_holds_no_rule` forbids the words `Machine`, `merge.` and `subprocess` in cli.py code; keep comments and identifiers clear of them.
- **Allow-list.** The agent must use only allow-listed commands (git grep rather than grep; no redirects, pipes, `git mv`, `mkdir` or `sed -i`). Use the Write and Edit tools for file changes.

### How to verify

- `uv run pyright` reports 0 errors.
- `uv run pytest -q` is fully green, in particular tests/test_blackbox.py, tests/test_manual.py, tests/test_scenarios.py, tests/test_architecture.py and the new unit tests.
- `git grep -n "cmd_transition\|cmd_question_answer\|cmd_work_accept\|cmd_task_new\|_show(\|Services" src tests` finds no stale references (only `AdrCommands` and `Commands`).
- `git grep -n "samba.app.resolve\|samba.domain.task_id\|FeedbackMode" src/samba/entrypoints/cli.py` finds nothing.
- `uv run samba --help` and `uv run samba task --help` are identical to the output before the change (compare against `git stash`-free means: run on main in the original checkout, or rely on test_manual).

### Suggested subtasks

None needed. If the cost cap is hit, split after the bootstrap step: (1) task_commands.py, `Commands`, `build_orchestrator` and the tests, with a temporary adapter in cli.py; (2) the cli.py rewrite, architecture guards and docs.

## Assumptions
- Accepted ADR text (ADR 0013 mentioning `Services`) is left unedited; the spec chapters carry the new state.
- `FeedbackMode` stays defined in app/change_state.py; only cli.py stops importing it.
- `build_orchestrator` replaces the `for_run` flag on `build`, so `build` always uses `NullJournal`.
- `AcceptWork` stays async and is exposed as is; the CLI binding wraps it with `asyncio.run`.
- ADR commands keep going through `build_adr` returning `AdrCommands`, selected by a marker on the leaf parser, and are rendered by the same `render` function.
- No new ADR is needed because the design follows ADR 0013 as written.

## Log
- 2026-11-11 15:53 samba: dispatch_plan: plan-todo -> plan-running
- 2026-11-11 15:54 samba: planned: plan-running -> plan-review: planned (turns 1, $0.25): Add app/task_commands.py (six thin use cases over ChangeState), have bootstrap return a use-case-only Commands object plus a separate orchestrator builder, and rewrite cli.py as parse, one bound call, one shared render. Tests, spec and CLAUDE.md are updated in the same change; it should fit in one run.
- 2026-11-11 15:54 samba: plan.accept: plan-review -> work-todo
- 2026-11-11 15:54 samba: dispatch_work: work-todo -> work-running
- work: all plan steps done. Added app/task_commands.py (six use cases), Commands/build_orchestrator/AdrCommands in bootstrap, cli.py as bind + render (handler per leaf via set_defaults; ConfigError mapped once in main; `validate` default keeps the question answer conflict check). Architecture guards and unit tests added. Full suite passed (712) and pyright 0 errors.
- Spec changes: architecture.md (Entry points row, dependency rule: Commands, build_orchestrator, AdrCommands, parse/call/render, no entry point calls another; Terminal note; Journal row uses build_orchestrator), cli.md (named use cases, removed the "two steps" text), CLAUDE.md map. No ADR proposed: design follows ADR 0013.
- 2026-11-11 16:03 samba: permission denied: Bash (uv run python - <<'EOF'
print(1)
EOF)
- 2026-11-11 16:06 samba: done: work-running -> work-review: validation passed (turns 2, $0.91): Added app/task_commands.py with six named use cases. bootstrap now returns a use-case-only `Commands`, plus a separate `build_orchestrator` for `samba run` and `AdrCommands`. cli.py is now parse, one bound call per leaf parser, and one shared `render`. I added architecture guards and unit tests, and updated the architecture and cli spec chapters and CLAUDE.md. pyright reports 0 errors, 712 tests pass, and the work is committed. No ADR proposed.
- 2026-11-11 16:10 samba: work.accept: work-review -> done: merged dbedc30, validated
