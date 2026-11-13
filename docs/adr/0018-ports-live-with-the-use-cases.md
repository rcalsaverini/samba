---
status: accepted
date: 2026-11-13
supersedes: []
---

# 0018: The ports live with the use cases

## Context

Every port sits in `domain/ports.py`. The `architecture` chapter gives the reason: the domain's
`Task` depends on the clock port. ADR 0017 removes that reason: nothing in the domain calls a port.

ADR 0011 says a port is owned by the layer that uses it. The principle behind that sentence is
that a port is the interface the inside declares so that the outside can be injected into it, and
a layer declares a port when its code receives the adapter and calls it. Who receives each port
today: the task store goes into `Machine`, `Tick`, `Startup`, `ChangeState` and the queries; the
clock into `Machine`, `AnswerQuestion`, `CreateTask`, `TurnFlow`, `Tick` and `Workers`; the agent
runner, git, the validator, the journal, the terminal, the lock, the ADR files, the interactive
session and the id generator into use cases and entry points. Under ADR 0017 nothing under
`domain/` has anything injected: it takes values as arguments. So the use cases declare every
port, and a Protocol filed in a package where no code calls it is not that package's declaration
of a need but a type definition in the wrong folder.

"Inside" is not "domain". In the hexagon the inside is the domain and the use cases together, and
the ports are the edge of that hexagon. After ADR 0017 the domain is the part of the inside with
no edge, and the use cases are the ring that touches the adapters. The domain still owns the
vocabulary (`Task`, `TaskId`, `State`, `Now`, `AgentReport`, `ValidationResult`, `LaunchSpec`),
and every port is written over it; written in the domain's vocabulary is not the same as declared
by the domain. Clean Architecture's gateways are typed over the entities and sit at the use-case
ring, which is this arrangement.

The present layout also misleads: when the aggregate's module imports from a file that also
declares "merge a git branch", the file layout says the aggregate depends on git, and a reader has
to open the file to learn it does not.

DDD convention keeps the repository interface in the domain model because aggregates and domain
services call it. There the domain does declare it, and the same principle puts it in the domain.
Under ADR 0017 nothing in the domain calls anything, so that premise is gone. Samba's store port
confirms it by content: of its eleven methods only `get`, `list`, `ids`, `create` and `save`
are repository operations; `prepare`, `observe_moves`, `accept_move`, `revert_move`,
`rejected_names` and `location` are application mechanics (store readiness, hand moves, where
the agent finds its file). It is a use-case port whoever calls it.

## Decision

- The ports live with the use cases, in `app/ports.py`, and `domain/ports.py` is removed.
- They stay Protocols written over domain types (`Task`, `TaskId`, `State`, `Now`, `AgentRequest`,
  `AgentReport`, `ValidationResult`, `LaunchSpec`), with their value types and errors beside them
  (`Workspace`, `MergeAttempt`, `CommitResult`, `EditResult`, `AdrInfo`, `StoreError`,
  `TaskExists`, `WorkspaceError`, `AdrError`, `LaunchError`).
- The dependency rule gains one edge and one prohibition. An adapter implements ports, so it may
  import `app/ports.py` and nothing else in `app/`. The domain imports nothing from `app/`. Entry
  points and `bootstrap` import the ports as they import the use cases. The architecture test
  enforces all three.
- Considered and not chosen: keeping the task store and the clock in the domain by the DDD
  convention. It leaves a ports module in a package where nothing uses it, keeps the two-way
  dependency between the aggregate and a file typed over it, and needs a rule with an exception.
  A separate top-level `ports` package was also rejected: the root holds four packages, and the
  ports are the boundary of the use-case layer, not a layer of their own.

## Consequences

- Every importer of `samba.domain.ports` changes one import line: the use cases, the adapters, the
  entry points, `bootstrap`, the fakes and the tests. No behavior changes.
- The `TYPE_CHECKING` guard goes: `app/ports.py` imports domain types plainly and nothing imports it
  back.
- The `architecture` chapter (Layers table, dependency rule, Ports table), the `running-claude`
  chapter and `CLAUDE.md` name `app/ports.py`.
- For the rewrite of ADR 0010 the domain becomes plain data and functions with no trait or
  interface at all; those sit with the use cases, and the adapters depend on that layer.
- Depends on ADR 0017. The two land in one refactor task.
