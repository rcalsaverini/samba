---
priority: 3
---
# Split Config into policy, agent settings, layout, prompts, validation and hooks (6a)

Part 6a of 6 of part 6 (which is part 6 of 7 of the refactor that ADR 0011 starts). Read docs/adr/0011 and 0012 first, and 0005, 0009 and 0010 for context. Follow them; do not re-decide them.

The plan below was reviewed and approved. Because it is too large for one run it was split into six sequential tasks: 6a to 6f. The earlier parts are merged. Do ONLY part 6a. The plan's steps are numbered 0 to 10; the other parts cover the other steps, so do not start them. Behavior does not change; the black-box suite passes unchanged. Leave pyright at 0 errors and the full suite green, and commit.

Scope of 6a: step 3 only (the Config split) and the Config unit test of step 1. No ports, no use cases, no CLI change.

Done when (6a): Config is a composite of the frozen parts the plan names; orchestrator, workspace, the claude adapter and views use only the part they need; load_config returns the same values as before (unit-tested); DEFAULT_ALLOW stays in config.py. Spec: note the split in docs/spec/architecture.md and docs/spec/workflow-config.md if it names config groups; the rest of the spec step is part 6f. pyright and the tests pass.

THE APPROVED PLAN (all six parts):

## Plan
### Approach

Follow ADR 0011/0012 and the existing pattern (`app/machine.py`, `app/turn.py`): use cases are classes or functions taking ports, returning frozen result dataclasses, never printing, reading stdin, or returning exit codes. The CLI becomes a thin argparse adapter that parses, builds a request, calls a use case, prints the result's messages (byte-identical to today) and maps result kinds to exit codes. One composition root reads `WORKFLOW.md` and builds everything; `Config` is split so each use case gets only its part.

Order: (1) tests first, (2) ports + config split, (3) use cases one at a time, with the CLI switched over per use case, (4) composition root, (5) tick, (6) architecture test + spec. Run `uv run pyright` and `uv run pytest -q` after every step; black-box tests must stay green and untouched (if one must change, record why in `## Log`).

### Steps

- [ ] **0. Read** `docs/adr/0009..0012`, `docs/spec/architecture.md`, `docs/spec/cli.md` (command pattern at ~line 61, `work accept` ~167, ADR commands ~158), `src/samba/cli.py` (all), `config.py`, `orchestrator.py`, `views.py`, `merge.py`, `lock.py`, `workspace.py`, `tests/fake_tasks.py`, `tests/test_scenarios.py`.
- [ ] **1. Tests first (in-process, domain+app only, no adapters).** Add `tests/fake_terminal.py` (scripted `Terminal`: interactive flag, queued lines, editor results, records prompts) and `tests/fake_merger.py` / fake lock. Add scenario kinds or plain pytest cases (`tests/test_app_use_cases.py`, using `FakeTasks` and a fake clock; never import an adapter) for:
  - `ChangeState`: legal event fires; illegal event returns a `NotAllowed` result naming state and legal events; missing task; `fire` not applied; feedback written before the move with `feedback round N` log; blocked_cause captured for the retry hint; empty feedback warning (`optional`) and error (`required`).
  - `AnswerQuestion`: single open question; none open; several open (lists them); unknown qid; question not open; answer recorded, fires `question.answer` only when the round has no open question left; stale re-check after the lock.
  - `AcceptWork`: dry run plan text, no-merge, preflight failure, conflict / error / validation_failed / already / merged results with the exact log lines, fire failure after merge.
  - `CreateTask`: slug collision `-2`, `-3`; skip_plan destination; dependency resolution errors; ask-on-terminal flow through the `Terminal` port; EOF -> "input ended; nothing created".
  - Confirmation policy (`confirm`): `--yes` skips; not interactive -> refused with code-2 kind; "y"/"yes" proceeds; anything else -> declined (code-1 kind).
  - `Tick`: observe/reconcile/dispatch ordering (priority, queued_at, id), concurrency cap, `not_before`, dependency stuck rows (cycle/discarded), held map, skipped when lock held, workspace cleanup of done/discarded/missing.
  - `adr` use cases: list (accepted/all), show, accept/reject/supersede results and `AdrError.code`.
  - Config split: `load_config` returns parts with the same values as before (unit test may import `samba.config`; black-box files must not).
  Extend `tests/test_architecture.py` (step 8). Keep CLI behavior covered by the existing black-box files unchanged.
