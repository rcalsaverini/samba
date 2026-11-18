---
priority: 3
depends_on: ["add-the-composition-root-reduce-cli-py-to-an-adapter-and-fin"]
---
# Put git, worktrees, validation, lock and journal behind ports

Part 7 of 7 of the refactor that ADR 0011 starts. Read docs/adr/0011 and 0012 first, and 0006, 0007, 0008, 0009 and 0010 for context. Follow them; do not re-decide them.

Behavior does not change. The black-box suite must pass unchanged; if you must change a black-box test, say why in your log. Keep pyright strict at 0 errors. Layout: pure `src/samba/domain/`, use cases in `src/samba/app/`, ports in `src/samba/ports.py`, adapters in `src/samba/adapters/`.

Scope:
- A `Vcs` port in the vocabulary of the domain: ensure and remove a task's workspace, list existing workspaces, check the base branch and the repository root, preflight for a merge, count commits, merge without committing, abort, commit, keep Samba's directory out of version control. `workspace.py` and `merge.py` become its git adapter, with one convention for sync and async (no `asyncio.run` inside sync wrappers).
- A `Validator` port: run the repo's validation in a workspace and return a result (ok, timed out, output tail, log location). Used by the turn flow and by work accept.
- A `Lock` port for the repo lock (flock adapter), and a `Journal` port replacing the global `logging.getLogger("samba")` calls in the core with structured events. The adapter keeps the current log format, file and levels.
- The orchestrator and every use case receive all their ports; the composition root from part 6 builds them. Nothing in `domain/` or `app/` touches the process, git, a file or a logger.
- Add a fake for each port under `tests/` and two or three scenarios that run a whole task through plan, work, review and accept with fakes only (ADR 0012).
- Update the spec (architecture chapter: the final list of ports and adapters; the workspaces chapter where the adapter boundary matters).

Done when:
- `tests/test_architecture.py` lists every domain and app module and passes.
- The end-to-end scenarios pass in well under a second, and the black-box suite is unchanged and green.
- The spec step is done, and pyright and the tests pass.

## Plan
### Approach

Behavior stays identical. The black-box suite is not touched, apart from anything a failing run proves unavoidable, which would be justified in the task `## Log`.

The work in one paragraph:
- Add four ports to `ports.py`: `Vcs`, `Validator`, `Lock`, `Journal`.
- Fold `workspace.py`, `merge.py`, `git_merger.py` and `git_workspaces.py` into one adapter, `adapters/git_vcs.py`.
- Fold `lock.py` and `repo_lock.py` into `adapters/file_lock.py`.
- Add `adapters/shell_validator.py` and `adapters/log_journal.py`.
- Move the merge sequence out of `merge.py` into the `AcceptWork` use case.
- Remove `logging`, `proc`, `workspace`, `merge` and `Path` from `orchestrator.py`, `app/` and `domain/`.

### Design decisions

**One sync/async convention.**
- Every `Vcs` and `Validator` method is `async def`.
- Adapters never call `asyncio.run`.
- `AcceptWork.run` becomes `async`. `cli.py` calls `asyncio.run(...)` once at the adapter edge, in the `work accept` handler.
- `Lock` stays sync, as it is now: flock with a short sleep loop, used in a `with` block.
- `Journal` is sync.

**`Vcs`, in the domain's vocabulary.** Locations are opaque `str`, with no `Path`.
- `branch_name(task_id) -> str`
- `workspace_location(task_id) -> str`
- `async ensure_workspace(task_id) -> Workspace(location, created)`
  - Raises `WorkspaceError`.
  - The `after_create` hook stays inside the adapter. The adapter takes `Hooks` and `shell`, and removes the worktree on hook failure, exactly as today.
- `async remove_workspace(task_id)` (raises `WorkspaceError`)
- `async existing_workspaces() -> list[str]`
- `async repository_problem() -> str | None`
  - Checks the repository root and the base branch, with today's `StartupError` texts: "... is not the root of a git repository" and "base_branch '<x>' does not exist".
