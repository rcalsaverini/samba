---
status: accepted
date: 2026-11-07
supersedes: []
---

# 0007: One git worktree per task, outside the repository

Recorded retroactively on 2026-11-08.

## Context

Tasks must be able to run in parallel and must not disturb the human's checkout. Each one needs its
own files and its own branch, which can be reviewed and merged afterwards.

## Decision

- Each task gets a `git worktree` on its own branch, `samba/<id>`, under
  `~/.samba/workspaces/<repo-key>/<id>`.
- Worktrees live outside the repository on purpose. Claude Code loads `CLAUDE.md` files from its
  working directory and every parent directory, so a worktree nested inside the main checkout would
  also read the main checkout's `CLAUDE.md`.
- The path must resolve inside the workspaces root, and the workspaces root must not be inside the
  repository. Both are checked at startup.
- The workspace is kept across runs. The worktree is removed when the task reaches `done` or is
  deleted. The branch is kept.

## Consequences

- Parallel agents cannot overwrite each other or the human's working tree.
- A worktree is isolation for git state only. It is not a security boundary, and Samba is meant for
  trusted local repositories.
- Disk use grows with the number of live tasks. A repository's `after_create` hook runs once per
  worktree and has to be cheap enough for that (for example `uv sync -q`).
- The repo key is derived from the repository folder name, so renaming the folder starts a new key.
