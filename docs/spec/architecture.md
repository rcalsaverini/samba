# Architecture

Samba is layered so the rules of the core can be tested without a clock, a disk, a subprocess or a
network (ADR 0011, ADR 0012). This chapter describes the layers, the ports and where each piece
lives.

## Layers

| Layer | Location | Holds |
|---|---|---|
| Domain | `src/samba/domain/` | Pure rules and data: states, question records, the transition table, dependency evaluation. No I/O. (This includes `domain/template.py` and `domain/prompts.py`.) |
| Use cases | `src/samba/app/` | The operations of the orchestrator and the commands, written against ports. |
| Ports | `src/samba/domain/ports.py` | Protocols for everything the core needs from the outside world. They sit at the domain level: the domain's `Task` depends on the clock port. |
| Adapters | `src/samba/adapters/` | Implementations of the ports: system clock, files, git, the `claude` runner, the terminal. |
| Entry points | `src/samba/entrypoints/` | What starts Samba: `cli.py` (parse, one call, render), `table.py` (the table printer of the CLI) and `workers.py` (the asyncio workers) and `orchestrator.py` (the wiring and the poll loop; see Orchestrator parts). They call `bootstrap`, the use cases and the ports, never an adapter. |

The root of `src/samba/` holds only `__init__.py`, `__main__.py`, `bootstrap.py` and the four
packages `domain`, `app`, `adapters` and `entrypoints`. `bootstrap.py` is the one module allowed to
import every layer.

## Dependency rule

Dependencies point inward only: entry points depend on `bootstrap`, the use cases, the domain and
the ports; adapters depend on ports and the domain, use cases depend on the
domain and ports, the domain depends on nothing outside itself. No inner layer (`domain`, `app`,
`adapters`) imports `bootstrap` or `entrypoints`. The ports are Protocols that live
in the domain package (`domain/ports.py`), so this holds for them too. A domain module imports none of
`os`, `time`, `datetime`, `uuid`, `subprocess`, `asyncio`, `logging`, `pathlib`, and no adapter.
The composition root, `bootstrap.py`, is the only place that builds adapters and hands them to use
cases. This refines the last sentence of ADR 0011: the composition root is `bootstrap.py`, called
by every entry point. `build(repo)` loads `WORKFLOW.md` and returns `Commands`, which exposes only
use cases: the six named state-changing ones over `ChangeState` (`AcceptPlan`, `RejectPlan`,
`RejectWork`, `RetryTask`, `StopTask`, `DiscardTask`, in `app/task_commands.py`), the four
read-only queries (`ListTasks`, `ShowTask`, `ListQuestions`, `ShowQuestion`), `AnswerQuestion`,
`AcceptWork` and `CreateTask`, and the completion queries `complete_tasks` (`CompleteTaskIds`) and
`complete_questions` (`CompleteQuestions`); `AdrCommands` has `complete` (`CompleteAdrs`). The
completion queries live in `app/completion.py`: read-only, no `typer` or `click`, they take plain
strings (the command label and the typed prefix) and return `(value, help)` pairs of plain
strings. The states a verb can act on come from the transition table (`find_row`), not from the
CLI. The Typer completion callbacks in `cli.py` go through `bootstrap` and these queries only,
print nothing and turn every error into no candidates. It holds no config, no `Tasks` port and no orchestrator, so it is
the contract a web page or an MCP server could call too. `build_orchestrator(repo)` is a separate
function, used only by `samba run` (the orchestrator is not a use case; it is the only builder
of the `LogJournal`). `build_adr(repo)` returns `AdrCommands` for the ADR commands, which
need no config. `build_explore(repo)` serves `samba explore`: it loads `WORKFLOW.md` but uses only
`claude.command` and `claude.model`. Constructors take their ports as required parameters and have no defaults.
`entrypoints/cli.py` is a Typer app (ADR 0014): parse, one call, render. Each command is a function
whose signature declares its arguments and options, builds the use cases through `bootstrap` and
passes plain values (the id or `TASK[/QID]` as typed, text, flags) to exactly one use case, and one shared
`render(result)` maps `Done`, `Table`, `Text`, `Written` and `Refused` to output and the exit code
(0, 1 for `refused`, 2 for `usage`). It holds no rule, does not resolve ids and has no `if`
chain on command names. `run`, `explore` and `dev transitions` keep their own small paths and are
outside the contract. No entry point calls another: `cli.py` imports neither `orchestrator.py` nor
`workers.py`, and `tests/checks/test_architecture.py` guards it, along with `cli.py` importing neither
`app/resolve.py` nor `domain/task_id.py`, `domain/` and `app/` modules never importing `typer` or
`click`, and no module importing `argparse`.