- [ ] **2. Ports in `ports.py`:** `Terminal` (`is_interactive() -> bool`, `ask(prompt) -> str` raising `EOFError` at EOF, `read_block(prompt) -> list[str]`/description until empty line, `confirm(prompt) -> bool`, `edit(initial: str) -> str | None` plus an `edit_error` message channel returned in a result rather than printed), `RepoLock` (`acquire(blocking: bool) -> context manager yielding held: bool`), `Merger` (`preflight`, `commit_count`, `merge(branch, message, validate: bool) -> MergeResult`; log path built inside), `Workspaces` (`existing_ids`, `remove`), `Adrs` (`load_all`, `find`, `set_status`, `supersede`, `parse_number`). Define `MergeResult` and error types in `domain` or `ports` (plain data, no Path: `log_path: str | None`).
- [ ] **3. Split `Config` (`config.py`).** New frozen dataclasses: `Policy` (`max_turns`, `max_attempts`, `retry_base_s`, `max_retry_backoff_s`, `max_cost_usd_per_task`, `reflect_on_give_up`, `require_plan`, `max_concurrent`, `poll_interval_s`), `AgentSettings` (existing `ClaudeConfig` + `PlanningConfig` minus `require_plan`), `Layout` (`repo`, `samba_dir`, `workspaces_root`, `base_branch`), `Prompts` (`template`, `overrides`), plus `Validation` (command, timeout, tail lines, `shell`) and `Hooks` (`after_create`, timeout). `Config` becomes a composite of these plus `warnings`. Update `load_config`, `orchestrator.py`, `workspace.py`, `adapters/claude_cli.py` (takes `AgentSettings`, no `PlanningConfig.require_plan`) and `views.py`. `DEFAULT_ALLOW` / `DEFAULT_PLANNING_ALLOW` stay in `config.py`. Pure refactor: run the full suite.
- [ ] **4. Adapters for the new ports:** `adapters/terminal.py` (`StdTerminal`: `isatty` of stdin and stdout, `print(prompt, end="", flush=True)` + `readline`, the exact `[y/N]` prompt text, the `$EDITOR`/`$VISUAL`/`vi` temp-file editor, moved from `_edit_feedback`/`_edit_answer`), `adapters/repo_lock.py` (wraps `lock.repo_lock`), `adapters/git_merger.py` (wraps `merge.py`), `adapters/git_workspaces.py` (wraps `workspace.Workspaces`), `adapters/adr_files.py` (wraps `adr.py`). Do not move `merge.py`, `lock.py`, `workspace.py` or `adr.py` in this refactor part: leave them where they are and wrap them (the git ones move in part 7; `git mv` is not in the allow list). Update the `CLAUDE.md` map.
- [ ] **5. Use cases in `app/`:**
  - `app/change_state.py`: `legal_events(task, ...)` / `check_legal(tasks, task_id, event, label) -> Legal | NotAllowed | NoFile` (the single legality check replacing the three copies), and `ChangeState.run(...)` implementing the command pattern: legality, feedback (optional/required), confirmation hook through the `Terminal`, lock, re-check, write feedback, `Machine.fire`. Returns `StateChanged(location, hint_cause)` or `Refused(kind, message)`. Keep message strings identical, including the `blocked_cause` retry hint (`_retry_hint` moves here as `retry_hint(cause)`).
  - `app/confirm.py`: the confirmation policy (`--yes`, non-interactive -> refused "needs confirmation: run it on a terminal or pass --yes; nothing changed" with code-2 kind, `[y/N]`, declined -> "not confirmed; nothing changed", code-1 kind), using `Terminal`. Order stays: after the legality check, before the lock.
  - `app/answer_question.py`: `AnswerQuestion` (check, editor via `Terminal.edit` with the `# ` quoting built in the use case, re-check under lock, `answer_question`, log line, fire when round done). Result carries `still_open` for the stderr note.
  - `app/accept_work.py`: `AcceptWork` using `Merger`, `RepoLock`, `Machine`, `Terminal` (dry-run fields, plan text, confirm, merge, per-status log lines and messages, fire). Returns `Accepted`, `DryRun(lines)`, or `Refused`.
  - `app/create_task.py`: `CreateTask` with `slugify` via `TaskId.slug`, collision loop, dependency resolution (move `_resolve_deps`; `resolve_task_id` is in `views.py`, a read-only helper; either move the resolver into `app/resolve.py` or leave it and let `app/` import it only if `views.py` is pure, otherwise move it and re-export), the interactive prompts through `Terminal`.
  - `app/adr.py`: `ListAdrs`, `ShowAdr`, `SetAdrStatus`, `SupersedeAdr` over the `Adrs` port returning rows/text/written paths as `str`.
  - `app/tick.py`: `Tick` use case with the decision logic of `observe`, `reconcile`, `dispatch`, `_deps_ready`, cleanup, taking `Tasks`, `Clock`, `RepoLock`, `Workspaces`, `Machine`, `Policy` and a `spawn(task) -> None` callback (the orchestrator's worker creation). The orchestrator keeps `running`, workers, startup and shutdown, and calls `Tick.run()`; `_note`/`pending_notes` move with it or stay behind a small `Notes` object injected into both.
  - Read-only commands (`task list/show`, `question list/show`) become thin use cases (`ListTasks`, `ShowTask`, `ListQuestions`, `ShowQuestion`) returning rows/lines, so the CLI has no logic like `_split_target` or the question block formatting; `views.py` stays for renderers (make it clock-free if it moves into `app/`, otherwise keep it in the adapter side).
- [ ] **6. Composition root `src/samba/compose.py`** (or `adapters/root.py`): `build(repo: Path) -> Services` reads `load_config`, builds `MarkdownTasks` once, `SystemClock`, `UuidGenerator`, `ClaudeCliRunner`, `StdTerminal`, lock, merger, workspaces, `Machine`, and every use case; plus `build_adr(repo)` for the config-free ADR commands. Replace the eight `MarkdownTasks(...)`/`_store` constructions in `cli.py` and the defaults in `Orchestrator.__init__` (it then requires its ports; tests pass fakes) with it. Nothing outside the root constructs an adapter. `cmd_run` keeps `_setup_logging` and signal handling in the adapter.
- [ ] **7. Rewrite `cli.py`** (it stays at `src/samba/cli.py` as the CLI adapter, so `samba.cli:main`, the `pyproject` scripts and `python -m samba` keep working; moving a file needs `git mv`, which is not in the allow list): argparse tree unchanged (all help strings, flags, `--repo`), `main` calls `build`, then each command builds a request, calls the use case, prints `result.messages` to stdout/stderr, and returns the exit code derived from the result kind (`ok` 0, `refused` 1, `usage` 2). Config errors still print `samba: config error: ...` exit 2. No rule left: no `human_events`, no `merge.*`, no slug, no questions logic, no `Machine`.
- [ ] **8. `tests/test_architecture.py`:** extend `APP_MODULES` with every new `app/*.py` module; add a `test_app_modules_import_no_io` asserting `app/` imports none of `subprocess`, `os`, `pathlib` (asyncio and logging allowed), keep the "no adapter import" and "no direct clock/uuid" and storage-vocabulary checks, add a test that the scanner flags `import os` in a temp module; update `test_the_old_task_store_is_gone_and_the_adapter_is_used` so only the composition root imports `samba.adapters.markdown_tasks` (and assert `cli.py`/orchestrator do not import any adapter other than through the root); add a test that `MarkdownTasks(` appears only in the composition root.
- [ ] **9. Spec and docs (same change):** `docs/spec/cli.md` command pattern points at `ChangeState`, `AcceptWork`, `AnswerQuestion`, `CreateTask` and the confirmation policy now "on the `Terminal` port"; `docs/spec/architecture.md`: new ports in the Ports table, the composition root (replace "until it exists" passages), the split config, the "Not yet behind a port" list updated (terminal, git/merge, lock, workspaces moved; subprocess helpers and worker execution remain), the architecture test paragraph; `docs/spec/workflow-config.md` if it names config groups; `CLAUDE.md` map (new modules); `docs/spec/README.md` only if chapter blurbs change. No em-dashes in prose.
- [ ] **10. Final checks:** `uv run pyright` (0 errors), `uv run pytest -q`; confirm `git grep -nE "print\(|sys\.stdin|human_events|merge\." -- src/samba/app` is empty and the CLI adapter has no rule (use `git grep`: plain `grep` is not in the allow list); add the `## Log` entry listing any black-box test changes (target: none) and the spec details settled.

### Files to change

- New: `src/samba/app/{change_state,confirm,answer_question,accept_work,create_task,tick,adr,queries}.py`, `src/samba/adapters/{terminal,repo_lock,git_merger,git_workspaces,adr_files}.py`, `src/samba/compose.py`, `tests/fake_terminal.py`, `tests/fake_merger.py`, `tests/test_app_use_cases.py`.
- Edit: `src/samba/ports.py`, `config.py`, `orchestrator.py`, `workspace.py`, `adapters/claude_cli.py`, `views.py`, `cli.py` (shrinks to a shim or is moved), `tests/test_architecture.py`, `tests/conftest.py` only if it builds a Config, `docs/spec/{cli,architecture,workflow-config}.md`, `CLAUDE.md`, `pyproject.toml` only if the entry point path changes.
- No file moves in this refactor part: `cli.py`, `merge.py`, `lock.py`, `workspace.py` and `adr.py` stay where they are.

### Risks

- **Message/exit-code drift:** many exact strings and exit codes (1 vs 2) are spread over `cli.py`. Mitigate by copying strings verbatim into result objects, keeping each command's black-box tests unchanged, and diffing stderr in a few manual runs.
- **Ordering of effects:** confirmation is after the legality check and before the lock; feedback is saved before `fire`; the editor runs before the lock. Preserve exactly, and cover in the in-process tests.
- **The tick vs the orchestrator:** `dispatch` spawns asyncio workers and records `Running`; extracting it risks changing timing. Use a `spawn` callback and keep `running` in the orchestrator; `pending_notes`/`_note` is shared state, so inject one holder into both. If this grows, split the tick into its own follow-up subtask (see below) rather than risk the suite.
- **Architecture constraints:** `app/` and `ports.py` may not use `os`/`pathlib`/`subprocess` or the words `Path`, `mtime`, `sidecar`, `front matter`; ports must carry strings. `views.py` reads `time.time` (flagged in the spec): either keep it adapter-side or inject the clock if a use case needs it.
- **`Config` split fan-out:** about 60 references in `orchestrator.py` plus workspace, claude adapter and views; mechanical but wide. Do it as its own green commit before touching use cases.
- **ADR commands have no WORKFLOW.md:** the composition root must not require config for them (existing test expects that).
- **Orchestrator constructor default removal** could break test helpers that build `Orchestrator(config)`; grep showed none import samba internals in black-box files, but check `tests/test_*` that do (test_tasks_port, test_agent_port, test_scenarios).

### How to verify

- `uv run pyright` reports 0 errors.
- `uv run pytest -q` passes, including the unchanged `tests/test_blackbox.py`, `test_cli_surface.py`, `test_manual.py`, `test_work_accept.py`, `test_task_new.py`, `test_questions.py`, `test_adr.py`, and the new in-process use case tests and architecture tests.
- `git diff --stat -- tests/test_blackbox.py` is empty (or the change is justified in `## Log`).
- `git grep` checks (plain `grep` is not in the allow list): no `print(`, `sys.stdin`, `sys.stdout`, `input(` in `src/samba/app/`; no adapter import in `app/`; `MarkdownTasks(` only in the composition root; `src/samba/cli.py` contains no `human_events`, `merge.`, `TaskId.slug`, `Machine`.
- The black-box suite is the behavior check: it asserts on the exact messages and exit codes. Do not run `samba run` or `work accept` yourself: they are not in the allow list.

### Suggested subtasks

1. Config split + `Layout`/`Policy` (pure refactor, no behavior).
2. `Terminal` port + adapter + confirmation policy + `ChangeState` (cmd_transition, retry/stop/discard/plan/work reject) and the single legality check.
3. `AnswerQuestion`, `AcceptWork` (+ `Merger`, `RepoLock` ports) and `CreateTask`.
4. ADR use cases and read-only query use cases.
5. `Tick` extraction from the orchestrator.
6. Composition root, `adapters/cli.py`, architecture test and spec/CLAUDE.md update (depends on 1 to 5). If executed as one task, follow this order and commit per step.

## Assumptions
- The black-box suite (tests/test_blackbox.py and the other CLI-level tests) imports no `samba.cli`/`samba.config` internals (grep of tests/ for `samba.cli|samba.config|Config(|load_config|cmd_` found nothing), so refactoring those is free; the only text/behavior contracts are stdout/stderr messages and exit codes.
- "The tick" moves as the *decision part* (observe, reconcile, cleanup, dispatch ordering and dependency firing). Worker execution (`_work`, `_validate`, `_setup`, prompts, git/shell) stays in `orchestrator.py` as the adapter-side runner, with the worker spawn, the repo lock and workspaces reached through ports/callbacks. Moving the whole 700-line orchestrator is out of scope.
- Use cases may not use `os`, `subprocess` or `pathlib`, and `app/`+`domain/` code may not contain the word `Path` (storage-vocabulary check). So paths cross ports as `str` or are built inside the adapter (e.g. the accept-validate log path is derived by the Merger adapter from the task id).
- Ports are Protocols in `ports.py` (single file, as today); new ones: `Terminal`, `RepoLock`, `Merger`, `Workspaces` (subset the tick needs), `Adrs`. `ports.py` is in DOMAIN_MODULES so it must stay free of os/pathlib too.
- `Config` split keeps `load_config(repo) -> Config` returning a composite whose parts are separate frozen dataclasses (`Policy`, `AgentSettings`=existing `ClaudeConfig`+`PlanningConfig` models/allow, `Layout`, `Prompts`, plus `Validation`/`Hooks`/`Runtime` for the leftovers). `DEFAULT_ALLOW` stays in config.py.
- `adr` use cases take the repo root as an opaque `str`/via the `Adrs` port, so `adr.py` becomes (or is wrapped by) an adapter and `app/adr.py` returns result objects; `adr` needs no WORKFLOW.md, so the composition root has a second entry (`build_adr_services(repo)`) that does not read config.
- Exit codes are kept by having the CLI adapter map result/error types to codes (1 vs 2) exactly as today; the use-case errors carry a `kind` ("usage" -> 2, "refused" -> 1).

## Log
- 2026-11-10 20:41 samba: dispatch_work: work-todo -> work-running
- 6a done: Config is now a composite (Policy, AgentSettings, Layout, Prompts, Validation, Hooks + warnings). `shell` lives in Validation; planning model/allow are `AgentSettings.planning_model/planning_allow`; `require_plan` is in Policy. Workspaces takes (Layout, Hooks, shell); ClaudeCliRunner/build_argv take AgentSettings. views.py had no Config use. Added tests/test_config.py. Spec notes in architecture.md and workflow-config.md. No black-box test changes. pyright 0 errors, 550 tests pass.
- 2026-11-10 20:46 samba: permission denied: Bash (cat > <tmp>/edit_config.py <<'EOF'
import re,sys
p=sys.argv[1]
s=open(p).read()
a=s.index("@dataclass(frozen=True)\nclass)
- 2026-11-10 20:49 samba: done: work-running -> work-review: validation passed (turns 1, $0.69): Config is now a composite of frozen Policy, AgentSettings, Layout, Prompts, Validation and Hooks (plus warnings). The orchestrator, Workspaces and the claude adapter use only the parts they need. `views.py` never used Config, so it is unchanged. Added `tests/test_config.py` and spec notes in architecture.md and workflow-config.md. pyright reports 0 errors and all 550 tests pass, with no black-box test changes.
- 2026-11-10 20:53 samba: work.accept: work-review -> done: merged c147222, validated
