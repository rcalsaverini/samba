---
status: accepted
date: 2026-11-13
supersedes: []
---

# 0017: The domain takes values, never capabilities

## Context

ADR 0011 says the domain performs no IO, reads no clock and generates no ids, and that a port is
owned by the layer that uses it. The code reads the clock from inside the domain anyway:
`Task.create`, the question helpers and the transition effects take a `Clock` port and call it.
Every such call reads the clock once and formats the result (`time`, `iso_seconds`, `log_stamp`);
none waits and none measures a duration.

Hexagonal architecture and DDD allow this. A Protocol declared by the inside is inside code, the
dependency still points inward, and Evans keeps the repository interface in the domain model. So
this is not a breach of the dependency rule. It has costs that showed up all the same:

- A domain function that calls a port is no longer a function of its arguments. Its result depends
  on an effect performed during the call, so a test needs a fake where a literal would do, and a run
  cannot be replayed from its inputs.
- An aggregate is a consistency boundary. A capability that fails halfway through a method leaves a
  half-mutated aggregate with nothing to roll back. The clock cannot fail; the next capability
  someone wants to pass in (an entropy source, a remote lookup) can.
- Because the aggregate imports the ports module, and the ports module declares the task store over
  the aggregate, the two files import each other, hidden behind `TYPE_CHECKING`.
- The question "may an aggregate take a capability, for example a random source with several IO
  backends" came up in design and had no answer in the ADRs.

## Decision

- The domain takes values, never capabilities: a domain function receives the results of IO as
  arguments and performs none, not even through a port it declares.
- Time arrives as a value. A frozen `Now` holds the wall time and the formatted forms the domain
  writes. A use case builds it from the clock port once per operation and passes it down, so every
  timestamp of one operation is the same instant. `monotonic` is for durations in workers and
  adapters and is never a domain value.
- When a rule seems to need a capability during its computation, the boundary between inside and
  outside is drawn in the wrong place, and it is redrawn, trying these in order: pass the values
  (a fixed number of them, known before the rule runs); pass a seed and keep the rule
  deterministic; pass a stream the rule pulls from, typed with the standard library; or make the
  rule a step function or a generator and let the use case run the loop against the port, as
  `decide_after_turn` and `TurnFlow` already do for the agent. If none of these fits, the operation
  is not a domain rule but a use case, and only its pure part stays in the domain.
- Consequently no domain module declares, imports or takes a port. The domain imports the standard
  library and itself. The architecture test enforces this. By the ownership rule of ADR 0011 every
  port then belongs to the use-case layer; where the ports module lives is ADR 0018.
- Fakes of the ports stay, for the use cases. Unit tests of the domain build the values directly
  (ADR 0016: no port, no fake).

## Consequences

- Domain functions are deterministic and replayable, and the scenario files (ADR 0012) can state
  the current time as data instead of configuring a fake.
- The use cases read each port once per operation and hand the values down. That is a little more
  plumbing in `Machine`, `AnswerQuestion`, `CreateTask`, `TurnFlow` and `Tick`.
- Behavior does not change: the same timestamps, log lines and files. Only signatures move.
- ADR 0011 stands and is applied: its "reads no clock" becomes literally true. This ADR does not
  supersede it.
- The refactor is one task, run after the test-levels chain of ADR 0016 finishes, because that
  chain promises not to touch `src/` and migrates the tests this change edits.
