---
priority: 3
depends_on: [plan-accept-reject-and-work-reject-commands]
---
# Work accept command

Phase 2. `symphony work accept <id>` merges a reviewed task's branch and marks the task done. It is
the first command classed as dangerous.

Read first: `docs/command-ideas.md` sections 5.3 and 6.3; SPEC §4.1, §7 (workspaces, branches),
§11; the command pattern established by the `plan accept` / `reject` task.

Decisions already made by the human:

- Follows the command pattern: the merge is the command's outside effect, then it fires
  `work.accept`. Moving a file from `work-review` to `done` by hand stays a plain event and never
  merges.
- Default merge: a merge commit (`git merge --no-ff symphony/<id>`) into the base branch, with a
  message naming the task. `--no-merge` fires the event without merging (for when the human
  already merged).
- Confirmation (doc section 5.3): on a TTY, prompt `[y/N]` showing the branch, the base branch and
  the number of commits; without a TTY and without `--yes`, exit code 2 without acting; `--yes`
  skips the prompt. `--dry-run` prints what would happen and exits 0.

Scope:

- Preflight, all before any change: the task is in `work-review`; the main checkout is on the base
  branch; the main checkout has no uncommitted changes to tracked files; the branch exists. Any
  failure: exit code 1 with a clear message, nothing changed.
- Merge conflict: abort the merge (`git merge --abort`), leave the task in `work-review`, exit
  code 1 with the conflicting files listed, and a `## Log` line saying the merge failed.
- After a successful merge, fire `work.accept`; the orchestrator's cleanup removes the worktree as
  today. The branch is kept (deleting branches is a later `clean` command).

Acceptance criteria:

- Black-box tests (all with `--yes` or without a TTY as appropriate): successful merge (merge
  commit present on the base branch, task in `done`, `## Log` line), `--no-merge`, `--dry-run`,
  refusal without TTY and without `--yes`, each preflight failure, merge conflict aborted cleanly,
  wrong state refusal.
- SPEC §11 documents the command and the confirmation policy.
- `uv run pyright` reports 0 errors and `uv run pytest -q` passes.

## Plan
### Approach

Add `symphony work accept ID [--no-merge] [--no-validate] [--yes] [--dry-run] [--repo PATH]`. It follows the command pattern in SPEC §11: resolve the id, confirm, take the repo lock, run preflight, do the outside effect (merge, validate, commit), then fire `work.accept` through `Machine.fire`. The `work-review -> done` row already exists in `transitions.py`, so the transition table does not change. A hand move to `done` stays a plain observed event and never merges.

Put the git logic in a new module `src/symphony/merge.py`. Write a separate `cmd_work_accept` in `cli.py`; do not bend `cmd_transition`. Reuse `resolve_task_id`, `repo_lock`, `TaskStore`, `SidecarStore`, `Machine`, `human_events`, and the lock-busy and wrong-state messages (factor them into shared helpers if cheap). For subprocesses reuse `proc.py`: `git(cwd, *args)` and `run_shell(cfg.shell, cfg.validate_command, cwd, cfg.validate_timeout_s)` are async, so call them through `asyncio.run` (one small `asyncio.run` wrapper in `merge.py`). That gives validation the same shell, timeout and process-group kill as task validation (SPEC §7.3).

### New in round 2: validate after merging, before committing

The merge is done as `git merge --no-ff --no-commit`, so the merged result sits uncommitted in the main checkout. `validate.command` runs there, and only a pass produces the merge commit. This catches a branch that passes alone but fails after merging with a main that moved on.

