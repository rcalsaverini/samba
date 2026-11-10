# Architecture

Samba is layered so the rules of the core can be tested without a clock, a disk, a subprocess or a
network (ADR 0011, ADR 0012). The refactor that gets there runs in a chain of tasks. This chapter
describes the target and says where each piece lives today.

## Layers

| Layer | Target location | Holds |
|---|---|---|
| Domain | `src/samba/domain/` | Pure rules and data: states, question records, the transition table, dependency evaluation. No I/O. (`template.py` and `prompts.py` are pure and follow later.) |
| Use cases | `src/samba/app/` | The operations of the orchestrator and the commands, written against ports. |
| Ports | `src/samba/ports.py` | Protocols for everything the core needs from the outside world. |
| Adapters | `src/samba/adapters/` | Implementations of the ports: system clock, files, git, the `claude` runner, the terminal. |

## Dependency rule

Dependencies point inward only: adapters depend on ports and the domain, use cases depend on the
domain and ports, the domain depends on nothing outside itself. A domain module imports none of
`os`, `time`, `datetime`, `uuid`, `subprocess`, `asyncio`, `logging`, `pathlib`, and no adapter.
The composition root (the CLI) is the only place that builds adapters and hands them to use cases.
Until it exists (a later task of the chain), constructors take optional ports and default to the
system adapters.

## Ports

| Port | Methods | Adapter |
|---|---|---|
| `Clock` | `time()` wall seconds, `monotonic()`, `iso_seconds()` local ISO 8601 to the second, `log_stamp()` local `YYYY-MM-DD HH:MM` | `SystemClock` in `adapters/system.py` |
| `IdGenerator` | `new_session_id()` | `UuidGenerator` in `adapters/system.py` |
| `AgentRunner` | `run(AgentRequest) -> AgentReport`, `ready() -> Readiness` | `ClaudeCliRunner` in `adapters/claude_cli.py` |
| `Terminal` | `is_interactive()`, `ask(prompt)` (raises `EOFError` at end of input), `read_block(prompt)`, `edit(initial) -> EditResult` (the text, or an error message) | `StdTerminal` in `adapters/terminal.py` |
| `RepoLock` | `acquire(blocking) -> context manager yielding held` | `FileRepoLock` in `adapters/repo_lock.py` (wraps `lock.repo_lock`) |
| `Tasks` | `get(id)`, `list(status)`, `ids(status?)`, `create(task)`, `save(task) -> bool`, `observe_moves()`, `accept_move(move)`, `revert_move(move)`, `rejected_names(status)`, `location(id)`, `prepare()` | `MarkdownTasks` in `adapters/markdown_tasks.py`; the in-memory `FakeTasks` for tests is `tests/fake_tasks.py` |

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
optional `agent` and defaults to `ClaudeCliRunner`, like the clock. The fake runner for tests is
`tests/fake_agent.py`.

The clock is threaded through `Machine`, the transition effects (`not_before`,
`first_dispatched_at`, `queued_at`), the question helpers (`add_questions`, `answer_question`,
`dismiss_open`), `log_line`, `MarkdownTasks` and the orchestrator. Timestamps written to task
files and sidecars are formatted by the clock (`iso_seconds`, `log_stamp`), because the domain may
not import `datetime`. In the domain the clock is always a required parameter. Only the
adapter-side constructors (`MarkdownTasks` takes one, `Orchestrator`) default to `SystemClock`,
until the composition root exists.

## Where each concern lives today

Moved into `domain/`: states and causes (`states.py`), question records (`questions.py`), the
`Task` aggregate and `TaskId`, the transition table, effects, `find_row`, `human_row`,
`human_events` and the markdown renderer (`transitions.py`), and dependency evaluation
(`deps.py`). The effects, `apply_row` and the row helpers work on a `Task`; `apply_row` sets
`status`, stamps `queued_at` when the destination is a todo status (the dispatch order key) and
tells whether the questions changed. `evaluate` takes a snapshot (`TaskRef` per task id, an absent
id is unknown); `deps_snapshot(task, get)` in `deps.py` builds it from the task and its
`depends_on` closure. `Machine` (`fire`, `observe`) is the use case `app/machine.py`: it loads the
task through the `Tasks` port, applies a row, adds the log line and saves once. The orchestrator
holds a `Tasks` (default `MarkdownTasks`) and no sidecar store.