The use cases take plain values (strings, numbers, booleans) and resolve the task id or unique
prefix themselves (`find_task` in `app/resolve.py`: an unknown or ambiguous id is a `usage`
refusal). Each returns one of a closed set (`Result` in `app/results.py`): `Done` (location on
stdout, notes on stderr), `Table`, `Text` (a `work accept --dry-run` plan is a `Text`), `Written`
(ADR files) or `Refused` (`refused` or `usage`). `Explored` stays apart, for `explore`.

The `Terminal` port stays how a use case asks for a confirmation or for text (`$EDITOR`); a
non-interactive caller (a web page, an MCP server) passes `yes` or the text up front and the use
case never touches the terminal. ADR 0013 is complete: named use cases, `Commands`, and the CLI
as parse, call, render.

## Ports

| Port | Methods | Adapter |
|---|---|---|
| `Clock` | `time()` wall seconds, `monotonic()`, `iso_seconds()` local ISO 8601 to the second, `log_stamp()` local `YYYY-MM-DD HH:MM` | `SystemClock` in `adapters/system.py` |
| `IdGenerator` | `new_session_id()` | `UuidGenerator` in `adapters/system.py` |
| `AgentRunner` | `run(AgentRequest) -> AgentReport`, `ready() -> Readiness` | `ClaudeCliRunner` in `adapters/claude_cli.py` |
| `Terminal` | `is_interactive()`, `ask(prompt)` (raises `EOFError` at end of input), `read_block(prompt)`, `warn(line)` (one line to stderr mid-dialogue), `edit(initial) -> EditResult` (the text, or an error message) | `StdTerminal` in `adapters/terminal.py` |
| `Lock` | `acquire(blocking) -> context manager yielding held` | `FileLock` in `adapters/file_lock.py` (the `.samba/lock` flock; replaces `lock.py` and `RepoLock`) |
| `Vcs` | All async, locations opaque text: `branch_name(task_id)`, `workspace_location(task_id)`, `ensure_workspace(task_id) -> Workspace(location, created)` (runs the `after_create` hook, removes the worktree if it fails, raises `WorkspaceError`), `remove_workspace(task_id)`, `existing_workspaces()`, `repository_problem() -> str \| None`, `preflight(branch)`, `commit_count(branch)`, `begin_merge(branch, message) -> MergeAttempt(status, detail, restore_point)` (`pending`, `already`, `conflict`, `error`; conflict and error are already undone), `abort_merge(restore_point)`, `commit_merge(restore_point) -> CommitResult(ok, detail)`, `checkout_location()`, `exclude_samba_dir()`. The restore point is returned, so the adapter keeps no merge state | `GitVcs` in `adapters/git_vcs.py` (replaces `workspace.py`, `merge.py`, `GitMerger` and `GitWorkspaces`). `AcceptWork` (async, one `asyncio.run` in `entrypoints/cli.py`) runs the merge sequence over it: `begin_merge`, the validator in `checkout_location()`, then `abort_merge` or `commit_merge` |
| `Validator` | `run(location, log_name) -> ValidationResult` (async; stores the full output under the runs directory; `domain/validation.py` holds the result and the two tail formats `agent_tail` and `accept_tail`) | `ShellValidator` in `adapters/shell_validator.py`; `TurnFlow` and `AcceptWork` call it, and it creates the directories of the logs it writes |
| `Journal` | `debug`, `info`, `warning`, `exception(event, **fields)`; `exception` adds the traceback | `LogJournal` in `adapters/log_journal.py` (`samba.log` at DEBUG, stderr at INFO, the `kv` format), `NullJournal` for commands that write no log. Injected into `Machine`, `Tick`, `TurnFlow`, `Startup`, `RunTask`, `Finisher`, `Workers`, `Orchestrator` and `ClaudeCliRunner`; `bootstrap.build_orchestrator(repo)` builds the `LogJournal` for `samba run` only |
| `Adrs` | `parse_number(text)`, `load_all() -> list[AdrInfo]`, `find(number)`, `set_status(number, verb, allowed_from, status) -> files`, `supersede(old, new) -> files`; every method may raise `AdrError(message, code)` (`code` 1 refused, 2 usage); `AdrInfo` carries `file` as text | `FileAdrs` in `adapters/adr_files.py` (wraps `adapters/adr_format.py`) |
| `InteractiveSession` | `run(LaunchSpec(argv, cwd)) -> exit code`, not async; runs the program attached to the person's terminal. Raises `LaunchError(message)` when it cannot start (for example `claude` not found). `LaunchSpec` is in `domain/launch.py` | `TerminalSession` in `adapters/interactive_session.py`: `subprocess.run` with the terminal inherited, SIGINT ignored in Samba while the child runs. It reads no stream-json and is not an `AgentRunner`. Used by `StartExplore` (`app/explore.py`) |
| `Tasks` | `get(id)`, `list(status)`, `ids(status?)`, `create(task)`, `save(task) -> bool`, `observe_moves()`, `accept_move(move)`, `revert_move(move)`, `rejected_names(status)`, `location(id)`, `prepare()` | `MarkdownTasks` in `adapters/markdown_tasks.py`; the in-memory `FakeTasks` for tests is `tests/fakes/fake_tasks.py` |