Flow of the merge step (skipped entirely with `--no-merge`):
1. `git merge --no-ff --no-commit -m "Merge symphony/<id>: <task title>" symphony/<id>`. (`-m` sets the prepared `MERGE_MSG`.)
2. Non-zero exit: conflict path. List files with `git diff --name-only --diff-filter=U`, then `git merge --abort`. Leave the task in `work-review`. Append the `## Log` line "work.accept: merge failed (conflicts: a, b)". Print the files on stderr, exit 1. If the conflict list is empty (for example an untracked file in the way), abort if `MERGE_HEAD` exists, log git's stderr, exit 1.
3. Exit 0 and no `MERGE_HEAD` (check with `git rev-parse -q --verify MERGE_HEAD`): the branch is already merged, git said "Already up to date". Nothing to validate or commit. Treat as success, note it on stderr, fire the event with message "already merged". Settle this in SPEC.
4. `MERGE_HEAD` present and `validate.command` is configured and `--no-validate` not given: run it in the main checkout (cwd = `config.repo`) with `cfg.shell` and `cfg.validate_timeout_s`.
   - Fail or timeout: `git merge --abort`, then verify `git rev-parse HEAD` equals the pre-merge HEAD and `git status --porcelain --untracked-files=no` is empty. If `merge --abort` itself fails (validation modified tracked files), fall back to `git reset --hard <pre-merge HEAD>`; this is safe because preflight proved the tracked tree was clean. Leave the task in `work-review`. Append a `## Log` line "work.accept: validation failed after merge: <tail>". Exit 1 with the tail on stderr.
   - Log line shape: `append_log` writes one line, so collapse the last N lines (cap N at about 10, `validate.output_tail_lines` as the upper bound) joined with ` | `, and for a timeout append "(timed out after Ns)", as `_validate` does in the orchestrator. Write the full output to `.symphony/runs/<id>/accept-validate.log` and mention that path on stderr. Check `append_log` in `tasks.py` first; if it already handles multi-line text safely, use the tail as is.
   - Note `run_cmd` returns empty output on timeout, so the line for a timeout is just the timeout note.
5. Validation passes (or is skipped: no `validate.command`, or `--no-validate`): `git commit --no-edit`, which uses the prepared `MERGE_MSG`. Read the new HEAD sha. Then fire `work.accept` with message "merged <sha>" (add ", validated" when validation ran, ", validation skipped" with `--no-validate`).
6. `--no-validate` has no effect with `--no-merge` (no merge, nothing to validate); accept the flag silently.
7. No `validate.command` configured: skip validation and print a note on stderr ("no validate.command; merged without validation").

Order of operations in `cmd_work_accept`:
1. Resolve the id (unknown or ambiguous: exit 2). Check the state is `work-review` through `human_events` (wrong state: exit 1, the usual "Legal events" message).
2. Preflight read-only checks, unless `--no-merge` (then only the state check): main checkout on `config.base_branch` (`git symbolic-ref --short HEAD`); no uncommitted changes to tracked files (`git status --porcelain --untracked-files=no` empty); branch `workspace.branch_name(id)` exists (`git rev-parse --verify --quiet refs/heads/...`). Each failure: exit 1, clear message, nothing changed.
3. Commit count: `git rev-list --count <base>..<branch>`.
4. `--dry-run`: print the branch, base branch, commit count, whether it would merge, whether it would validate (the command text, or "skipped"), and the final state; exit 0, no prompt, no change. Runs after preflight so a dry run also reports preflight failures. It never runs the validate command.
5. Confirmation: `--yes` skips. If stdin and stdout are TTYs, print "Merge symphony/<id> into <base> (N commits)? [y/N]" (add "then validate with `<command>`" when validation will run; "Mark done without merging" for `--no-merge`); anything but `y`/`yes` is exit 1, no change. No TTY and no `--yes`: exit 2 with a message, no action. Prompt before taking the lock so a slow human never blocks orchestrator ticks.
6. Take the lock (busy: exit 1). Re-check the state and re-run preflight under the lock. Then the merge flow above, then `fire`.
7. On success print the task file's new path on stdout, exit 0. If `fire` returns False after a commit, report loudly with the sha and exit 1 (the merge is already in the base branch). The branch is kept; the orchestrator's cleanup removes the worktree.

Git identity: the merge commit needs `user.name`/`user.email`. In tests, pass `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`, `GIT_COMMITTER_NAME`, `GIT_COMMITTER_EMAIL` through `sb.run(..., **env)`. Do not set identity inside the command.

### Steps (tests first)

