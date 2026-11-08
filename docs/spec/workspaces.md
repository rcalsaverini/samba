# Workspaces

## Creation

If `workspaces/<id>` does not exist:

1. If branch `samba/<id>` exists (task reworked after its worktree was removed):
   `git worktree add <path> samba/<id>`.
2. Else: `git worktree add -b samba/<id> <path> <base_branch>`.
3. Run `hooks.after_create` with cwd = worktree. Failure or timeout: remove the worktree, fail the
   attempt.

If it exists, reuse it as is (no reset).

## Safety invariants

- The workspace path, resolved to absolute, must be inside `<workspaces_root>/<repo-key>/`.
- `<workspaces_root>` must not be inside the repository (checked at startup, see layout for why).
- Claude and all hooks run with cwd = workspace path.
- The id regex (task-files, Identity) prevents path tricks in names.

## Validation

`validate.command` (and hooks) run via `shell` (default `bash -c`, a non-login shell that inherits
Samba's environment) with cwd = workspace, after the agent reports done.

The agent's Bash tool runs with the user's interactive shell environment, which can resolve tools
differently (found in the smoke test: the agent's `python3` had pytest, while a `bash -lc` login
shell found a different `python3` without it, plus a profile script error). So validation commands
should pin their tools rather than rely on `PATH` (`uv run pytest`, `make check`, `./scripts/check`),
and the agent should be allowed to run the exact same command. Exit code
0 = pass. Output (stdout+stderr combined) is saved to `runs/<id>/validate-<n>.log`; the last
`output_tail_lines` lines are fed back on failure. A timeout counts as a validation failure, not a
worker failure. `work accept` runs the same command again on the merged result (cli).

## Removal

`git worktree remove --force <path>` when the task reaches `done/` or is deleted. The branch is kept.
Samba never deletes branches.

