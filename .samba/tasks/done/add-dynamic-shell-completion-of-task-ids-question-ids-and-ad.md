---
priority: 3
depends_on: ["build-the-command-line-on-typer-with-shell-completion-adr-00"]
---
# Add dynamic shell completion of task ids, question ids and ADR numbers (ADR 0014, part 2)

Read CLAUDE.md, docs/spec/architecture.md, docs/spec/cli.md and ADRs 0011 to 0015 first. Behavior of the commands does not change: the black-box suite and every other test stay green, and pyright stays at 0 errors. Plan steps may use only commands in the WORKFLOW.md allow list: no git mv, no sed -i, no mkdir, no pipes or redirects, and no uv command other than uv run pyright, uv run pytest and the listed uv run samba forms. If the work is too big for one run at the per-task cost cap, propose chained subtasks in the plan.

Part 2 of ADR 0014. Part 1 (the previous task) rewrote the command line on Typer with static completion (command names and options, and --install-completion / --show-completion). This task adds dynamic completion of ids: samba plan accept <TAB> offers the tasks that can be accepted. Add small read-only queries in app/ (a new app/completion.py or in app/queries.py) that return plain strings with a short help text: task ids filtered by the states the verb can act on (plan accept and reject: plan-review; work accept and reject: work-review; task retry: stuck; task stop: running; task show and discard: all), task/qid of open questions for question answer and show, and ADR numbers (adr accept and reject: proposed; adr supersede: accepted; adr show: all). Take the legal source states from the transition table in domain/transitions.py (find_row and human_row) instead of hard-coding states in the CLI. Expose the queries from bootstrap (a complete member of Commands and of AdrCommands). In entrypoints/cli.py add Typer autocompletion callbacks on the id arguments: they go through bootstrap and the queries only, never the filesystem, must print nothing, swallow every error (no repo, no WORKFLOW.md, broken config) and return no candidates, and resolve --repo from the context with a fallback to the current directory. Add tests: unit tests of the queries over the fakes (in the style of tests/test_app_*.py), and a black-box tests/test_completion.py that drives Click's environment-based completion from the sandbox (check the exact variable name and the prog name once, set the prog name explicitly in the app if needed): plan accept offers only plan-review tasks, work accept only work-review, question answer offers task/qid of open questions, adr accept offers only proposed ADRs, --repo is honored, and a missing repo or broken WORKFLOW.md gives no candidates, exit 0 and no traceback on stderr. Extend the architecture test so the queries stay in app/ without typer or click. Update the cli and architecture spec chapters, docs/manual.md (completion section) and the CLAUDE.md map so they say completion is dynamic.

## Plan
### Approach
Add `app/completion.py` with three small read-only queries that return `list[tuple[str, str]]` (value, short help). Each takes plain strings (command label and the incomplete word) and never prints.
- `CompleteTaskIds(tasks)`.
  - `run(command: str, incomplete: str)` maps the command label (`"plan accept"`, `"plan reject"`, `"work accept"`, `"work reject"`, `"task retry"`, `"task stop"`, `"task show"`, `"task discard"`) to a human event: `plan.accept`, `plan.reject`, `work.accept`, `work.reject`, `task.retry`, `task.stop`, `task.discard`. The label-to-event map lives in app, like the event strings in task_commands.py.
  - For `show` there is no event, so every state is offered. `discard` may use the `task.discard` rows, which cover the discardable states.
  - Legal states come from the table: `[s for s in STATES if find_row(event, s, lambda _g: True)]`. That gives plan-review for plan accept and reject, work-review for work accept and reject, stuck for task retry, and plan-running plus work-running for task stop. Nothing is hard-coded. Optionally add a tiny pure helper `human_sources(event)` in domain/transitions.py built on `find_row`, if that reads better.
  - Help text is the state, plus the title if short, for example `plan-review  Add X`.
  - Candidates are filtered with `startswith(incomplete)`. Use `tasks.list(state)` per legal state.
- `CompleteQuestions(tasks)`: `run(incomplete)` returns `task/qid` for each open question of tasks in the `question` state, using `open_questions`. Help is the question text on one line, truncated to about 60 characters.
- `CompleteAdrs(adrs)`: `run(command, incomplete)`. `accept` and `reject` offer proposed ADRs, `supersede` offers accepted ones, and `show` offers all. Values are `f"{n:04d}"` and help is the title. It uses `adrs.load_all()`.

Bootstrap:
- Add `complete_tasks: CompleteTaskIds` and `complete_questions: CompleteQuestions` to `Commands`.
- Add `complete: CompleteAdrs` to `AdrCommands`.
- Build them in `build` and `build_adr`. `AdrCommands` is positional, so update the call.

