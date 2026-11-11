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
  `tests/test_manual.py` fails when a CLI subcommand is not mentioned in it, so update it when
  you add, rename or remove a command.
- `src/samba/`: the root holds only `__init__.py`, `__main__.py`, `bootstrap.py` and the packages
  `domain`, `app`, `adapters` and `entrypoints` (guarded by `tests/test_architecture.py`).
  - `entrypoints/cli.py`: a Typer app (ADR 0014; no argparse; `typer` is a runtime dependency, with
    shellingham, rich and pydantic; static shell completion via `--install-completion` and
    `--show-completion`, dynamic id completion is a later task). One function per command, `--repo`
    declared on each leaf, `domain/` and `app/` never import `typer`. Parse, one call, render (no rule): `run` and `<noun> <verb>` commands, no aliases:
    `task new|list|show|retry|stop|discard`, `plan`/`work` review commands (including
    `work accept`), `question list|show|answer` (answers are recorded per question),
    `adr list|show|accept|reject|supersede` (needs no WORKFLOW.md), `explore [topic]`
    (`explore_cmd`, an interactive claude session), `dev transitions`. Each command function makes
    one call that passes plain values to one use case, and `render(result)` prints it and maps
    the kind to the exit code (`finish` raises `typer.Exit`). No if/elif on command names;
    `run` (`run_cmd`), `explore` and `dev transitions` keep their own small paths. `tests/test_cli_surface.py`
    covers help shape, usage errors and completion. It imports
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
    `tests/test_architecture.py`): builds the parts below and runs startup, then tick and sleep,
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
  - `test_blackbox.py`: the main suite. It runs the `samba` CLI as a subprocess and asserts only
    on files and on calls recorded by the fake. **It must never import the `samba` package**:
    the suite is meant to be reused unchanged against a future rewrite in another language.
  - `conftest.py`: the `Sandbox` fixture (temp git repo, WORKFLOW.md, tasks, helpers).
  - `test_manual.py`: drift check for `docs/manual.md`. Runs the CLI's `--help` and reads files,
    never imports `samba`.
  - `test_scenarios.py` and `scenarios/*.json`: the scenario runner and its data (ADR 0012,
    `architecture` chapter, Scenarios), including `lifecycle.json`: the whole life of a task over
    the orchestrator, the use cases and the fakes. Imports the domain, `app/` and
    `entrypoints/orchestrator.py`, never an adapter.
  - `test_app_startup.py`, `test_app_run_task.py`: `Startup`, `RunTask` (with `PromptBuilder`,
    `Finisher`) and `Guard` over the fakes, no loop of their own.
  - `test_architecture.py`: guards the dependency rule. Reads sources with `ast`, never imports
    `samba`; append moved domain modules to its `DOMAIN_MODULES`.
  - `fake_claude.py`: scripted fake of the `claude` CLI. Standard library only.
  - `fake_agent.py`: in-memory fake `AgentRunner` (scripted reports), tested in `test_agent_port.py`.
  - `fake_session.py` (`FakeSession`, the `InteractiveSession` fake; `test_app_explore.py`,
    `test_explore.py`), `fake_vcs.py`, `fake_validator.py`, `fake_journal.py`, `fake_terminal.py` (with `FakeLock`):
    in-memory fakes of the `Vcs`, `Validator`, `Journal`, `Terminal` and `Lock` ports.

## Checks

Run these as separate, plain commands (no pipes or `&&`):

- `uv run pyright` (strict mode, must report 0 errors)
- `uv run pytest -q` (about 25 seconds)

## Conventions

- Python 3.11+, fully typed; no `Any` leaking into public signatures, use `cast` at JSON/YAML
  boundaries.
- New behavior gets a black-box test first, in the style of the existing ones.
- Prose in docs and prompts: no em-dashes.
