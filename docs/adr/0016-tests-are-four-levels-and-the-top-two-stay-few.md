---
status: accepted
date: 2026-11-12
supersedes: [9]
---

# 0016: Tests are divided in four levels, and the two widest ones stay few

## Context

ADR 0009 made the main test suite black-box: it runs the `samba` command as a subprocess and never
imports the package, so it survives the rewrite of ADR 0010. ADR 0012 added scenario data for the
rules of the core, and said that if the review preferred it, a later ADR should supersede 0009 and
restate the black-box rule.

Since ADR 0011 the use cases run in-process over fakes, and the numbers show what keeping the
black-box suite as the default home of every test costs:

- 734 tests. About 410 run in-process and take a few seconds. The other 325 or so, in 14 files,
  start the real command, and the whole suite takes about 4.5 minutes. A command line start costs
  about 0.22 s since ADR 0014, and each `work accept` validation takes minutes.
- Many of those tests check a state change, an id resolution or an answered question, which a use
  case test shows with no process, no argument parsing and no timing.
- The tests have no stated shape: a reader cannot tell what a test is allowed to touch, and a new
  test goes wherever the nearest example is.

The reason for ADR 0009 is a portable contract for a rewrite. That contract is the spec, the
scenario files and a small acceptance suite. It does not need every case to cross a process.

## Decision

- Tests are divided in four levels, each with its own folder under `tests/`, and each level has an
  import rule that the architecture test enforces:
  - **unit** (`tests/unit/`): one pure thing, such as the transition table, the retry policy, the
    task aggregate, template rendering, id resolution, a parser. No port, no fake, no file, no
    process. It imports the domain, and the use case modules only for pure helpers.
  - **component** (`tests/component/`): one use case or one application part (a use case, `Tick`,
    `RunTask`, `Startup`, the machine) in-process, with fakes for its ports. Scenario data
    (ADR 0012) and the lifecycle scenario that chains the parts over fakes live here. It imports the
    domain, the use cases and the fakes, never an adapter.
  - **integration** (`tests/integration/`): one real adapter against the real thing it adapts,
    through its port: the markdown task store on a temporary directory, git on a temporary
    repository, the shell validator, the `claude` runner against the scripted fake `claude`
    process, the lock, the journal, the terminal on a pseudo terminal, the interactive session. It
    imports an adapter and the domain, never an entry point or the bootstrap. The contract of a
    port is written once as a set of cases and run against both the fake and the real adapter, so
    the fakes used by the component level cannot drift from the real behavior.
  - **end-to-end** (`tests/e2e/`): the real `samba` command as a subprocess, with the mechanics of
    ADR 0009 (`SAMBA_CMD`, assertions on files, exit codes, output and the calls recorded by the fake
    `claude`, never imports the package).
- The shape is a pyramid. Most tests are unit and component tests. Integration and end-to-end tests
  are few, and each one must be able to say what only its level shows:
  - an integration test shows what a port's real adapter does that a fake cannot: files on disk,
    git behavior, process handling, a terminal. There is one case per behavior of the port, not one
    per use case;
  - an end-to-end test shows what only the whole process shows: command names, arguments and
    options, exit codes, what goes to stdout and to stderr, help and completion, signals, and a
    handful of journeys (a task from `task new` to `work accept` with the fake `claude`).
- A new test goes to the lowest level that can show the behavior. A test that crosses a level
  without needing it is moved down.
- The existing tests are sorted into the levels in a chain of tasks, one file or family at a time.
  Each task lists, for every test it moves or deletes, the test that now covers the same behavior.
- The portable contract for a rewrite is the spec, the scenario files and the end-to-end suite.
  The unit, component and integration tests protect this implementation and are rewritten with it.
- The speed of the fast loop is a design constraint. `pytest tests/unit tests/component` runs in
  seconds and is what an agent runs while working. The full run, used by validation, stays small
  enough that its documented duration (`CLAUDE.md`, the `architecture` chapter) is kept true.

## Consequences

- The self-verification loop of an agent drops from minutes to seconds, and validation shrinks to
  the in-process levels plus few slow tests. The measured result is reported when the migration
  ends.
- This supersedes ADR 0009. Its black-box mechanics survive in the end-to-end level. Its claim that
  the main suite is black-box, and that internal helpers get no tests of their own, does not.
  ADR 0012's rule that a rule gets a scenario first and an edge gets an end-to-end test first stays,
  with "edge" now meaning what only the whole process shows.
- Fakes stay honest through the shared port contract cases. That is more test code per port, but it
  replaces the end-to-end suite as the guard against drift.
- The migration is judged by the mapping from removed tests to the tests that cover the same
  behavior, not by the old test staying green.
- The first task updates the test conventions and the stale timing in `CLAUDE.md`, and adds the
  folder rules to `tests/test_architecture.py`. Running the suite in parallel is a separate tooling
  choice and is not decided here.