- `async preflight(branch) -> str | None`
- `async commit_count(branch) -> int`
- `async begin_merge(branch, message) -> MergeAttempt(status, detail, restore_point)`
  - `status` is `pending`, `already`, `conflict` or `error`.
  - It is `git merge --no-ff --no-commit`, and on conflict it aborts or resets internally, as `merge_branch` does now.
- `async abort_merge(restore_point)`: the `_undo` logic, merge --abort then reset --hard when needed.
- `async commit_merge(restore_point) -> CommitResult(ok, detail)`
  - On success, `detail` is the short sha.
  - On failure it undoes the merge and returns the last 4 lines of output.
- `checkout_location() -> str`: the main checkout, where accept validates.
- `async exclude_samba_dir()`: the `info/exclude` logic from `Orchestrator._exclude_samba_dir`.
- The restore point is returned, not stored, so the adapter holds no hidden state.

**`Validator` port.**
- `async run(location: str, log_name: str) -> ValidationResult`.
- The adapter wraps `run_shell` with the `Validation` config, writes `<runs>/<log_name>` (creating dirs) and returns the result.
- `ValidationResult` is a frozen dataclass in a new `domain/validation.py`. Fields: `ok`, `timed_out`, `code`, `output` (full text), `timeout_s`, `tail_lines` (the configured limit), `log_location: str | None`.
- Two pure helpers keep the two existing tail formats byte-identical:
  - `agent_tail(result)` is `rstrip().splitlines()[-tail_lines:]` joined by newline, plus the `(timed out after {timeout_s}s)` line.
  - `accept_tail(result)` is non-blank stripped lines, last `min(10, tail_lines)`, joined by ` | `, with the `{timeout_s:g}` note and the `(no output)` fallback.
- Log names are `<id>/validate-<turns_total:03d>.log` (turn flow) and `<id>/accept-validate.log` (accept).

**`Lock` port.**
- Rename `RepoLock` to `Lock`, with the same `acquire(blocking) -> context manager[bool]` shape.
- Update `change_state`, `answer_question`, `accept_work`, `tick`, `compose`, `FakeLock`.

**`Journal` port.**
- Methods: `debug(event, **fields)`, `info`, `warning`, and `exception(event, **fields)` (error level, includes the traceback of the exception being handled).
- `adapters/log_journal.py` (`LogJournal`) keeps the exact format and file: `logging.getLogger("samba")`, `kv(event, **fields)`, `%(asctime)s %(levelname)s %(message)s`, `samba.log` at DEBUG and stderr at INFO.
- Today `cli._setup_logging` runs only for `samba run`. Keep that, so other commands neither create handlers nor write the log.
  - `compose.build(repo, *, for_run: bool = False)` builds `LogJournal(samba_dir)` for run.
  - It builds a `NullJournal` (a no-op, in the adapters) otherwise.
  - `cli.py` loses `logging` and `_setup_logging`.
  - Check how `main` calls `build` and pass `for_run` accordingly.
- `ClaudeCliRunner` also receives the journal instead of its own `getLogger`.

**Use cases and orchestrator take all ports.**
- `Machine`, `TurnFlow`, `Tick`, `AcceptWork` and `Orchestrator` get `journal` (and `vcs`, `validator`, `lock` where needed) as required constructor parameters, with no defaults. The `logfmt.kv` calls move into `LogJournal`.
- `TurnFlow(agent, ids, tasks, clock, validator, journal)`
  - It calls the validator itself when the action is `RunValidation`, and emits `journal.info("validate", task, ok, code)`.
  - The `validate` callable parameter of `run` goes away.
- `Orchestrator`
  - Ports: `config, clock, ids, agent, tasks, vcs, validator, lock, journal`.
  - Workers use `vcs.ensure_workspace`, `vcs.branch_name` and `vcs.workspace_location`, and `str` locations.
  - Startup uses `vcs.repository_problem()` and `vcs.exclude_samba_dir()`.
  - The `runs_dir.mkdir` moves into the adapters that write runs (Validator and `ClaudeCliRunner`). Verify `claude_cli` already creates its dirs, and add it if not.
