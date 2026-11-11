---
status: accepted
date: 2026-11-11
supersedes: []
---

# 0015: The orchestrator is a set of named parts and a thin loop

## Context

`orchestrator.py` is 314 lines and one class that does four unrelated jobs:

1. Startup checks: the store, the repository, the `claude` login, config warnings and recovery of
   tasks that were running.
2. The poll loop.
3. The lifecycle of workers: spawn, track, cancel and shut down the asyncio tasks.
4. The rules of one task run: build the prompts and variables, run the turn flow, finish the task,
   and decide whether to retry, reflect or give up.

ADR 0011 moved the tick (`Tick`), the turn loop (`TurnFlow`) and the transition (`Machine`) out
into `app/`, but jobs 1 and 4 stayed, and so did the asyncio details of job 3. The commands got a
clean seam and the orchestrator did not. The per-task rules can only be exercised through the whole
class.

## Decision

- Each job becomes its own part with one reason to change:
  - `Startup` (in `app/`): the checks and the recovery of job 1, over ports.
  - `Tick` (already in `app/`): what to dispatch and what to clean up.
  - `RunTask` (in `app/`): the run of one task, from ensuring the workspace to finishing it. It uses
    a prompt and turn-setup builder and a finish-or-fail rule, each in its own module in `app/`.
    The retry, reflection and give-up decisions stay pure functions of the domain policy.
  - `Workers` (in `entrypoints/`): the asyncio supervision of job 3, including what happens to a
    task whose worker is cancelled. It is the only part that needs `asyncio` tasks.
- `Orchestrator` (in `entrypoints/`) is the one place that knows how the parts fit: startup, then
  tick and sleep until stopped. It holds no rule and is about a hundred lines. It is a driving
  adapter driven by the clock, like the command line is driven by a person.
- Where the loop runs is replaceable at one point only. A different runtime (threads, a queue
  consumer, remote workers) reimplements `Workers` and `Orchestrator` against the same parts. No
  extra port for it is added now, because the swap points that matter (tasks, agent, git,
  validation, lock, journal) are already ports.

## Consequences

- The per-task rules and the startup checks become testable with the existing fakes and the
  scenario runner (ADR 0012) without starting a loop. The lifecycle scenarios keep passing.
- `tests/test_scenarios.py` and the architecture test follow the files to their new homes.
- Depends on the layout change that creates the `entrypoints/` package (recorded in the
  `architecture` chapter, not in an ADR), which should land first.
- Behavior is unchanged: prompts, retries, recovery, shutdown and the exit when idle stay as
  specified in the `orchestrator` chapter.