- [ ] Re-read `tests/test_commands.py` (`review_task` at line 17, wrong-state parametrization at line 171), `Sandbox.write_workflow` (override with `validate={"command": ..., "timeout_s": ...}`), `tasks.append_log`, and SPEC §4.1, §7.3 and §11.
- [ ] New `tests/test_work_accept.py`, black-box only (no `import symphony`). Helper: create `symphony/<id>` with real commits in the sandbox repo, put the task in `work-review` with a sidecar containing `branch`, set the git identity env vars.
- [ ] Write the failing tests:
  - [ ] Success with `--yes`: exit 0; merge commit on the base branch (two parents) whose message names the task; branch file present in the main checkout; task in `done`; `## Log` has the `work.accept: work-review -> done` line; branch still exists; stdout is the new path.
  - [ ] `--no-merge --yes`: task `done`, base HEAD unchanged, branch untouched, validation not run.
  - [ ] `--dry-run`: exit 0, output mentions branch, base, commit count and validation; nothing changed; works with no TTY and no `--yes`; the validate command does not run (it would write a marker file; assert it is absent).
  - [ ] No TTY and no `--yes`: exit 2, nothing changed.
  - [ ] Optional `pty` test: answer `n` (no change) and `y` (merged). Drop it if flaky and say so in the task log.
  - [ ] Preflight failures, each exit 1 and nothing changed: main on another branch; a modified tracked file (an untracked file alone does not block); branch missing.
  - [ ] Wrong state, parametrized (`plan-review`, `work-todo`, `done`, ...): exit 1 with the legal events listed, nothing changed. Unknown id: exit 2.
  - [ ] Conflict: both sides change the same line. Exit 1, the file on stderr, no `MERGE_HEAD`, no conflict markers, HEAD unchanged, task still in `work-review`, merge-failed `## Log` line.
  - [ ] Validation (new): configure `validate.command` as `! test -f old.txt` (the branch worktree has no `old.txt`, so the branch passes alone). After branching, commit `old.txt` on main (no textual conflict). `work accept --yes` exits 1; main HEAD is unchanged; `git status` is clean for tracked files and no `MERGE_HEAD`; no merge commit; the task is still in `work-review`; `## Log` has the validation-failure line with the output tail (have the command echo a marker string and assert it appears).
  - [ ] Validation passes after merge: same setup but a command that succeeds; merge commit present, task `done`.
  - [ ] `--no-validate`: the failing setup above, with `--no-validate --yes`, merges and reaches `done`.
  - [ ] Validation runs in the main checkout: the command writes `pwd` to a file outside the repo (via an env var set in `sb.run(**env)`); assert it equals the repo path, and that the merged file was present when it ran (command also checks `test -f <branch file>`).
  - [ ] Validation timeout: `validate.timeout_s: 1` and `sleep 30`; exit 1, merge aborted, `## Log` mentions the timeout.
  - [ ] No `validate.command` configured: the merge proceeds (the success test above covers this; assert the stderr note).
  - [ ] Hand move `work-review -> done` performs no merge: check whether an existing test already covers it; add only if not.
- [ ] Implement `merge.py` and `cmd_work_accept`. Add the `work accept` subparser (`id`, `--no-merge`, `--no-validate`, `--yes`, `--dry-run`, `--repo`), add it to the `--repo` loop and the dispatch in `main`, and update the `work` help text and the module docstring.
- [ ] Update SPEC §11: the usage block (with `--no-validate`), a work accept subsection (merge as the outside effect, preflight list, `--no-ff --no-commit`, validate in the main checkout with the §7.3 shell and timeout, commit only on pass, `--no-validate`, `--no-merge`, confirmation policy by class, dry-run, conflict and validation-failure handling and their `## Log` lines, already-merged edge case, branch kept, exit codes), the "Exit codes" bullet, and the sentence listing commands that use the pattern. Add one sentence to §7.3 saying validation also runs at accept time. No em-dashes.
- [ ] Update `CLAUDE.md` (`cli.py` line, `merge.py` entry).
- [ ] Run `uv run pyright` (0 errors), then `uv run pytest -q`, as separate plain commands.
- [ ] Add a line to the task file's `## Log` saying SPEC was updated and which details were settled (already-merged branch, `--no-merge` also confirmed, dry-run order, validation log line shape).

### Files to change

- `tests/test_work_accept.py` (new); possibly `tests/conftest.py` for a branch-building helper.
- `src/symphony/merge.py` (new).
- `src/symphony/cli.py`.
- `SPEC.md` (§11, §7.3).
- `CLAUDE.md`.

### Risks

