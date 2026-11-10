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

The clock is threaded through `Machine`, the transition effects (`not_before`,
`first_dispatched_at`), the question helpers (`add_questions`, `answer_question`,
`dismiss_open`), `log_line`, `SidecarStore.save` and the orchestrator. Timestamps written to task
files and sidecars are formatted by the clock (`iso_seconds`, `log_stamp`), because the domain may
not import `datetime`. In the domain the clock is always a required parameter. Only the
adapter-side constructors (`SidecarStore`, `Orchestrator`) still default to `SystemClock`, until the
composition root exists.

## Where each concern lives today

Moved into `domain/`: states and causes (`states.py`), question records (`questions.py`), the
`Sidecar` dataclass (`sidecar.py`, an interim home), the transition table, effects, `find_row`,
`human_row`, `human_events` and the markdown renderer (`transitions.py`), and dependency
evaluation (`deps.py`). `evaluate` takes a snapshot (`TaskRef` per task id, an absent id is
unknown); `TaskStore.deps_snapshot` builds it from the task and its `depends_on` closure.
`samba/transitions.py` keeps only `Machine` (`fire`, `observe`), the file IO around the table.

Not yet behind a port, and not yet moved:

- Task store and sidecars: `tasks.py`.
- Claude runner: `claude.py`; subprocess helpers: `proc.py`.
- Git: `workspace.py` and `merge.py`.
- Repo lock: `lock.py` (monotonic deadline and sleep).
- Terminal output: `cli.py` and `views.py` (`views.py` still reads `time.time`).
- `Machine.fire` keeps the `time.sleep` of the test-only `SAMBA_DEBUG_FIRE_DELAY` knob.

More ports and module moves arrive in later tasks of the chain.

## Scenarios

The rules of the core are tested with data (ADR 0012). `tests/scenarios/*.json` holds the cases and
`tests/test_scenarios.py` loads and runs them in-process, one pytest case per scenario. The runner
imports the domain (and later the use cases) only: never an adapter and never `samba.tasks`, so the
fake clock lives in the test file. A rewrite in another language can reuse the JSON unchanged.

Each file is `{"kind": "<kind>", "scenarios": [{"name": "...", ...}]}`. Sidecar fields are plain
JSON named as in the `Sidecar` dataclass; omitted fields take their default.

| Kind | Scenario fields | Checks |
|---|---|---|
| `transition` | `given`: `state`, `sidecar` (fields), `deps_met` (default true), `plan_required` (default false); `event`; `actor`; optional `ctx` (`error`, `delay`), `clock_time`, `hand_move_to`; `expect` | The row is picked as `Machine.fire` picks it (`find_row`, first row for the event and state whose guards hold) and must belong to `actor`. `expect` is `{"fires": false}` or `{"fires": true, "state", "guards", "effects", "sidecar"}`: destination, the row's guard names and effect names, and the sidecar fields the effects changed (exactly those). `hand_move_to` picks the row by `human_row` instead, for rows `fire` cannot reach. |
| `human_row` | `src`, `dst`, `sidecar`, `expect` | The event name of the human row for a hand move, or `null`. |
| `human_events` | `state`, `sidecar`, `expect` | The ordered human event names legal in the state. |
| `deps` | `tasks` (`id`, `status`, `depends_on`), `task`, `expect` | `evaluate` on a snapshot of `tasks` gives `kind`, `waiting` and `unknown`. |

Coverage rule: a test fails when a row of the transition table, keyed by `(src, event, guard,
dst)`, is picked by no `transition` scenario that fires. Adding a row therefore needs a scenario.

## Architecture test

`tests/test_architecture.py` reads source files with `ast` and never imports `samba`. It asserts
that the modules in its `DOMAIN_MODULES` list import none of the forbidden modules and no adapter,
that `orchestrator.py`, `transitions.py` and the domain modules make no direct `time.time`,
`time.monotonic`, `datetime.now` or `uuid` call, and that the scanner does flag an `adapters` or
`datetime` import in a temporary module. It also asserts that `tests/test_scenarios.py` imports no
adapter and not `samba.tasks`. The list holds `ports.py`, `template.py`, `prompts.py` and the
modules of `domain/`, and grows as more modules move in.
