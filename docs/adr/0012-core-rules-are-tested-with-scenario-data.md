---
status: accepted
date: 2026-11-10
supersedes: []
---

# 0012: The rules of the core are tested with scenario data

## Context

ADR 0009 makes the main test suite black-box: it runs the `samba` command as a subprocess and
never imports the package, so the suite survives a rewrite. That suite is also the only way to test
a rule today, so even a pure decision (is this the last retry, is the budget spent, is this
transition legal) costs a real process, a real repository and a fake `claude`. It runs for about
25 seconds, it has produced flaky timing tests, and it is a slow loop for an agent checking its own
work.

ADR 0011 makes the domain and the use cases free of IO, so they can now be exercised in-process.
Plain unit tests written in Python would be fast, but they would be thrown away with the Python,
which is the reason ADR 0009 exists.

## Decision

- The rules of the core are described as **scenarios**: language-neutral data files (JSON) under
  `tests/scenarios/`. A scenario states a starting situation (a task and its counters, an event or
  an agent report, the policy settings) and the expected result (the new state, the effects, the
  decision taken).
- A small **runner** in Python loads the scenarios and runs them in-process against the domain and
  the use cases, with in-memory fakes for the ports. It is the one kind of test allowed to import
  the `samba` package, and it may import the domain and the use cases only, never an adapter.
- The scenarios hold the rules and the runner holds only plumbing. A rewrite brings its own small
  runner and executes the same files.
- The black-box suite of ADR 0009 stays as the acceptance suite. It keeps testing that the
  adapters, the command line and the core work together, through the real command. It no longer
  carries every rule.
- New rules get a scenario first when they live in the core, and a black-box test first when they
  live at an edge (command line, files, processes).

## Consequences

- Rules are checked in milliseconds, with no processes and no timing, which tightens the
  self-verification loop for agents and removes a class of flaky tests.
- The behavior contract for a rewrite grows to three parts: the spec, the black-box suite and the
  scenario files.
- ADR 0009 stays accepted and keeps governing the acceptance suite. This ADR adds a second kind of
  test next to it. Its consequence that "internal helpers get no unit tests" no longer holds for the
  core. If the review prefers that to be explicit, this ADR should supersede 0009 and restate the
  black-box rule.
- Scenarios are less flexible than code: a case that needs logic is a sign that logic belongs in
  the core, or that the case is an acceptance test.
- Fakes for the ports are a second implementation to keep faithful, so they stay small and are
  checked by the acceptance suite.
