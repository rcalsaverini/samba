# New command for approving tasks

Add `symphony approve <id>` so I don't have to move files by hand.
It should move a task from plan-review/ to todo/ (approving the plan)
or from review/ to done/ (accepting the work).

## Feedback


## Plan
### Note

The task file has no `## Feedback` section this time (only `## Plan`, `## Questions` and `## Log`), so there was nothing new to incorporate. Below is the previous plan, unchanged. If you meant to leave feedback, add it under `## Feedback` and send the task back to `plan/`. The open questions are repeated at the end.

### Approach

`symphony approve <id>` is one command with two modes, chosen by the task's current state:

- `plan-review` -> `todo`: approve the plan. A file move plus a log line. No orchestrator change: SPEC 14.3 rule 2 already detects approval at dispatch (file in `todo/`, sidecar `last_outcome == "planned"`). The sidecar is not touched.
- `review` -> `done`: accept the work. Merge `symphony/<id>` into the base branch, move the file to `done/`, remove the worktree (keep the branch). The human no longer merges by hand.

Settled details (add to SPEC section 11 and note in the task file `## Log`; SPEC 1.1 "the agent never merges" stays true because the human runs the command):

1. **Order and failure (review mode).** Preflight, merge, move to `done/`, log line, worktree removal. Any preflight or merge failure leaves the task in `review/`, exit 1 with a clear message; a failed merge is aborted with `git merge --abort`. Failure of worktree removal after the merge is only a warning (orchestrator cleanup, SPEC 5.2 and 7.4, removes it later).
2. **Preflight** (repo `config.repo`, base `config.base_branch`): main checkout is on the base branch; no tracked changes (`git status --porcelain --untracked-files=no` empty); branch `symphony/<id>` exists. If the branch is missing, skip the merge with a note in stdout and the log line. "Already up to date" counts as success.
3. **Merge:** `git merge --no-ff -m "Merge symphony/<id>: <title>" symphony/<id>` in `config.repo`. No push, no rebase, branch never deleted. `--no-merge` flag skips the merge and only moves.
4. **Worktree removal:** `Workspaces.remove(id)` via `asyncio.run` (idempotent if the orchestrator also cleans up).
5. **Other states, unknown id, invalid id** (`is_valid_id`): exit 1, `symphony: <id> is in <state>; approve works on plan-review and review`, nothing moves.
6. **Output and log:** print the new task path; append a `## Log` line via `TaskStore.append_log` in the existing timestamped format (copy from `orchestrator.py`): `approved plan (plan-review -> todo)` or `accepted work, merged symphony/<id> into <base> (review -> done)`.
7. No running orchestrator required.

### Steps

- [ ] Read SPEC 1.1, 2, 3.3, 4.1, 5.2, 7.4, 11, 14.2, 14.3; `proc.py` (`git` helper, result `.ok`/`.output`); `config.py` (`repo`, `base_branch`); log-line format in `orchestrator.py`.
- [ ] Black-box tests first in `tests/test_blackbox.py` (next to `test_new_command_creates_todo_task`, ~line 404; use `sb.add_task`, `sb.run("approve", id)`, `sb.state_of`, `sb.log_section`, `sb.branch_exists`, `sb.worktree`, `git(sb.repo, ...)`; never import `symphony`):
  - [ ] plan-review -> todo: exit 0, path on stdout, log line, sidecar unchanged.
  - [ ] End-to-end plan approval: sidecar `last_outcome: planned`, `## Plan` present; approve, then `sb.run_idle()` with scripted fake; fresh session (no `--resume`), `plan_approved` true.
  - [ ] review -> done with merge: real branch `symphony/<id>` with a commit; file lands on the base branch, merge commit exists, task in `done/`, log line, branch kept, worktree gone.
  - [ ] Merge conflict: non-zero exit, task still in `review/`, no `.git/MERGE_HEAD`, clean tree, base unchanged.
  - [ ] Dirty tracked file in main checkout: non-zero, no merge, task stays.
  - [ ] Main checkout on another branch: non-zero, nothing changes.
  - [ ] review task with no branch: moves to `done/`, exit 0, note printed.
  - [ ] `--no-merge`: moves, base branch does not get the commit.
  - [ ] Other states, unknown id, invalid id (`../x`): non-zero, file stays.
  - [ ] `--repo` respected.
- [ ] Implement in `src/symphony/cli.py`: `cmd_approve(config, task_id, merge)`, `APPROVE` mapping, `_merge_branch` helper, `approve` subparser (positional `id`, `--no-merge`, `--repo`), dispatch, docstring. Strict pyright, no `Any`.
- [ ] Update SPEC.md (1.1, 7.4, 11, 14.2) and the CLAUDE.md map line. No em-dashes.
- [ ] Add a `## Log` note naming the settled spec details.
- [ ] Run `uv run pyright`, then `uv run pytest -q`, as separate plain commands.

### Files to change

- `tests/test_blackbox.py`, `src/symphony/cli.py`, `SPEC.md`, `CLAUDE.md`; `tests/conftest.py` only if a helper (branch with a commit) is missing.

### Risks

- First time Symphony touches the human's main checkout: mitigated by preflight, `--no-ff` without push, abort on conflict, `--no-merge`.
- Merge succeeds but the move fails: re-running is safe ("Already up to date").
- Concurrent orchestrator: review tasks are not running, renames are atomic, worktree removal is idempotent.
- Signing or hooks could block a non-interactive merge: surface git's stderr tail on failure.

### How to verify

- `uv run pyright` 0 errors; `uv run pytest -q` all green.
- Manual in a scratch repo: approve a plan, run to `review/`, approve again; check merge commit, `done/`, worktree gone, branch kept.

### Suggested subtasks

None.

## Questions
There was no `## Feedback` section in the task file. What should change in the plan? Also still open: (1) merge style `--no-ff` vs fast-forward vs squash; (2) when a review task has no `symphony/<id>` branch, skip the merge with a note (current plan) or error?

## Log
- 2026-11-06 22:52 symphony: planned, moved to plan-review (turns 1, $0.19): Plan for `symphony approve <id>`: a CLI-only move from plan-review to todo or review to done, leaving the sidecar alone so the existing dispatch rule (SPEC 14.3) detects approval. It includes black-box tests first, a SPEC section 11 update and a log note.
- 2026-11-06 23:03 symphony: planned, moved to plan-review (turns 2, $0.47): Revised plan: `symphony approve` on a review task now also merges `symphony/<id>` into the base branch with `--no-ff`, moves the task to done and removes the worktree, aborting cleanly on any failure. Plan approval stays a plain move, with a `--no-merge` escape hatch and tests for conflicts, dirty tree and wrong branch.
- 2026-11-06 23:16 symphony: planned, moved to plan-review (turns 3, $0.84): The task file has no `## Feedback` section this time, so I re-submitted the previous plan unchanged with a note saying so. The two merge-default questions are still open.
- 2026-11-07 01:16 symphony: task.discard: stuck -> discarded: observed hand move
