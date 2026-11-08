---
status: accepted
date: 2026-11-07
supersedes: []
---

# 0008: Samba runs the validation itself

Recorded retroactively on 2026-11-08.

## Context

An agent saying "done" is a claim, not evidence. The main criterion for this project is how well an
agent can check its own work, and a human reviewing every claim by hand defeats the purpose of
running agents.

## Decision

- When the agent reports done, the orchestrator runs the repo's `validate.command` in the task's
  worktree. The task goes to review only if it passes. If it fails, the output goes back to the agent
  for another turn.
- `work accept` validates again, on the merged result: it merges with `--no-commit`, runs the
  command in the main checkout and commits only if it passes. On failure it aborts the merge and the
  task stays in `work-review`.
- The agent can run the same command itself (it is in the allow list), so it finds failures before
  Samba does.

## Consequences

- Review starts from a green tree, and "it passes on the branch" and "it passes after the merge" are
  both checked.
- Validation is only as good as the repository's command. A weak one lets weak work through.
- Validation time is paid twice per task, and it dominates the cost of `work accept`.
- `work accept` has `--no-validate` for the cases where the human decides otherwise.