### The Tasks port and stale saves

`Task` (`domain/task.py`) is the one record the core talks to: identity (`TaskId`, `domain/task_id.py`),
title, body, priority, `depends_on`, `status` (a `State`), the counters, the session ids, the closed
`last_stage`, `blocked_cause` and `last_outcome`, `queued_at`, `branch` and `workspace` (opaque
strings), and the plan, assumptions, feedback rounds, log lines and question records. The store
behind the port is the adapter's business. The orchestrator, the CLI and the views all go through
the port; the folder helpers of the old `tasks.py` are gone, and front matter of task files is read
and written only by `MarkdownTasks`.

A worker holds a `Task` for minutes while commands (`task stop`, `question answer`, `work reject`)
write the same record, and the agent edits its own task file. So `save` is not "write what I
hold". The rule, which every adapter keeps:

- `get` and `list` remember a snapshot of what they returned (identity is the key, the domain has no
  version field).
- `save(task)` re-reads the stored record and diffs the aggregate against its snapshot. Only the
  fields the aggregate changed are written; the others keep the stored value. A scalar changed on
  both sides takes the aggregate's value.
- `log` and `feedback` are append-only: only entries beyond the snapshot's are appended to the stored
  ones, so lines written meanwhile (by a human, by the agent) stay.
- `questions` merge by id. A question both sides changed keeps the stored version, so a human's
  answer is not lost.
- `status` is written only if the aggregate changed it, and then only if the stored status is still
  the one it was loaded with. Otherwise `save` returns False and writes nothing (the old
  compare-and-move).
- The store's record of the last known status (for hand moves) changes only on a status-changing
  save, on first sight and in `accept_move`. A stale counter save never resets it, so a hand move is
  not missed.
- `MarkdownTasks` rewrites the `.md` only when a field the file owns changed (`body`, `plan`,
  `assumptions`, `log`, `feedback`, `questions`, `status`); a counter-only save touches only the sidecar
  JSON.
- After a successful save the aggregate is refreshed in place from the merged record and its snapshot
  renewed, so the worker's copy picks up what a human changed.

A version number with a conflict-and-retry loop was rejected: it would push retry logic into every use
case and make workers re-apply their increments. A database adapter can use row versions behind the
same port.

`AgentRequest`, `AgentReport`, `Failure`, `QuestionDraft` and `Readiness` are frozen dataclasses in
`domain/agent.py` (running-claude, Adapter boundary and the report). The orchestrator takes an
`agent`, passed in by the composition root, like the clock. The fake runner for tests is
`tests/fakes/fake_agent.py`.

The clock is threaded through `Machine`, the transition effects (`not_before`,
`first_dispatched_at`, `queued_at`), the question helpers (`add_questions`, `answer_question`,
`dismiss_open`), `log_line`, `MarkdownTasks` and the orchestrator. Timestamps written to task
files and sidecars are formatted by the clock (`iso_seconds`, `log_stamp`), because the domain may
not import `datetime`. The clock is always a required parameter, in the domain and in the
constructors of `MarkdownTasks` and `Orchestrator`; only the composition root builds `SystemClock`.

## Where each concern lives

