# Architecture

Samba is layered so the rules of the core can be tested without a clock, a disk, a subprocess or a
network (ADR 0011, ADR 0012). The refactor that gets there runs in a chain of tasks. This chapter
describes the target and says where each piece lives today.

## Layers

| Layer | Target location | Holds |
|---|---|---|
| Domain | `src/samba/domain/` | Pure rules and data: the transition table, dependency evaluation, template rendering. No I/O. |
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
| `Clock` | `time()` wall seconds, `monotonic()` | `SystemClock` in `adapters/system.py` |
| `IdGenerator` | `new_session_id()` | `UuidGenerator` in `adapters/system.py` |

The clock is threaded through `Machine`, the transition effects (`not_before`,
`first_dispatched_at`), the question helpers (`add_questions`, `answer_question`,
`dismiss_open`), `log_line`, `SidecarStore.save` and the orchestrator. Timestamps written to task
files and sidecars are formatted from `Clock.time()`.

## Where each concern lives today

Not yet behind a port, and not yet moved:

- Task store and sidecars: `tasks.py`.
- Claude runner: `claude.py`; subprocess helpers: `proc.py`.
- Git: `workspace.py` and `merge.py`.
- Repo lock: `lock.py` (monotonic deadline and sleep).
- Terminal output: `cli.py` and `views.py` (`views.py` still reads `time.time`).
- `Machine.fire` keeps the `time.sleep` of the test-only `SAMBA_DEBUG_FIRE_DELAY` knob.

More ports and module moves arrive in later tasks of the chain.

## Architecture test

`tests/test_architecture.py` reads source files with `ast` and never imports `samba`. It asserts
that the modules in its `DOMAIN_MODULES` list import none of the forbidden modules and no adapter,
and that `orchestrator.py` and `transitions.py` make no direct `time.time`, `time.monotonic`,
`datetime.now` or `uuid` call. The list starts with the modules already clean (`ports.py`,
`template.py`, `prompts.py`, `deps.py`) and grows as modules move into `domain/`.
