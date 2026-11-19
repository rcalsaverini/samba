---
status: proposed
date: 2026-11-13
supersedes: []
---

# 0023: Each artifact kind is an aggregate with its own state machine

## Context

The principles chapter names `Task` as the one aggregate. ADR 0021 adds backlog items, Epics and
TEPs, each with its own author, approver and states. The core today is shaped for one kind: `State`
is a closed set of ten strings, the transition table is one table, `Tick` iterates `plan-todo` and
`work-todo`, the request to the agent has a closed `plan` or `work` kind, and the store port mixes
repository operations with hand-move mechanics (ADR 0018).

Some rules of the new workflow span artifacts: a task waits when its TEP is being amended, a wave
is ready for review when all its tasks are merged, an Epic is done when all its waves are approved.
Written as "when X changes, update every Y", they would save several aggregates in one operation,
and a crash halfway would leave them inconsistent. Principle 5 gives no way to do that.

## Decision

- A backlog item, an Epic, a TEP and a task are each an aggregate with its own id, its own states
  and its own transition table. The table is plain data of the same shape as today's, one per kind.
  The consistency boundary is one artifact.
- A rule that spans artifacts is a use case that reads several aggregates and changes at most one,
  or it is derived. Derived means a pure function of values the use case hands the domain, like
  `deps_met`: a task is held while its TEP is in `amend`, a wave is in review when its tasks are
  merged, an Epic is done when its waves are approved. The result is computed on each tick and is
  never written into the other artifacts.
- No operation needs two saves to be atomic. When an operation changes several artifacts, each step
  is safe to repeat, and the tick re-derives what is missing.
- The store is a repository per kind (`get`, `list`, `create`, `save`) of the same shape. How the
  folders of ADR 0005 serve several kinds is the adapter's business. Separating what is not
  repository work (hand-move observation, readiness, where an agent finds its file) is already under
  way after ADR 0018 and is not decided here.

## Consequences

- The principles chapter no longer calls `Task` the one aggregate: it says `Task` was the first. The
  other principles stand.
- `Machine`, `Tick`, the transition table and the agent request generalize over the kind. The
  constants `plan-todo` and `work-todo` stop being known to the loop.
- Adoption is incremental (ADR 0021). The first new kind should be the backlog item: no worktree, no
  agent run, a few states. It exercises the generalization at the lowest cost.
- Scenario data (ADR 0012) gains a transition file per kind, so the rules of each machine are stated
  outside the code (principle 9).
- Open: one generic `Machine` parameterized by the kind's table, or one per kind. The task that
  implements the second kind decides.