Moved into `domain/`: states and causes (`states.py`), question records (`questions.py`), the
`Task` aggregate and `TaskId`, the transition table, effects, `find_row`, `human_row`,
`human_events` and the markdown renderer (`transitions.py`), and dependency evaluation
(`deps.py`), and the settings types (`settings.py`). The effects, `apply_row` and the row helpers work on a `Task`; `apply_row` sets
`status`, stamps `queued_at` when the destination is a todo status (the dispatch order key) and
tells whether the questions changed. `evaluate` takes a snapshot (`TaskRef` per task id, an absent
id is unknown); `deps_snapshot(task, get)` in `deps.py` builds it from the task and its
`depends_on` closure. `Machine` (`fire`, `observe`) is the use case `app/machine.py`: it loads the
task through the `Tasks` port, applies a row, adds the log line and saves once. The orchestrator
holds a `Tasks` (a `MarkdownTasks` built by the root) and no sidecar store.

Policy is in `domain/policy.py`: `Budget` (cap, spent, `left`, `exceeded`), `RetryPolicy` (`decide`
gives `Retry` with the delay or `GiveUp`), `should_reflect` (the give-up turn) and
`decide_after_turn`, which turns an `AgentReport` into one action: `Fail`, `Finish`,
`RunValidation`, `RecordQuestions` or `Continue`. A failure wins over the budget, the budget over
the outcome. The turn flow shared by planning and work is the use case `app/turn.py` (`TurnFlow`):
it drives the `AgentRunner` port, executes the action and returns `Finish` or `Fail` to the
orchestrator, which fires the transition. It mutates the `Task` it is given (plan, assumptions,
questions, denial log lines, counters) and calls `Tasks.save` after each step.

Configuration is plain data in `domain/settings.py`, a composite of frozen parts, so each consumer
takes only the part it needs: `Policy` (turns, retries, cost cap, `reflect_on_give_up`,
`require_plan`, concurrency, polling), `AgentSettings` (the `claude` command, permissions, timeouts
and the planning model and allow list; taken by `adapters/claude_cli.py`), `Repository` (the base
branch), `Prompts` (the body template and the overrides), `Validation` (command, timeout, tail
lines, shell) and `Hooks` (`after_create`, timeout). `Config` holds one of each plus `warnings`.
`ConfigError` and the `DEFAULT_ALLOW` and `DEFAULT_PLANNING_ALLOW` lists live there too. The core
carries no location (ADR 0011): `Layout` is gone, and the orchestrator and the use cases get the
repo as opaque text through the `Vcs` port (`checkout_location`). `adapters/workflow_file.py` reads
and validates `WORKFLOW.md`; `load_config` returns the `Config` plus a `Locations` of real paths
(repo, Samba directory, workspaces root), including the check that the workspaces root is outside
the repo. Bootstrap hands `Locations` only to `GitVcs` (which also takes the base branch, `Hooks`
and the shell), `FileLock`, `MarkdownTasks`, `LogJournal` and `ClaudeCliRunner`.

The terminal, git (workspaces and merge), validation, the lock, the journal and the ADR files are
behind ports. `entrypoints/orchestrator.py` (wiring, poll loop) and `entrypoints/workers.py` import no adapter, `logging`,
`subprocess` or `pathlib`; the decisions are in `app/`. What is not behind a port:

- Subprocess helpers: `adapters/process.py`, used only inside adapters.
- The table printer `entrypoints/table.py`, the CLI's output (it reads `time.time` for column widths).
- The test-only `SAMBA_DEBUG_FIRE_DELAY` sleep is in `MarkdownTasks.save`, between the rename and
  the sidecar write.

## Orchestrator parts

ADR 0015 splits the orchestrator into named parts. Every rule is in `app/`; the entry point only
wires and supervises:

| Part | Module | Owns |
|---|---|---|
| `Guard` | `app/guard.py` | the `plan_required` and `deps_met` guards handed to `Machine` |
| `Startup` | `app/startup.py` | the startup checks (store, repository, agent login), config warnings, `exclude_samba_dir`, recovery of tasks left running; `StartupError` lives here |
| `RunTask` | `app/run_task.py` | the run of one task: workspace, turn setup, `TurnFlow`, then finish or fail; `crashed` for a bug in Samba |
| `PromptBuilder` | `app/prompt_builder.py` | the prompt variables, system prompt, named prompts and the `TurnSetup` of a stage |
| `Finisher` | `app/finish.py` | the finishing transition, and the retry, reflect or give-up decision after a failed attempt |

