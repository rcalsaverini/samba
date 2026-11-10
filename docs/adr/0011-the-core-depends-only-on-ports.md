---
status: accepted
date: 2026-11-10
supersedes: []
---

# 0011: The domain and the use cases depend only on ports

## Context

Today the rules of Samba (the lifecycle, retries, budgets, what an agent outcome means) are written
in the same functions that rename files, spawn `claude`, run git and print to the terminal. The
orchestrator builds its own stores, the transition machine renames files and sleeps, the CLI holds
use cases, and the agent result type is Claude's raw JSON. As a result:

- A rule cannot be tested without a real process, a real repository and a fake `claude` binary.
- Changing how tasks are stored (a database, a tracker such as Linear) means editing the rules.
  ADR 0005 already says the store sits behind a small interface, but the code does not honor it.
- The expected rewrite (ADR 0010) has no clear seam: the behavior is tangled with Python and with
  the folder layout.

## Decision

- Samba is split in three layers, and dependencies point inward only:
  - **Domain**: the task and its lifecycle, the transition table, questions, dependency rules,
    retry and budget policy, and the decision of what to do after an agent turn. It performs no IO,
    reads no clock, generates no ids, logs nothing and imports no adapter. It knows no folder, path,
    sidecar, process or git concept.
  - **Use cases**: one per thing the human or the orchestrator can do (tick, run a turn, change a
    task's state, accept work, answer a question, create a task). They orchestrate the domain through
    ports.
  - **Adapters**: everything that touches the outside: the task store, the `claude` process, git and
    worktrees, the shell, the lock, the clock, the log, the terminal and the command line.
- A **port** is a small interface (a `Protocol`) written in the vocabulary of the domain, owned by
  the layer that uses it. The adapter adapts to it, never the reverse.
- The task store is the first test of this rule: replacing the markdown folders with a database or a
  remote tracker must change only an adapter. The domain sees a task with a status and never a file.
  How the store keeps it, including folders and hand moves (ADR 0005), is the adapter's business.
- The agent runner is the second: use cases receive a result in domain terms (outcome, summary,
  plan, questions, cost, failure kind), never Claude's JSON.
- Ports are added only where they buy a fast test or a rewrite seam. There is no dependency
  injection framework, no event bus and no abstraction layer for its own sake. A single place, the
  composition root in the command line entry point, builds the adapters and wires them in.

## Consequences

- Core rules become testable in-process with fakes, which gives agents a much faster
  self-verification loop than the current suite of subprocess tests.
- A rewrite reimplements the ports and the adapters against a stated contract, instead of
  untangling behavior from storage.
- There is more indirection and more files than the single-module style of v0. The cost is
  accepted for the core, and it must not spread to code that has no outside world to hide.
- Existing code moves in small steps, each keeping the black-box suite green. Nothing in ADRs 0005
  to 0010 is superseded: the folder store, the headless `claude` process, worktrees and validation
  stay as they are, now as adapters.
- How the core's own rules are tested (fast, in-process, and still portable to a rewrite) is a
  separate decision, and it touches ADR 0009. It gets its own ADR.