- **Lock held during validation:** validation can take up to `validate.timeout_s` (default 900s). The orchestrator skips ticks and other commands fail with the lock-busy message meanwhile. Acceptable, since the merged state is in the shared main checkout; document it in SPEC. The confirmation prompt stays outside the lock.
- **Cleanup after failed validation:** validation may modify tracked files or leave untracked files (caches). `merge --abort` can then fail; use the `reset --hard <pre-merge HEAD>` fallback (safe because preflight required a clean tracked tree) and verify HEAD afterwards. Untracked leftovers from validation are not removed; mention that in SPEC.
- **Validation changes tracked files after a pass:** `git commit --no-edit` commits only the index (the merge result), not those edits. They stay as uncommitted changes in the main checkout; the user sees them in `git status`. Note it, do not try to handle it.
- **Validate command is user-provided shell run in the main checkout:** same trust as task validation; no new exposure. The command text is not echoed from untrusted sources.
- **Git identity:** the merge commit needs it; a missing identity makes `git commit` fail. Handle like a non-conflict failure: abort the merge, log, exit 1, show git's stderr.
- **Partial success:** if the commit succeeds but `fire` returns False, the merge is in the base branch. The lock makes this unlikely; report the sha loudly.
- **Dirty check and `.symphony/`:** verify how `.symphony/` is ignored in the sandbox and in this repo, so task moves never make the main checkout look dirty.
- **`## Log` multi-line text:** check `append_log` before writing tails into it; collapse to one line if needed.
- **TTY detection:** use stdin and stdout `isatty`; the `pty` test is optional.
- **Black-box rule:** the new tests may only use the CLI, files and git.

### How to verify

- `uv run pyright` reports 0 errors.
- `uv run pytest -q` passes, including the new tests and all existing ones.
- Manual check in a scratch repo: make a task branch that passes alone but fails after main moves, run `symphony work accept <id> --dry-run`, then `--yes` (refused, main untouched, `## Log` has the tail), then `--yes --no-validate` (merge commit, task in `done`, branch kept).

## Feedback
### Round 1

Add a pre-merge check: merge with git merge --no-ff --no-commit, run validate.command from WORKFLOW.md in the main checkout (same shell and timeout as task validation), and only commit if it passes. On failure: git merge --abort, leave the task in work-review, append a ## Log line with the tail of the validation output, exit 1. Add --no-validate to skip it. Black-box tests: a branch that passes alone but fails after merging with a moved main is refused and leaves main untouched.

## Log
- 2026-11-07 01:53 symphony: dispatch_plan: plan-todo -> plan-running
- 2026-11-07 01:54 symphony: planned: plan-running -> plan-review: planned (turns 1, $0.21): Plan for `symphony work accept`: a new `merge.py` module plus a `cmd_work_accept` in `cli.py`, with a black-box test file written first and the SPEC §11 update. The `work.accept` row already exists, so the transition table is unchanged.
- 2026-11-07 19:18 symphony: plan.reject: plan-review -> plan-todo: feedback round 1
- 2026-11-07 19:18 symphony: dispatch_plan: plan-todo -> plan-running
- 2026-11-07 19:19 symphony: planned: plan-running -> plan-review: planned (turns 2, $0.75): Revised plan adds a pre-commit validation step: `git merge --no-ff --no-commit`, run `validate.command` in the main checkout with the §7.3 shell and timeout, commit only on pass, abort and log the output tail on failure, plus `--no-validate` and black-box tests for the moved-main case.
- 2026-11-07 19:22 symphony: plan.accept: plan-review -> work-todo
- 2026-11-07 19:22 symphony: dispatch_work: work-todo -> work-running
- work: implemented `merge.py`, `cmd_work_accept`, tests in `tests/test_work_accept.py` (21, incl. pty prompt test, stable). pyright 0 errors, pytest 208 passed. SPEC §11 and §7.3 updated; settled: already-merged branch is a success ("already merged"), `--no-merge` also needs confirmation, dry-run runs after preflight and never validates, validation log line is the last <=10 lines joined by " | " (plus timeout note), full output in runs/<id>/accept-validate.log. Hand-move test added.
- 2026-11-07 19:26 symphony: permission denied: Bash (python3 - <<'EOF'
import re
p='src/symphony/cli.py'
s=open(p).read()
s=s.replace("from symphony.config import","from sym)
- 2026-11-07 19:28 symphony: done: work-running -> work-review: validation passed (turns 3, $1.28): Added `symphony work accept` (`merge.py` plus `cmd_work_accept`). It merges with `--no-ff --no-commit`, runs `validate.command` in the main checkout, and commits only on a pass. It supports `--no-merge`, `--no-validate`, `--yes` and `--dry-run`. SPEC §11 and §7.3 and CLAUDE.md are updated. I added 21 black-box tests. pyright reports 0 errors and the full suite passes (208 tests). All work is committed on the branch.
- 2026-11-07 19:36 symphony: work.accept: work-review -> done: merged 2f6e629, validated
