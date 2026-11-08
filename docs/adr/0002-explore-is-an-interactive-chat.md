---
status: accepted
date: 2026-11-08
supersedes: []
---

# 0002: Exploration is an interactive chat, outside the task state machine

## Context

Planning and work are fire-and-forget: a task goes in, an agent runs headless, a human reviews the
result. Exploring a design question is different. It is back and forth, the human steers, and the
outcome is a set of decisions, not a plan or a branch.

## Decision

- `samba explore "topic"` launches an interactive `claude` session in the repository with an ADR
  guide appended to its instructions. It has no task states, no worktree and no review folder.
- The session produces zero or more ADRs with status `proposed`, each covering one decision (ADR 0001).
  The human accepts or rejects each one in the chat or with `samba adr` commands.
- Research inside the chat uses Claude Code's own subagents. Samba adds no machinery for it.

## Consequences

- Samba stays headless everywhere except this one launcher, which is a thin wrapper.
- Nothing in the orchestrator, the transition table or the task store changes for exploration.
- An exploration is only as durable as the ADRs it writes. Chat history is not a record.
- Whether this should be a Samba command or only a Claude Code slash command or skill is open. Samba
  gains little beyond passing a fixed allow list (ADR 0004).