- `Tick` takes `Vcs` in place of `Workspaces`, and `Journal`.
- `AcceptWork`
  - Ports: `tasks, machine, terminal, lock, vcs, validator, journal, base_branch, validate_command`.
  - It now runs the sequence formerly in `merge.merge_branch`: `begin_merge`, then (if validating) `validator.run(vcs.checkout_location(), "<id>/accept-validate.log")`, then `abort_merge` on failure or `commit_merge`.
  - It maps results to the same `Refused` and `Accepted` messages, using `accept_tail`.
  - The messages for conflict, error, already, validation_failed (detail plus the "full output: <log>" line) and merged (sha, ", validated") must stay byte-identical.
- Delete `Merger`, `MergeResult`, `Workspaces`, `WorkerWorkspaces`, `RepoLock` and their adapters.
- Keep `WorkspaceError` in `ports.py`.

**Fakes, all under `tests/`.**
- `fake_vcs.py`: in-memory workspaces, scripted merge, preflight and commit-count results, a recorded call log, optional failure injection.
- `fake_validator.py`: scripted results per call, recorded calls.
- `fake_lock.py`: reuse or move the existing `FakeLock`, with a `held` flag.
- `fake_journal.py`: records `(level, event, fields)`.
- Delete `fake_merger.py` and the fake workspaces in `test_tick.py`.

**End-to-end scenarios (ADR 0012).**
- New `tests/scenarios/lifecycle.json` and a runner in `tests/test_scenarios.py` (or `test_lifecycle.py`). It imports only the domain, `app/`, `orchestrator.py` and the fakes, never an adapter.
- The runner builds `Orchestrator` with `FakeTasks`, `FakeAgent`, `FakeVcs`, `FakeValidator`, `FakeLock`, `FakeJournal`, a fake clock and an ids generator. It calls `startup`, then `tick()` and awaits the running workers (no `run()` and no poll sleep).
- Human steps go through `ChangeState` (`plan accept`) and `AcceptWork` (`work accept`).
- Scenarios:
  1. Happy path with plan approval: plan-todo, plan-running, plan-review, plan accept, work-todo, work-running, work-review, work accept, done. It checks the merge calls, validator calls, workspace creation and removal, and key journal events.
  2. Work validation fails once, the turn flow feeds back the tail and the second run passes. Also accept-time validation failure: the merge is aborted and the task stays in work-review.
  3. Agent reports blocked with a question, the human answers, the task resumes and finishes. Or a merge conflict at accept that leaves the task in work-review.
- One test asserts the scenarios take well under a second in total.
- Existing `turn_flow` scenario JSON stays valid. The runner swaps its validate callable for a `FakeValidator` built from the scenario's `validate` results (the tail becomes `output`).

### Spec and docs
- `docs/spec/architecture.md`
  - New final ports table: `Clock`, `IdGenerator`, `AgentRunner`, `Terminal`, `Lock`, `Vcs`, `Validator`, `Journal`, `Adrs`, `Tasks`, with their adapters.
  - Rewrite "Where each concern lives today": nothing remains unported except `proc.py` helpers inside adapters and `views.py`.
  - Add the `lifecycle` row to the Scenarios table.
  - Update the architecture-test paragraphs. The two duplicate sections can be merged.
- `docs/spec/workspaces.md`: note that creation, the hook, validation and removal are the `Vcs` and `Validator` adapters' business, and that the use cases see opaque locations.
- `docs/spec/observability.md`: say events go through the `Journal` port and the log format is unchanged.
- `CLAUDE.md` map: replace the entries for `workspace.py`, `merge.py`, `lock.py`, `git_merger.py`, `git_workspaces.py`, `repo_lock.py`. Add `git_vcs.py`, `file_lock.py`, `shell_validator.py`, `log_journal.py` and the new fakes.
- Also grep the spec, README and manual for `merge.py`, `workspace.py`, `lock.py`, `RepoLock` and `Merger`. `tests/test_manual.py` and `tests/test_spec_docs.py` must stay green.
- Add a `## Log` note in the task file saying the spec was updated and which details were settled (async convention, `for_run` journal, full output in `ValidationResult`).

