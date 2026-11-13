# Samba

Local orchestrator that runs Claude Code headless on markdown task files, one git worktree per task.

## Map

- `docs/spec/`: the specification, the source of truth for behavior. Start at `docs/spec/README.md`,
  the index: one line per chapter saying when to read it. Chapters are named by topic (`overview`,
  `layout`, `task-files`, `states`, `orchestrator`, `workflow-config`, `workspaces`, `prompts`,
  `running-claude`, `observability`, `cli`, `architecture`, `implementation-notes`, `backlog`) and are referenced by name, not by number. Read the chapters relevant to your task
  before changing code, and update the spec in the same change when behavior changes.
- `README.md`: entry point with a short quickstart; links to the manual and the spec.
- `docs/manual.md`: the user manual (setup, daily loop, troubleshooting), for people using Samba.
  `tests/e2e/test_completion_and_docs_e2e.py` fails when a CLI subcommand is not mentioned in it,
  so update it when you add, rename or remove a command.
- `src/samba/`: the root holds only `__init__.py`, `__main__.py`, `bootstrap.py` and the packages
  `domain`, `app`, `adapters` and `entrypoints` (guarded by `tests/checks/test_architecture.py`).
  - `entrypoints/cli.py`: a Typer app (ADR 0014; no argparse; `typer` is a runtime dependency, with
    shellingham, rich and pydantic; static shell completion via `--install-completion` and
    `--show-completion`, and dynamic completion of task ids, question ids and ADR numbers through
    callbacks that use `bootstrap` only and swallow every error). One function per command, `--repo`
    declared on each leaf, `domain/` and `app/` never import `typer`. Parse, one call, render (no rule): `run` and `<noun> <verb>` commands, no aliases:
    `task new|list|show|retry|stop|discard`, `plan`/`work` review commands (including
    `work accept`), `question list|show|answer` (answers are recorded per question),
    `adr list|show|accept|reject|supersede` (needs no WORKFLOW.md), `explore [topic]`
    (`explore_cmd`, an interactive claude session), `dev transitions`. Each command function makes
    one call that passes plain values to one use case, and `render(result)` prints it and maps
    the kind to the exit code (`finish` raises `typer.Exit`). No if/elif on command names;
    `run` (`run_cmd`), `explore` and `dev transitions` keep their own small paths. `tests/e2e/test_cli_shape.py`
    and `tests/e2e/test_completion_and_docs_e2e.py` cover help shape, usage errors and completion. It imports
    neither `app/resolve.py` nor `domain/task_id.py` nor another entry point.
    The script entry is `samba.entrypoints.cli:main`.
  - `bootstrap.py`: the composition root, called by every entry point; the only module that may
    import every layer and the only place that builds adapters. `build(repo)` reads
    `WORKFLOW.md` and returns `Commands` (use cases only: `AcceptPlan`, `RejectPlan`, `RejectWork`,
    `RetryTask`, `StopTask`, `DiscardTask`, the four queries, `AnswerQuestion`, `AcceptWork`,
    `CreateTask`); `build_orchestrator(repo)` is the separate builder used only by `samba run`;
    `build_adr(repo)` returns `AdrCommands`, the config-free entry for the ADR commands;
    `build_explore(repo)` needs only `claude.command` and `claude.model`. Constructors take their ports, no defaults.
  - `app/task_commands.py`: the six named use cases over `ChangeState` (event strings, labels and
    feedback modes live here, not in the CLI).
  - `domain/launch.py`: `LaunchSpec` and `explore_launch` (the argv of `samba explore`; the guide
    and the allow and deny lists are `EXPLORE_*` in `domain/prompts.py`). `app/explore.py`: `StartExplore`,
    over the `InteractiveSession` port; `adapters/interactive_session.py` (`TerminalSession`) runs
    it on the terminal. Not an `AgentRunner`, no stream-json.
  - `adapters/adr_format.py`: ADR files under `docs/adr/`: front matter parsing, summary line, status edits.
    `adapters/adr_files.py` (`FileAdrs`) is the `Adrs` port over it; `app/adr.py` holds the ADR
    use cases (`ListAdrs`, `ShowAdr`, `SetAdrStatus`, `SupersedeAdr`) and `app/queries.py` the
    read-only ones (`ListTasks`, `ShowTask`, `ListQuestions`, `ShowQuestion`), returning
    `Table`/`Text`/`Written` from `app/results.py`.
  - `app/completion.py`: `CompleteTaskIds`, `CompleteQuestions`, `CompleteAdrs`: read-only queries
    returning `(value, help)` strings for shell completion (legal states come from the transition
    table via `find_row`); exposed as `Commands.complete_tasks`, `complete_questions` and
    `AdrCommands.complete`.
  - `entrypoints/table.py`: the table printer of the CLI (the rows come from `app/queries.py`, which
    also holds the state-prefix matcher and the `task show` renderer).
  - `domain/settings.py`: the plain settings (`Policy`, `AgentSettings`, `Repository`, `Prompts`,
    `Validation`, `Hooks`, `Config`), `ConfigError` and the `DEFAULT_*` lists; no location, no
    pathlib or yaml. `adapters/workflow_file.py`: loads and validates `WORKFLOW.md` (front matter +
    prompt body), `load_config` returns the `Config` and a `Locations` (real paths, for adapters only).
  - `domain/`: the pure core, no I/O (`architecture` chapter). `states.py` (`State`, causes),
    `questions.py` (question records and helpers), `task.py` (the `Task` aggregate),
    `task_id.py` (`TaskId`, slug, prefix resolution),
    `transitions.py` (the transition table as plain data, effects, `find_row`, `human_row`,
    `human_events`, the markdown renderer; `samba dev transitions` prints it and the states chapter
    embeds the output), `deps.py` (`depends_on` evaluation over a snapshot,
    `docs/spec/orchestrator.md`, Dependencies).
  - `domain/policy.py`: `Budget`, `RetryPolicy`, `should_reflect` and `decide_after_turn` (one
    action after a turn: fail, finish, run validation, record questions, continue).
  - `app/turn.py`: `TurnFlow`, the turn loop shared by planning and work, over the `AgentRunner`
    port; the orchestrator fires the transition for what it returns.
  - `app/change_state.py`: `ChangeState` (the command pattern of plan/work reject, task
    retry/stop/discard, plan accept) and `check_legal`, the single legality check;
    `app/answer_question.py`: `AnswerQuestion`; `app/accept_work.py`: `AcceptWork` (`work accept`, async: the
    merge sequence over the `Vcs` and `Validator` ports); `app/create_task.py`: `CreateTask` (`task new`); `app/resolve.py`:
    `find_task` (id or prefix to a `TaskId` or a `usage` refusal; use cases resolve ids, the CLI does not),
    `split_target`, `resolve_task_id`, `resolve_deps`, `ResolveError`; `app/confirm.py`: the confirmation policy over the
    `Terminal` port; `app/results.py`: the closed `Result` set (`Done`, `Table`, `Text`, `Written`, `Refused`) and message helpers. Use cases never print: the
    CLI prints their results and maps `kind` to the exit code.
  - `adapters/git_vcs.py` (`GitVcs`, the `Vcs` port: worktrees outside the repo, the after_create
    hook, the git steps of `work accept`), `adapters/shell_validator.py` (`ShellValidator`, the
    `Validator` port),
    `adapters/terminal.py` (`StdTerminal`, the `Terminal` port: tty, prompts, `$EDITOR`),
    `adapters/file_lock.py` (`FileLock`, the `Lock` port: the `.samba/lock` flock shared by commands
    and orchestrator ticks), `adapters/log_journal.py` (`LogJournal`, `NullJournal`: the `Journal`
    port, and the `kv` log line format; only `samba run` gets the log, `bootstrap.build_orchestrator(repo)`).
  - `adapters/markdown_tasks.py`: `MarkdownTasks`, the `Tasks` port over the task folders, the
    sidecar JSON and the `## Log`/`## Questions` sections (stale-save merge, hand-move detection).
  - `app/tick.py`: `Tick` (observe hand moves, reconcile running workers, clean up workspaces,
    dispatch with dependency rows), `Notes` (held `## Log` lines) and `Running`; starts workers
    through a `spawn` callback.
  - `entrypoints/orchestrator.py`: the thin `Orchestrator` (about 100 lines, no rule; guarded by
    `tests/checks/test_architecture.py`): builds the parts below and runs startup, then tick and sleep,
    `Workers.shutdown` in a `finally`, exit when idle (ADR 0015).
  - `entrypoints/workers.py`: `Workers`: `spawn` (the callback of `Tick`), the `running` dict and
    `Notes` shared with `Tick`, the cancelled-worker handling (journal `stopped`, recover on
    shutdown, workspace removal when moved), `run_task.crashed` for other exceptions, `shutdown`,
    `wait_all` (tests).
  - `app/guard.py` (`Guard`: `plan_required`, `deps_met`), `app/startup.py` (`Startup` and
    `StartupError`: checks, config warnings, recovery), `app/run_task.py` (`RunTask`: the run of one
    task), `app/prompt_builder.py` (`PromptBuilder`: variables, prompts, `TurnSetup`), `app/finish.py`
    (`Finisher`: finish, or retry, reflect, give up). App modules import no `asyncio`
    (`Running.task` is a `Cancellable` in `app/tick.py`).
  - `app/machine.py`: `Machine.fire` and `observe`, the only path that moves a task
    (`docs/spec/states.md`): loads the `Task`, applies the domain row, saves.
  - `adapters/claude_cli.py`: `ClaudeCliRunner`, the only reader of Claude's stream-json: builds
    the argv, runs `claude`, maps the output into an `AgentReport`. `domain/agent.py`:
    `AgentRequest`, `AgentReport`, `Readiness`.
  - `domain/ports.py`: the ports (Protocols `Clock`, `IdGenerator`, `AgentRunner`, `Tasks` and the
    rest; at the domain level because `Task` uses the clock port); `adapters/system.py`: the system
    clock and uuid generator. The layers and the dependency rule are in the `architecture` chapter.
  - `adapters/process.py`: subprocess helpers (process groups), used only inside adapters.
  - `domain/prompts.py`: built-in prompts, the protocol prompt, the outcome schema.
  - `domain/template.py`: strict `{{ name }}` rendering.
