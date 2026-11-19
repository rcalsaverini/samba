---
status: proposed
date: 2026-11-13
supersedes: []
---

# 0021: Work is organized as backlog items, epics, technical execution plans and tasks

## Context

Today one task file is the request, the plan and the unit of execution. That is why plans cannot
be reviewed apart from the work, why nits and ideas have nowhere to go, and why a task can be as
large as a feature. These are different things with different authors, approvers and lifetimes.

## Decision

Samba distinguishes these artifacts. Each is a markdown file, and its state is the folder it sits
in (ADR 0005).

- **Backlog item**: an intent, one or two lines: what and why, and where it came from. States:
  `open`, `promoted`, `dropped`. No plan, no worktree. Sources are exploration, review nits,
  ADR candidates, and the Owner.
- **ADR**: a rule about how the software is built (ADR 0001). It constrains designs and plans. It
  is not a goal and not a spec.
- **Spec**: what the software does today (`docs/spec/`). A change of behavior edits the spec in the
  same change.
- **Epic**: a goal to reach, larger than one task. The Owner approves it. It says what and why, what
  is out of scope and which paths were rejected.
- **Technical execution plan (TEP)**: how to reach an Epic. It fixes interfaces, order and
  invariants across tasks. It is a reference for tasks, not the body of one.
- **Task**: one unit of work with one purpose, small, self-contained and independent. It results in
  one pull request of a few commits and a small diff, and it leaves the build green. It carries its
  own concrete steps, file list and tests, and points at the TEP section it implements.
- **Bugfix**: a task created straight from a backlog item, with no Epic and no TEP.

Each of these is its own aggregate with its own states (ADR 0023).

The chain is backlog item, then Epic, then TEP, then tasks. A backlog item can instead become an
ADR or a bugfix. Exploration (ADR 0002) is where items are refined and promoted.

## Consequences

- The plan phase of today's task becomes the TEP step upstream of the tasks. The work states stay on
  the task.
- Nits and ADR candidates from reviews become backlog items. The Owner decides which ones become
  work.
- Smaller tasks mean more tasks and more dependencies between them. How reviews and merges are
  grouped is not decided here. It is a later ADR, after Epics and TEPs have run.
- Today's task file keeps working. The new artifacts are adopted one at a time, and nothing here
  requires them all at once.
- Open: a better name than "TEP", and whether Epics are one file or a folder holding their TEP and
  tasks.