### Steps
- [ ] 1. Read ADRs 0011, 0012, 0006 to 0010 and `docs/spec/{architecture,workspaces,observability,orchestrator,cli}.md`. Run `uv run pytest -q` and `uv run pyright` for a green baseline.
- [ ] 2. Add `domain/validation.py` (`ValidationResult`, `agent_tail`, `accept_tail`) with unit tests that pin both tail formats against today's output, including the timeout note, `(no output)`, blank lines, and the `{timeout_s}` vs `{timeout_s:g}` difference.
- [ ] 3. Add the new ports to `ports.py` (`Vcs` plus its result dataclasses, `Validator`, `Lock`, `Journal`). Write the fakes in `tests/`, and write the lifecycle scenarios and runner. They fail or are skipped until the wiring exists.
- [ ] 4. Update `tests/test_architecture.py`:
  - Add a test that every `.py` under `domain/` and `app/` is in `DOMAIN_MODULES` or `APP_MODULES`.
  - Add `domain/validation.py`.
  - Forbid `logging` and `pathlib` in the app modules.
  - Check that `orchestrator.py` imports no adapter, `proc`, `workspace`, `merge`, `lock`, `logging`, `subprocess` or `pathlib`.
  - Add a negative self-test for the new checks.
  - Run it to see it fail.
- [ ] 5. Write the adapters:
  - `adapters/git_vcs.py` (port `workspace.py` and `merge.py` git calls to async methods, move `repo_key` and `branch_name` in).
  - `adapters/file_lock.py`.
  - `adapters/shell_validator.py`.
  - `adapters/log_journal.py` (plus `NullJournal`).
  - Add a test for each against a temp git repo or temp dir where the behavior is non-trivial.
- [ ] 6. Journal: swap `logging.getLogger` and `kv` in `machine.py`, `tick.py`, `turn.py` and `orchestrator.py` for injected `journal` calls. Keep every event name and field. Inject the journal into `ClaudeCliRunner`.
- [ ] 7. Lock: rename `RepoLock` to `Lock` across use cases, tick, compose and tests.
- [ ] 8. Vcs and Validator in the orchestrator and tick:
  - Startup, workers and cleanup use `Vcs`.
  - `TurnFlow` calls the `Validator`.
  - Drop `WorkerWorkspaces`, `Path` and the `proc` imports.
  - Update `test_tick.py`, `test_scenarios.py` and the other direct constructor calls.
- [ ] 9. `AcceptWork`: make it async and implement the merge sequence over `Vcs` and `Validator`. Update `cli.py` to `asyncio.run` it. Update `test_app_accept_create.py` to the new fakes and keep every message assertion.
- [ ] 10. `compose.py`: build the new adapters, pass every port, add `for_run`. Remove `_setup_logging` and `logging` from `cli.py`. Delete `workspace.py`, `merge.py`, `lock.py`, `git_merger.py`, `git_workspaces.py`, `repo_lock.py` and the old fakes.
- [ ] 11. Run `uv run pyright` (0 errors) and `uv run pytest -q`. Confirm that `git diff main -- tests/test_blackbox.py` and the other black-box files are empty.
- [ ] 12. Update the spec chapters, `CLAUDE.md` and the docs listed above, with no em-dashes.
- [ ] 13. Add the `## Log` entry to the task file.

### Files to change
- New:
  - `src/samba/domain/validation.py`
  - `src/samba/adapters/{git_vcs,file_lock,shell_validator,log_journal}.py`
  - `tests/{fake_vcs,fake_validator,fake_lock,fake_journal}.py`
  - `tests/scenarios/lifecycle.json`
  - adapter tests
- Edited:
  - `src/samba/ports.py`
  - `compose.py`
  - `cli.py`
  - `orchestrator.py`
  - `app/{turn,tick,machine,accept_work,change_state,answer_question}.py`
  - `adapters/claude_cli.py`
  - `tests/{test_architecture,test_scenarios,test_tick,test_app_accept_create,test_app_use_cases}.py`
  - `docs/spec/{architecture,workspaces,observability}.md`
  - `CLAUDE.md`