CLI (entrypoints/cli.py): add small helpers that never touch the filesystem directly.
- `def _repo(ctx) -> Path`: `ctx.params.get("repo")`, falling back to `Path.cwd()`.
- Callback factories `task_ids(command)`, `question_ids()` and `adr_numbers(command)`. Each returns `def cb(ctx: typer.Context, incomplete: str) -> list[tuple[str, str]]`. The body is `try: return build(_repo(ctx)).complete_tasks.run(command, incomplete) except Exception: return []`.
- The callbacks print nothing, and `build(...)` is the only route to data.
- Catch `Exception` broadly. `ConfigError` and `typer.Exit` are included, and `SystemExit` is not an `Exception`, so `typer.Exit` (a `RuntimeError` subclass) is handled by the broad catch.
- Use the `AdrCommands` route (`build_adr`) for ADR numbers, which needs no WORKFLOW.md.
- Attach the callbacks with `typer.Argument(..., autocompletion=cb)`. Replace the shared `Id` alias with a per-command annotated alias: `PlanId`, `WorkId`, `RetryId`, `StopId`, `AnyId` for show and discard, `QuestionTarget` for question show and answer, `AdrAny`, `AdrProposed` and `AdrAccepted`. Keep metavar and help text identical, so the help shape test and the manual drift test stay green.
- Keep the `app(args=argv, prog_name="samba")` call. The env var name is `_SAMBA_COMPLETE`, and test_cli_surface.py already uses it with `complete_bash`.
- Make sure nothing is written to stderr on failure. If Click prints anything, silence it in the callback; the broad try/except covers it.

### Steps
- [ ] Read CLAUDE.md, docs/spec/README.md, cli.md, architecture.md, and ADRs 0011-0015 (`uv run samba adr list`, `uv run samba adr show N`). Check the Typer `autocompletion` signature and the exact env var once: `_SAMBA_COMPLETE=complete_bash`, `COMP_WORDS`, `COMP_CWORD`.
- [ ] Black-box tests first: create tests/test_completion.py. It must not import samba. Reuse the `Sandbox` fixture (`add_task`, `write_sidecar`, `write_workflow`) and a `complete(*words)` helper like the one in test_cli_surface.py. It runs `bare(...)` with `_SAMBA_COMPLETE=complete_bash`, `COMP_WORDS=" ".join(["samba", *words])` and `COMP_CWORD=len(words)`, with cwd set to the sandbox repo.
  - Cases:
    - `plan accept ` offers only plan-review tasks.
    - `work accept ` offers only work-review tasks.
    - `task retry ` offers stuck tasks, and `task stop ` offers running tasks.
    - `question answer ` offers `task/qid` of open questions: add a question-state task with questions, either through the sidecar JSON and `## Questions` section as other blackbox tests do (look at how test_blackbox.py creates them), or via the CLI flow.
    - `adr accept ` offers only proposed ADRs: write `docs/adr/0001-*.md` and `0002-*.md` with the front matter used in the existing ADR tests, and check `supersede` and `show`.
    - A prefix filters the candidates.
    - `--repo` is honored: run from a different cwd with `--repo <sandbox>` before the incomplete word.
    - No repo (cwd with no WORKFLOW.md and no git), and broken WORKFLOW.md (invalid YAML): exit 0, no candidates, and `"Traceback" not in stderr` and stderr empty.
- [ ] Unit tests: create tests/test_app_completion.py in the style of tests/test_app_queries.py (`FakeTasks`, `FakeClock`, `FakeAdrs`). Cover every command label against its state set, derived-from-table behavior, the prefix filter, the `task/qid` format for open vs answered questions, the ADR status filters, and the empty cases.
- [ ] Extend tests/test_architecture.py:
  - Add "app/completion.py" to `APP_MODULES`; `test_every_domain_and_app_module_is_listed` enforces this.
  - The existing tests already forbid typer and click in app modules. Add an explicit test that app/completion.py imports no `typer` or `click`, with a bad-file fixture in the style of `test_domain_and_app_import_no_cli_library...`.
- [ ] Implement app/completion.py, then the bootstrap members, then the CLI callbacks.
- [ ] Update the docs: docs/spec/cli.md, docs/spec/architecture.md, docs/manual.md, and the CLAUDE.md map.
- [ ] Run `uv run pyright` (0 errors), then `uv run pytest -q`.
- [ ] Log what changed in the task file's `## Log`.

### Files to change
- src/samba/app/completion.py (new)
- src/samba/bootstrap.py
- src/samba/entrypoints/cli.py
- src/samba/domain/transitions.py (only if a tiny `human_sources` helper is added)
- tests/test_completion.py (new), tests/test_app_completion.py (new), tests/test_architecture.py
- docs/spec/cli.md, docs/spec/architecture.md, docs/manual.md, CLAUDE.md
- tests/test_manual.py only if a needle for dynamic completion is added (for example "TAB" or "task ids")

### Spec changes
- docs/spec/cli.md, "Shell completion": say completion is now dynamic. Describe which ids each verb offers (the legal source states come from the transition table) and `task/qid` for open questions. Describe ADR numbers by status. Say the callbacks resolve `--repo` from the context with a fallback to the current directory, and that any error yields no candidates, exit 0, and no output on stderr. Remove the "Next (dynamic, a separate task)" and "ids are not completed" wording.
- docs/spec/architecture.md: record the new completion queries in app/ (no typer or click, read-only, return plain strings with help), the new `Commands` and `AdrCommands` members, and the CLI callbacks that go through bootstrap only. If it carries a use-case or module list, add `app/completion.py` to it.
- docs/manual.md, "Shell completion": say ids are completed, with examples such as `samba plan accept <TAB>`. Mention that the candidates depend on the repo (`--repo` or the current directory) and that nothing is offered outside a repo.
- CLAUDE.md map: update the cli.py bullet from "dynamic id completion is a later task" to dynamic completion, and add `app/completion.py` with its one-line description.