Policy is in `domain/policy.py`: `Budget` (cap, spent, `left`, `exceeded`), `RetryPolicy` (`decide`
gives `Retry` with the delay or `GiveUp`), `should_reflect` (the give-up turn) and
`decide_after_turn`, which turns an `AgentReport` into one action: `Fail`, `Finish`,
`RunValidation`, `RecordQuestions` or `Continue`. A failure wins over the budget, the budget over
the outcome. The turn flow shared by planning and work is the use case `app/turn.py` (`TurnFlow`):
it drives the `AgentRunner` port, executes the action and returns `Finish` or `Fail` to the
orchestrator, which fires the transition. It mutates the `Task` it is given (plan, assumptions,
questions, denial log lines, counters) and calls `Tasks.save` after each step.

Configuration (`config.py`) is a composite of frozen parts, so each consumer takes only the part it
needs: `Policy` (turns, retries, cost cap, `reflect_on_give_up`, `require_plan`, concurrency,
polling), `AgentSettings` (the `claude` command, permissions, timeouts and the planning model and
allow list; taken by `adapters/claude_cli.py`), `Layout` (repo, Samba directory, workspaces root,
base branch), `Prompts` (the body template and the overrides), `Validation` (command, timeout, tail
lines, shell) and `Hooks` (`after_create`, timeout). `Config` holds one of each plus `warnings`;
`load_config` builds it. `Workspaces` takes `Layout`, `Hooks` and the shell. `DEFAULT_ALLOW` and
`DEFAULT_PLANNING_ALLOW` stay in `config.py`.

Not yet behind a port, and not yet moved:

- Subprocess helpers: `proc.py` (the Claude runner moved to `adapters/claude_cli.py`).
- Git: `workspace.py` and `merge.py`.
- Repo lock: `lock.py` (monotonic deadline and sleep).
- Terminal output: `cli.py` and `views.py` (`views.py` still reads `time.time`). Both use the
  `Tasks` port; `cli.py` still builds `MarkdownTasks` itself until the composition root exists.
- The test-only `SAMBA_DEBUG_FIRE_DELAY` sleep is in `MarkdownTasks.save`, between the rename and
  the sidecar write.

More ports and module moves arrive in later tasks of the chain.

## Scenarios

The rules of the core are tested with data (ADR 0012). `tests/scenarios/*.json` holds the cases and
`tests/test_scenarios.py` loads and runs them in-process, one pytest case per scenario. The runner
imports the domain and the use cases only: never an adapter (the in-memory `tests/fake_tasks.py`
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
| `turn_flow` | `setup` (stage, prompts, limits), `task`, `reports` (scripted `AgentRunner`), `validate` (results), `expect` | `TurnFlow.run` end to end with the fake runner and `FakeTasks`: the result, the requests sent, plan and assumptions set, questions recorded, validation calls and task fields. |

Coverage rule: a test fails when a row of the transition table, keyed by `(src, event, guard,
dst)`, is picked by no `transition` scenario that fires. Adding a row therefore needs a scenario.

## Architecture test

`tests/test_architecture.py` reads source files with `ast` and never imports `samba`. It asserts
that the modules in its `DOMAIN_MODULES` list import none of the forbidden modules and no adapter,
that the `app/` modules (`turn.py`, `machine.py`) import no adapter, that `orchestrator.py`, the `app/`
modules and the domain modules make no direct `time.time`,
`time.monotonic`, `datetime.now` or `uuid` call, and that the scanner does flag an `adapters` or
`datetime` import in a temporary module. It also asserts that `tests/test_scenarios.py` imports no
adapter, and that no module but `adapters/claude_cli.py` mentions Claude's
JSON fields. The list holds `ports.py`, `template.py`, `prompts.py` and the
modules of `domain/` (including `agent.py`, `policy.py`, `task.py` and `task_id.py`), and grows as
more modules move in. With comments stripped, the code of `domain/` and `app/` must also match none
of `Path`, `mtime`, `sidecar`, `front matter`: storage vocabulary stays in the adapter (the check is
itself tested against a temporary module). Finally, `samba.tasks` must not exist, and `orchestrator.py`
and `cli.py` import `samba.adapters.markdown_tasks` and no folder helper.