- Deleted:
  - `src/samba/{workspace,merge,lock}.py`
  - `adapters/{git_merger,git_workspaces,repo_lock}.py`
  - `tests/fake_merger.py`

### Risks
- **Log behavior drift.** `samba.log` must not appear for non-`run` commands, and event text, levels and `worker_crashed` tracebacks must stay identical. `NullJournal` for non-run commands relies on there being no log output today. Verify by diffing a black-box run's log before and after.
- **Tail formats.** The two validation tail formats differ in blank-line handling, separator and `timeout_s` formatting. That is why `ValidationResult` keeps the full output and exposes two pure helpers. The unit tests in step 2 guard it.
- **`runs_dir` creation.** Dropping `mkdir` from startup is safe only if the writers create their directories. Confirm in `claude_cli`, and grep the black-box tests for assertions on `runs/`.
- **`AcceptWork` going async.** It touches `cli.py` and its unit tests. The lock is held across awaits, which is fine for flock, but check `cmd_work_accept` and the `--dry-run` path.
- **Merge undo correctness.** The `restore_point` plumbing replaces local state in `merge_branch`. Keep the exact order: abort, then reset if HEAD moved or tracked changes exist. Cover it with a git adapter test: conflict, validation failure with a dirty tracked file, and the already-merged case.
- **Hook failure path.** `ensure_workspace` must still remove the worktree and raise `WorkspaceError` with the same text.
- **Test churn.** Constructors lose their defaults, and `Orchestrator`, `Tick` and `TurnFlow` are built directly in tests. Missing one shows up as a pyright or test failure.
- **Architecture test strictness.** Forbidding `logging` and `pathlib` in `app/` may flag `Running` or other leftovers. Fix the code, do not loosen the test.

### How to verify
- `uv run pyright` reports 0 errors.
- `uv run pytest -q` is green. The black-box files (`test_blackbox.py`, `test_commands*.py`, `test_work_accept.py` and the rest) are unchanged in the diff.
- `tests/test_architecture.py` passes, including the new check that every domain and app module is listed.
- A grep over `src/samba/domain`, `src/samba/app` and `orchestrator.py` finds no `logging`, `subprocess`, `pathlib`, `os.`, `samba.proc`, `samba.workspace`, `samba.merge` or `samba.lock`.
- The lifecycle scenarios pass with fakes only, and the timing test confirms well under 1 s.
- Manual smoke: a `samba run` against a scratch repo with `fake_claude` writes the same `samba.log` lines as before, and `work accept` still merges and validates.

### Suggested subtasks
Not needed: the steps are tightly coupled by the constructor changes. If it has to be split, cut after step 4 (ports, fakes and scenarios with the architecture test) and after step 10 (adapters and wiring).

## Assumptions
- The ADRs (0006 to 0012) were not read, because the plan was written from the code, the spec and CLAUDE.md. The first step of the plan is to read them and adjust the port names if they conflict. `Lock` replaces `RepoLock`, as the task says.
- `Vcs` methods are all async and `AcceptWork.run` becomes async, with a single `asyncio.run` in `cli.py`. This is my reading of "one convention for sync and async".
- The `after_create` hook stays inside the git adapter's `ensure_workspace`. The task lists no separate hook port.
- Non-`run` commands get a no-op journal, so they still write no log, as today. Only `samba run` builds the file and stderr `LogJournal`.
- `ValidationResult` carries the full output, so the two existing tail formats stay byte-identical. This is slightly more than "output tail" in the task.
- Logging inside `ClaudeCliRunner` is also moved to the Journal, although the task only mentions the core.
- Existing scenario JSON files stay unchanged. Only the runner's validate stub changes.

## Log
- 2026-11-10 21:57 samba: dispatch_plan: plan-todo -> plan-running
- 2026-11-10 21:59 samba: planned: plan-running -> plan-review: planned (turns 1, $0.51): Replace the Merger, Workspaces and RepoLock ports with Vcs, Validator, Lock and Journal ports. Move git, flock and logging into adapters, inject every port from compose.py, and add fakes plus lifecycle scenarios that run a task through plan, work, review and accept in memory.
- 2026-11-11 10:38 samba: task.discard: plan-review -> discarded