| `Tick` | `app/tick.py` | observe hand moves, reconcile running workers, clean up workspaces, dispatch; starts workers through a `spawn` callback |
| `Workers` | `entrypoints/workers.py` | `spawn`, the `running` dict shared with `Tick` (and the same `Notes`), the asyncio task of each worker, the cancelled worker (journal `stopped`, `recover` on shutdown, workspace removal when moved), `crashed` for any other exception, `shutdown`, `wait_all` for tests |
| `Orchestrator` | `entrypoints/orchestrator.py` | builds the parts and runs: startup, then tick and sleep until stopped, `Workers.shutdown` in a `finally`, exit when idle. About a hundred lines, no rule |

`Startup` and `RunTask` are tested with the fakes and without a loop
(`tests/component/test_app_startup.py`, `tests/component/test_app_run_task.py`); the lifecycle scenarios still run
over the `Orchestrator`.

## The architecture test

`tests/checks/test_architecture.py` reads sources with `ast` and never imports `samba`. It checks that:

- the domain modules (`DOMAIN_MODULES`, which also holds `domain/ports.py`, `domain/template.py` and
  `domain/prompts.py`) import no I/O module and no adapter;
- every use case module (`APP_MODULES`) imports no adapter and none of `os`, `subprocess`,
  `pathlib`, `logging`, `asyncio` (use cases await ports and never touch the loop; `Running.task`
  in `app/tick.py` is a `Cancellable` Protocol, which an asyncio task satisfies);
- no domain or app module imports `pathlib` or `yaml`, `domain/settings.py` has no `Layout` and no
  `repo`, `samba_dir` or `workspaces_root` field, and `config.py` no longer exists at the root
  (`adapters/workflow_file.py` and `domain/settings.py` do);
- every `.py` under `domain/` and `app/` is listed in one of the two lists, so a new module cannot
  escape the checks;
- the root of `src/samba/` holds only `__init__.py`, `__main__.py`, `bootstrap.py` and the packages
  `domain`, `app`, `adapters` and `entrypoints`; `cli.py`, `views.py`, `orchestrator.py` and
  `compose.py` no longer exist there, and every `.py` under `entrypoints/` (`__init__.py`, `cli.py`,
  `table.py`, `orchestrator.py`, `workers.py`) is accounted for;
- no module of `domain/`, `app/` or `adapters/` imports `samba.bootstrap` or `samba.entrypoints`;
- `entrypoints/orchestrator.py` and `entrypoints/workers.py` import no adapter, `workspace`,
  `merge`, `lock`, `logging`, `os`, `subprocess` or `pathlib`;
- `entrypoints/orchestrator.py` is at most about 110 lines and imports none of `domain.policy`,
  `domain.prompts`, `domain.template` (it holds no rule);
- the orchestrator, the workers, the use cases and the domain make no direct `time.time`, `time.monotonic`,
  `datetime.now` or `uuid` call, and the code of `domain/` and `app/` (comments stripped) matches
  none of `Path`, `mtime`, `sidecar`, `front matter`;
- only `bootstrap.py` constructs `MarkdownTasks`, no module of `entrypoints/` imports an
  adapter, `entrypoints/cli.py` holds no rule (`human_events`, `merge.`, `TaskId.slug`, `Machine`), and
  `tests/component/test_scenarios.py` imports no adapter;
- only `adapters/claude_cli.py` mentions Claude's JSON fields, and `samba.tasks` does not exist;
- each test folder keeps its import rule (see Test levels): `tests/unit` imports no adapter, no
  module of `tests/fakes/` and no test or legacy support module; `tests/component` imports no
  adapter (fakes allowed); `tests/integration` imports neither `samba.entrypoints` nor
  `samba.bootstrap`; `tests/e2e` imports no `samba`;
- every test file sits in `unit`, `component`, `integration`, `e2e`, `checks` or `legacy`, the root of
  `tests/` holds no `.py`, `tests/fakes/` holds no test, and no two test files share a basename
  (the folders have no `__init__.py`, so pytest would fail with an import mismatch).

The scanners are themselves tested against temporary modules that break each rule.

## Test levels

ADR 0016 divides the tests in four levels, one folder each under `tests/`: `unit` (one pure piece
of the domain), `component` (use cases and parts over the in-memory fakes), `integration` (one real
adapter against git, files or a shell) and `e2e` (the `samba` command as a subprocess). The two
widest levels stay few and a test goes to the lowest level that can show the behavior. Next to
them: `checks/` (guards such as the architecture test and the spec drift check), `fakes/` (the
fakes of the ports and `fake_claude.py`, put on the pytest `pythonpath` so tests import them by
module name) and `legacy/`. `legacy/` is temporary: the old subprocess suite, moved there intact as
the behavior inventory while the new levels are written, and removed when the chain of tasks that
rewrites the suite ends; it is not extended. The fast loop is
`uv run pytest -q tests/unit tests/component`; the full run takes about 4.5 minutes, mostly legacy.

