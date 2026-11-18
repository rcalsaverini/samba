---
status: proposed
date: 2026-11-17
supersedes: []
---

# 0026: The markdown of finished tasks is tracked in git

## Context

A commit records what changed. It does not record why: the plan, the questions the agent asked and
the owner's answers, the feedback rounds and the `## Log`. Those live in the task file, and the task
file is the record a future agent or person would need. ADR 0005 already makes the files the state.

Today `.gitignore` excludes all of `.samba/`, and Samba also wrote `/.samba/` into `.git/info/exclude`
at startup. The sidecar JSON next to each task changes on every save, and `runs/`, `samba.log` and
`lock` are local runtime files. Only part of `.samba/` is history.

## Decision

- The markdown of tasks in `.samba/tasks/done/` and `.samba/tasks/discarded/` is tracked in git.
- Everything else under `.samba/` stays untracked: the sidecar JSON, `runs/`, `samba.log`, `lock`,
  `state/`, and the task files of every state that is not finished.
- The rule lives in `.gitignore`. Samba no longer writes a `/.samba/` line into `.git/info/exclude`,
  and startup removes the one older versions wrote, since it would hide the tracked files.
- Before a finished task file is committed, absolute paths are removed from it. Machine-specific
  paths are the first case of a rule that is not yet written: the owner will decide what else belongs
  in a task file and what does not.

## Consequences

- The history of a change can be read next to its code: `git log -- .samba/tasks/done/<id>.md`.
- Task files now get reviewed like other text. Anything that should not be in the repo (secrets,
  personal paths, customer data) must be removed before the task is committed.
- A finished task is not rewritten by Samba, so these files stay stable in history. A task that is
  reopened moves back to a working state and is ignored until it finishes again.
- Open: whether a task file that is `discarded` should be tracked too (proposed: yes, since it records
  a decision not to do something), and the rules for what goes into a task file.