### Risks
- `--repo` may not yet be in `ctx.params` for some shells or when `--repo` is typed after the incomplete word. The fallback to cwd covers it. A test uses `--repo` before the cursor word.
- Typer may print help or errors in resilient mode, so the black-box test must assert empty stderr. The broad try/except plus the no-print rule handle the callback side.
- `ctx.params` keys: the argument is named `id`, and `repo` must exist on every leaf. It is already declared on each leaf.
- Keep metavar and help output unchanged, since tests/test_cli_surface.py and tests/test_manual.py check help shape.
- Plan steps may only use allow-listed commands: use `git grep`, no mkdir, mv or redirects. `uv run pyright` and `uv run pytest -q` are separate plain commands.
- If the cost cap bites, split the work: (1) app queries, bootstrap and unit tests; (2) CLI callbacks, black-box tests and docs.

### How to verify
- `uv run pyright` reports 0 errors.
- `uv run pytest -q` is fully green, including the new tests/test_completion.py, tests/test_app_completion.py, tests/test_architecture.py, tests/test_cli_surface.py and tests/test_manual.py.
- Manual check: `_SAMBA_COMPLETE=complete_bash COMP_WORDS="samba plan accept " COMP_CWORD=3 uv run samba` in a sandbox lists plan-review ids only, and in an empty directory prints nothing with exit 0.

### Suggested subtasks
Only if needed: (a) app/completion.py, bootstrap and unit tests and the architecture test; (b) CLI callbacks, black-box tests/test_completion.py and the docs.

## Assumptions
- `samba adr list` could not be run in planning, because the installed `samba` binary lacks typer. The plan relies on the ADR 0014 text in docs/adr/ and on the task description. The executor should still run `uv run samba adr list` and read ADRs 0011-0015.
- Typer 0.12+ accepts an `autocompletion` callback `(ctx: typer.Context, incomplete: str) -> list[tuple[str, str]]`, where each tuple is (value, help). Click's bash/zsh/fish scripts print `type,value` lines, which is how test_cli_surface.py already parses output. Verify this once against the installed version.
- `--repo` is declared after the id on every leaf. Click resolves the already-typed words into `ctx.params` before the incomplete word, so `ctx.params.get("repo")` works when `--repo` was typed earlier on the line. If it was not typed, fall back to the current directory.
- `adr supersede N NEW`: only N is completed (accepted ADRs). NEW gets no completion, since the task does not specify it.
- `question show` and `question answer` complete the same candidates: `task/qid` of open questions only.
- Candidates are filtered by prefix on the incomplete word inside the app query, which takes `incomplete` as a plain string. This keeps the CLI free of logic.
- This fits one run; there is no chained subtask unless the cost cap bites.

## Log
- 2026-11-11 16:40 samba: dispatch_plan: plan-todo -> plan-running
- 2026-11-11 16:41 samba: planned: plan-running -> plan-review: planned (turns 1, $0.30): Add read-only completion queries in a new app/completion.py (legal source states derived from the transition table with find_row), expose them through bootstrap, and wire silent, error-swallowing Typer autocompletion callbacks on the id arguments. Tests come first, then the code, then spec, manual and CLAUDE.md updates.
- 2026-11-11 16:42 samba: plan.accept: plan-review -> work-todo
- 2026-11-11 16:42 samba: dispatch_work: work-todo -> work-running
- Work done: app/completion.py (CompleteTaskIds, CompleteQuestions, CompleteAdrs; legal states via find_row, no human_sources helper needed), bootstrap members, Typer autocompletion callbacks in cli.py (broad except, cwd fallback for --repo), tests/test_completion.py, tests/test_app_completion.py, architecture test. Click's bash script prints a blank line when there are no candidates, so black-box tests ignore empty lines. Help text is one-line, state + title. pyright 0 errors, pytest 734 passed.
- Spec: docs/spec/cli.md (Shell completion now dynamic, per-verb rules), docs/spec/architecture.md (completion queries, new Commands/AdrCommands members, callbacks), docs/manual.md, CLAUDE.md. No ADR: follows ADR 0014.
- 2026-11-11 16:52 samba: done: work-running -> work-review: validation passed (turns 2, $1.03): Added dynamic completion of task ids, question ids (task/qid) and ADR numbers: queries in app/completion.py, bootstrap members, silent error-swallowing Typer callbacks, and unit, black-box and architecture tests. Spec (cli, architecture), manual and CLAUDE.md are updated. pyright reports 0 errors and pytest passes (734 tests), all committed on the branch.
- 2026-11-11 16:57 samba: work.accept: work-review -> done: merged 902230c, validated
