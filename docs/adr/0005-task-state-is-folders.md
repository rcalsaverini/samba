---
status: accepted
date: 2026-11-07
supersedes: []
---

# 0005: Task state is the folder a markdown file sits in, and hand moves are observed

Recorded retroactively on 2026-11-08. The decision dates from the first version of Samba and the
stage-by-status layout of the same day.

## Context

Samba needs a store for tasks and their state that one person can see and steer without tools. The
alternatives were a database, a remote tracker (Jira, Linear, GitHub Issues) and a single status
field in each file.

## Decision

- A task is a markdown file. Its state is the folder it is in: `plan-todo`, `plan-running`,
  `plan-review`, `work-todo`, `work-running`, `work-review`, `question`, `stuck`, `done`, `discarded`.
- The task folders, the worktrees and a few small JSON sidecar files are the whole store. There is no
  database. Restart recovery comes from them.
- The human steers with a file browser and an editor as well as with commands. A move made by hand is
  observed: if the transition table has a row for it, it becomes that event. If not, the file is moved
  back.
- The store sits behind a small interface, so a remote tracker can be added later without changing
  the orchestrator.

## Consequences

- Everything is visible with `ls`, and state survives restarts with no migration story.
- There is no query language and no transactions. Concurrent writers are handled with a repo lock
  (`.samba/lock`), and the single-user assumption does the rest.
- Every hand move has to be classified as legal or illegal, which is why the transition table
  exists (see `docs/spec/states.md`).