## Scenarios

The rules of the core are tested with data (ADR 0012). `tests/component/scenarios/*.json` holds the cases and
`tests/component/test_scenarios.py` loads and runs them in-process, one pytest case per scenario. The runner
imports the domain and the use cases only: never an adapter (the in-memory `tests/fakes/fake_tasks.py`
stands in for the store), so the fake clock lives in the test file. A rewrite in another language
can reuse the JSON unchanged.

Each file is `{"kind": "<kind>", "scenarios": [{"name": "...", ...}]}`. The `task` key holds the
fields of the `Task` aggregate as plain JSON, named as in the dataclass (it was `sidecar` before
the aggregate); omitted fields take their default, and a question record may name only the fields
it needs.

| Kind | Scenario fields | Checks |
|---|---|---|
| `transition` | `given`: `state`, `task` (fields), `deps_met` (default true), `plan_required` (default false); `event`; `actor`; optional `ctx` (`error`, `delay`), `clock_time`, `hand_move_to`; `expect` | The row is picked as `Machine.fire` picks it (`find_row`, first row for the event and state whose guards hold) and must belong to `actor`. `expect` is `{"fires": false}` or `{"fires": true, "state", "guards", "effects", "task"}`: destination, the row's guard names and effect names, and the task fields the effects changed (exactly those; `status` and `queued_at` are not compared). `hand_move_to` picks the row by `human_row` instead, for rows `fire` cannot reach. |
| `human_row` | `src`, `dst`, `task`, `expect` | The event name of the human row for a hand move, or `null`. |
| `human_events` | `state`, `task`, `expect` | The ordered human event names legal in the state. |
| `deps` | `tasks` (`id`, `status`, `depends_on`), `task`, `expect` | `evaluate` on a snapshot of `tasks` gives `kind`, `waiting` and `unknown`. |
| `retry_policy` | `settings` (`max_attempts`, `base_s`, `max_backoff_s`), `failed_before`, `expect` | `RetryPolicy.decide`: `{"action": "retry", "attempts", "delay"}` or `{"action": "give_up", "attempts"}`. |
| `budget` | `cap` (or null), `spent`, `expect` | `left` and `exceeded` of a `Budget`. |
| `turn_decision` | `stage`, `validate`, optional `budget` (`cap`, `spent`), `report` (`AgentReport` fields), `expect` | `decide_after_turn`: `action` (`fail`, `finish`, `run_validation`, `record_questions`, `continue`) with its `error`, or `event`, `what`, `summary`. |
| `turn_rule` | `rule` (`session_reset`, `budget_gate`, `exhausted`, `reflect`) and its inputs, `expect` | The small rules: session reset on a missing session, the pre-turn budget gate, `max_turns` exhaustion, the give-up reflection. |
| `turn_flow` | `setup` (stage, prompts, limits), `task`, `reports` (scripted `AgentRunner`), `validate` (results, a scripted `FakeValidator`), `expect` | `TurnFlow.run` end to end with the fake runner and `FakeTasks`: the result, the requests sent, plan and assumptions set, questions recorded, validation calls and task fields. |
| `lifecycle` | `config` (`require_plan`, `validate`, `max_turns`), `status` (initial), `reports`, `validator` (`[ok, output]` per call), optional `merge`, `steps`, `expect` | The whole life of a task over fakes only (`FakeTasks`, `FakeAgentRunner`, `FakeVcs`, `FakeValidator`, `FakeLock`, `FakeJournal`): `Orchestrator.startup`, then `tick` and await the workers (no poll sleep). A step is `tick`, `plan_accept` (`ChangeState`), `answer` (`AnswerQuestion`) or `work_accept` (`AcceptWork`), each with the status expected after it. `expect`: the `Vcs` call names, the validator calls (location, log name), the workspaces left, the journal events as an ordered subsequence, `## Log` fragments, and optionally text in a sent prompt. A test asserts all scenarios run in under a second. |

Coverage rule: a test fails when a row of the transition table, keyed by `(src, event, guard,
dst)`, is picked by no `transition` scenario that fires. Adding a row therefore needs a scenario.

The lifecycle scenarios are the end-to-end check of the layering: they run the orchestrator and the
use cases with no adapter at all.