- `tests/`
  Four levels (ADR 0016), one folder each, plus `checks/` and `fakes/`. The root of `tests/` holds
  no `.py`. Folders have no `__init__.py`, so every test file basename is unique across `tests/`,
  and `fakes` and `component` are on the pytest `pythonpath` (pyright `extraPaths` also has
  `e2e`), so fakes and shared rigs are imported by module name. Sizes: about 40 unit, 330
  component, 145 integration and 50 end-to-end cases (27 functions). Coverage of `src/samba`:
  `uv run pytest --cov` (configured in `pyproject.toml`, subprocesses included), about 96%.
  - `unit/`: pure domain pieces (`test_task_domain.py`, `test_validation_domain.py`,
    `test_transition_table_shape.py`, `test_table_printer.py` for `entrypoints/table.py`). No
    adapter, no fake.
  - `component/`: use cases and parts over the in-memory fakes, no adapter: `test_app_*.py`
    (`Startup`, `RunTask` with `PromptBuilder` and `Finisher`, `Guard`, queries, completion,
    explore, resolve, use cases), `test_tick.py`, `test_agent_port.py` (the fake agent runner),
    and `test_scenarios.py` with `scenarios/*.json` (the scenario runner and its data, ADR 0012,
    `architecture` chapter, Scenarios; `lifecycle.json` is the whole life of a task over the orchestrator, the use cases and the fakes).
    Focused files reuse those rigs (`from test_tick import Rig`, `from test_app_run_task import
    Rig, make_config`): `test_system_prompts.py`, `test_dispatch_with_dependencies.py`,
    `test_workers_and_shutdown.py` (a live worker stopped, discarded, shut down; exit when idle),
    `test_blocked_report_without_questions.py`, and for the commands `test_task_list_and_show.py`,
    `test_command_messages.py` (retry hints, the discard prompt), `test_question_rounds.py`,
    `test_task_new_inputs.py`.
  - `integration/`: one adapter against the real thing (`test_config.py`, `test_tasks_port.py`,
    `test_adapters_vcs_validator_journal.py`, `test_markdown_task_files.py` (the file layout),
    `test_lock_port.py` (contract on `FakeLock` and `FileLock`, real contention, commands under
    the lock), `test_terminal_adapter.py` (a real pseudo terminal, `$EDITOR`),
    `test_claude_runner.py` (`ClaudeCliRunner` against `fakes/fake_claude.py`: argv, isolation,
    stream parsing, kills on stall, timeout and cancel), `test_adr_store.py` (contract on
    `FakeAdrs` and `FileAdrs`, then the files)). Where a fake has
    behavior of its own (tasks, lock, ADRs) the port contract runs against both fake and adapter
    through one parametrized fixture; scripted fakes are not paired. Imports neither
    `samba.entrypoints` nor `samba.bootstrap`. Few.
  - `e2e/`: the `samba` CLI as a subprocess, asserting only on files and on calls recorded by the
    fake claude. **It must never import the `samba` package**: the suite is meant to be reused
    unchanged against a future rewrite in another language (`SAMBA_CMD` replaces the command).
    `e2e_box.py` is its own small sandbox (the `box` fixture in `conftest.py`): a temp git repo,
    `WORKFLOW.md`, the scripted fake claude. Files: `test_cli_shape.py` (help, usage errors exit 2,
    stdout vs stderr, config errors), `test_completion_and_docs_e2e.py` (completion through the
    environment, and the manual drift check: every command in `--help` is in `docs/manual.md`),
    `test_explore_e2e.py`, `test_journeys.py` (a few whole journeys), `test_signals_and_terminal.py`
    (SIGINT, `task stop` of a live agent, prompts on a real pty), `test_every_command_runs.py` (each
    command binding reaches its use case). Each test's docstring says what
    only this level shows; `checks/test_e2e_budget.py` caps it at 30 test functions.
  - `checks/`: `test_architecture.py` (the dependency rule and the per-folder import rules; reads
    sources with `ast`, never imports `samba`; append moved domain modules to its `DOMAIN_MODULES`)
    and `test_spec_docs.py` (spec drift), `test_repo_docs_match_the_code.py` (the states chapter
    table and the repository `WORKFLOW.md` body agree with the code), `test_manual_text.py` (the
    manual documents completion; no em-dashes in README and manual), `test_e2e_budget.py`.
  - `fakes/`: `fake_claude.py` (scripted fake of the `claude` CLI, standard library only, used by
    the e2e tests and `integration/test_claude_runner.py`), `fake_agent.py` (fake `AgentRunner`), `fake_session.py`
    (`FakeSession`, the `InteractiveSession` fake), `fake_tasks.py`, `fake_vcs.py`,
    `fake_validator.py`, `fake_journal.py`, `fake_terminal.py` (with `FakeLock`), `fake_clock.py`
    (`FakeClock`), `fake_adrs.py` (`FakeAdrs`): in-memory fakes of the ports.

## Checks

Run these as separate, plain commands (no pipes or `&&`):

- `uv run pyright` (strict mode, must report 0 errors)
- `uv run pytest -q tests/unit tests/component` (the fast loop, under a second): run it while working
- `uv run pytest -q -n auto` (the full run in parallel with pytest-xdist, about 20 seconds;
  about a minute without `-n auto`, mostly `tests/e2e`): run it before reporting done

## Conventions

- Python 3.11+, fully typed; no `Any` leaking into public signatures, use `cast` at JSON/YAML
  boundaries.
- New behavior gets a test first, at the lowest level that can show it (ADR 0016: unit, component,
  integration, end-to-end); integration and end-to-end tests stay few. A port whose fake has
  behavior of its own gets its contract run against both fake and adapter. An end-to-end test
  needs a docstring saying what only that level shows, and the level has a budget.
- Prose in docs and prompts: no em-dashes.
