---
priority: 3
---
# Implement ADRs 0017 and 0018: the domain takes values, the ports live with the use cases

Read CLAUDE.md, docs/spec/architecture.md and ADRs 0011, 0016, 0017 and 0018 first. ADR 0017
decides that the domain takes values, never capabilities, and that time arrives as a `Now` value.
ADR 0018 decides that every port lives in `app/ports.py` and that `domain/ports.py` is removed.
This task implements both. It is a pure refactor: task files, sidecars, `## Log` lines, question
timestamps and every CLI output stay byte-for-byte the same. pyright stays at 0 errors and the
checks in CLAUDE.md stay green: the fast levels while working (`uv run pytest -q tests/unit
tests/component tests/checks`), `uv run pytest -q tests/integration` as well because adapters
change, and the full run is the validation Samba runs itself when you report done. Plan steps may
use only commands in the WORKFLOW.md allow list: git grep rather than grep, git mv and git rm are
allowed (the target directory must exist: create it by writing a file in it, there is no mkdir),
no sed -i, no pipes or redirects, no uv add, uv lock, uv sync or uv run python; uv run pytest with
options is fine. If the work is too big for one run at the per-task cost cap, propose two chained
subtasks in the plan, part A then part B. The order matters: until the domain takes values, moving
`Clock` out of `domain/` would make the domain import `app/`.

**Part A: time as a value (ADR 0017).**
- Add `domain/now.py`: a frozen dataclass `Now` with `time: float`, `iso_seconds: str` and
  `log_stamp: str`, preformatted by the adapter so the domain still imports no `datetime`. List it
  in `DOMAIN_MODULES` of the architecture test. `monotonic` is not part of `Now`: it measures
  durations in workers and adapters and is never persisted; it stays on the port only.
- The `Clock` port gains `now() -> Now`. `SystemClock` and `tests/fakes/fake_clock.py` implement
  it; the ad hoc clocks in `tests/unit/test_task_domain.py`, `tests/integration/test_tasks_port.py`,
  `tests/component/test_app_startup.py` and `tests/component/test_app_run_task.py` either gain
  `now()` or are replaced by the shared fake where the level allows (unit tests import no fake,
  ADR 0016: they build `Now(...)` directly, which is the point of the change).
- Every domain function that took a `Clock` takes a `Now`: `Task.create`, `add_questions`,
  `answer_question`, `dismiss_open` on the aggregate and in `domain/questions.py`; in
  `domain/transitions.py` the `Effect` signature, the effects, `apply_row`, `log_line` and
  `entry_line`. After this step no domain module imports `samba.domain.ports`.
- Use cases read the clock once per operation and pass the value down: `Machine.fire` and
  `Machine.observe` call `clock.now()` once and use that `Now` for the row effects and the log
  line, so a step that answers one question and dismisses the rest stamps both with one instant.
  Do the same in `AnswerQuestion`, `CreateTask`, `TurnFlow`, `Tick` and the queries where they
  build timestamps or log lines. Workers keep `clock.monotonic()`.

**Part B: the ports live with the use cases (ADR 0018).**
- New `app/ports.py` holds every port with its value types and errors: `Clock`, `IdGenerator`,
  `Tasks` with `StoreError` and `TaskExists`, `Terminal` with `EditResult`, `Lock`, `Vcs` with
  `Workspace`, `WorkspaceError`, `MergeAttempt`, `MergeAttemptStatus` and `CommitResult`,
  `Validator`, `Journal`, `Adrs` with `AdrError` and `AdrInfo`, `InteractiveSession` with
  `LaunchError`, and `AgentRunner`. It imports the domain types it is written over plainly, with
  no `TYPE_CHECKING` block: nothing imports it back.
- `git rm src/samba/domain/ports.py`. Update every importer, listed by
  `git grep -l "samba.domain.ports"`: the use cases, the adapters, `entrypoints/`, `bootstrap.py`,
  `tests/fakes` and the tests.
- `tests/checks/test_architecture.py`: remove `domain/ports.py` from `DOMAIN_MODULES`, add
  `app/ports.py` to `APP_MODULES`, and add three rules, each with a case showing it catches a
  violation, in the style of the existing checks: no domain module imports `samba.app` (today the
  domain rule forbids only I/O modules and adapters); an adapter's imports from `samba.app` are
  `samba.app.ports` and nothing else (today nothing limits adapters here); and
  `src/samba/domain/ports.py` does not exist and `samba.domain.ports` is imported nowhere. Keep
  every existing rule passing (no `datetime`, `pathlib` or `yaml` in the domain, no storage
  vocabulary, no `asyncio` in app, every domain and app module listed).

**Docs, in the same change.**
- `docs/spec/architecture.md`: the Ports row of the Layers table (it still justifies the location
  by the dependency ADR 0017 removes), the Dependency rule paragraph (the new edge from adapters to
  `app/ports.py`, and that the domain imports nothing from `app/`), the Ports table (every port in
  `app/ports.py`), the description of the architecture test that says `DOMAIN_MODULES` holds
  `domain/ports.py`, and the paragraph "The clock is threaded through ...", which becomes: the use
  cases read the clock once per operation and the domain takes a `Now` value.
  `git grep -n "domain/ports\|domain.ports\|Clock" docs/spec CLAUDE.md` finds every other mention,
  including the `running-claude` chapter's pointer to `AgentRunner`.
- `CLAUDE.md` map: the `domain/ports.py` line becomes an `app/ports.py` line, and the `domain/`
  list gains `now.py`.

**Done when.**
- `git grep -l "samba.domain.ports"` prints nothing and `src/samba/domain/ports.py` does not exist.
- No `Clock` parameter remains in `src/samba/domain/`, and no domain module imports `samba.app`.
- `uv run pyright` reports 0 errors; the fast levels and `tests/integration` are green; the full
  run, which Samba runs as validation, passes with no change to any expected file content or output.
- The architecture test enforces the three new rules, and the spec and CLAUDE.md describe the new
  layout.

## Plan
### Approach

Pure refactor; no file content or CLI output changes. Two parts, in this order, because until the domain takes values, moving `Clock` out of `domain/` would make the domain import `app/`. With no sed and no pipes, B's import edits are ~48 individual Edits, so I propose **two chained subtasks, A then B** (see the end). Each ends green on its own.

Part A (ADR 0017): `Now` becomes a domain value. `SystemClock.now()` preformats `iso_seconds` and `log_stamp`, so the domain still imports no `datetime`. Use cases call `clock.now()` once per operation and pass the value down. `monotonic()` stays on the port only, and workers keep it. The `Clock` Protocol keeps `time()` and `monotonic()` and gains `now() -> Now`; I'll drop `iso_seconds()` and `log_stamp()` from the port only if no non-domain caller remains. `MarkdownTasks` uses `clock.time()` for `updated_at`, which is fine to keep.

Part B (ADR 0018): create `app/ports.py` with every port moved verbatim from `domain/ports.py`, with plain imports and no `TYPE_CHECKING`. Then `git rm src/samba/domain/ports.py`, retarget all importers, and add the three architecture rules.

### Steps

### Part A: time as a value
- [ ] Read `docs/spec/architecture.md`, ADRs 0011, 0016, 0017 and 0018 with `Read` on `docs/adr/*.md`. `samba adr show 17` and `18` returned "unknown ADR" here, so the files may be missing from this worktree; check `docs/adr/` and fall back to the task text if so.
- [ ] Tests first:
  - `tests/unit/test_task_domain.py`: replace the ad hoc clock with `Now(time=..., iso_seconds=..., log_stamp=...)` built directly. Unit tests import no fake. Cover `Task.create`, `add_questions`, `answer_question` and `dismiss_open`.
  - Add a unit case that answering one question and dismissing the rest, with one `Now`, stamps both with the same `answered_at`.
  - Component: assert `Machine.fire` and `Machine.observe` read `clock.now()` once. Make `FakeClock` count `now()` calls, or return a changing value, and check the row effects and the log line share one instant.
- [ ] Add `src/samba/domain/now.py`: `@dataclass(frozen=True) class Now: time: float; iso_seconds: str; log_stamp: str`.
- [ ] Add `Now` to `DOMAIN_MODULES` in `tests/checks/test_architecture.py`.
- [ ] Update `Clock` in `domain/ports.py` (temporarily): add `now() -> Now`.
- [ ] Implement `SystemClock.now()` in `adapters/system.py`: read `self.time()` once and format both strings from it. Use `datetime.fromtimestamp(t).astimezone().isoformat(timespec="seconds")` and `strftime("%Y-%m-%d %H:%M")`, exactly as today, so output is byte-identical.
- [ ] Update `tests/fakes/fake_clock.py`: add `now()` returning `Now(self.now, FAKE_ISO, "2026-01-01 00:00")`. Keep `time()` and `monotonic()`.
- [ ] Update the ad hoc clocks:
  - `tests/integration/test_tasks_port.py`, `tests/component/test_app_startup.py` and `tests/component/test_app_run_task.py` either gain `now()` or are replaced by `FakeClock`.
  - The unit one builds `Now` directly instead.
- [ ] Domain signatures take `Now`:
  - `domain/questions.py`: `add_questions`, `answer_question` and `dismiss_open` take `now: Now` and use `now.iso_seconds`.
  - `domain/task.py`: `Task.create` takes `now` (`queued_at=now.time`), and `add_questions`, `answer_question` and `dismiss_open` take `now`.
  - `domain/transitions.py`: `Effect = Callable[[Task, Ctx, Now], None]` and all effects take `_now: Now`.
  - `_retry_delay` and `_first_dispatch` use `now.time`; `_dismiss_open` passes `now` on.
  - `log_line(message, now)` uses `now.log_stamp`; `entry_line(row, message, now)`; `apply_row(row, task, ctx, now)` stamps `queued_at = now.time`.
  - Drop `from samba.domain.ports import Clock` from all three modules, replacing it with `from samba.domain.now import Now`.
- [ ] Use cases, one `now = self.clock.now()` per operation:
  - `app/machine.py`: `fire` and `observe` read it once, use it for `apply_row` and `entry_line`.
  - `app/answer_question.py`: one `now` for `answer_question`, the dismissals and `log_line`.
  - `app/create_task.py`: `Task.create(..., now)`.
  - `app/turn.py`: `log_line` for `permission denied` and `add_questions`.
  - `app/tick.py`: the `log_line` at about line 127; its `clock.time()` comparison for dispatch stays or becomes `now.time`.
  - `app/queries.py`: `now = self._clock.time()` becomes `self._clock.now().time` where a display age is built.
  - Workers keep `clock.monotonic()`.
- [ ] Fix every test call site that passes a clock to a domain function: use `git grep -n "add_questions\|answer_question\|dismiss_open\|Task.create\|apply_row\|log_line\|entry_line" tests src`.
- [ ] Spec for A: see Spec changes.
- [ ] Run `uv run pyright`, then `uv run pytest -q tests/unit tests/component tests/checks`, then `uv run pytest -q tests/integration`.

### Part B: ports live with the use cases
- [ ] Tests first: in `tests/checks/test_architecture.py`:
  - Remove `domain/ports.py` from `DOMAIN_MODULES` and add `app/ports.py` to `APP_MODULES`.
  - Add `domain_app_imports(path)`: any `samba.app` or `samba.app.*` import in a domain module. Test: `test_domain_imports_nothing_from_app`, plus a tmp_path case catching `from samba.app.ports import Clock` and `import samba.app`.
  - Add `adapter_app_violations(path)`: imports from `samba.app` other than exactly `samba.app.ports`, run over `SRC/adapters/**/*.py`. Test: a tmp_path case catching `from samba.app.machine import Machine` while `from samba.app.ports import Tasks` passes.
  - Add `test_domain_ports_is_gone`: `src/samba/domain/ports.py` does not exist, and no `.py` under `src` or `tests` imports `samba.domain.ports`, scanning with `imported_modules`. Also give it a tmp_path catch case.
  - These fail until the code is moved, which is expected.
- [ ] Create `src/samba/app/ports.py` with every class from `domain/ports.py`, verbatim: `StoreError`, `TaskExists`, `Clock` (with `now()`), `IdGenerator`, `Tasks`, `EditResult`, `Terminal`, `Lock`, `WorkspaceError`, `Workspace`, `MergeAttemptStatus`, `MergeAttempt`, `CommitResult`, `Vcs`, `Validator`, `Journal`, `AdrError`, `AdrInfo`, `Adrs`, `LaunchError`, `InteractiveSession`, `AgentRunner`.
  - Plain imports from `samba.domain.now`, `agent`, `launch`, `validation`, `states`, `task` and `task_id`, with no `TYPE_CHECKING`.
  - The module must pass the APP_FORBIDDEN rules: no `asyncio`, no `os`, no `pathlib`. `contextlib.AbstractContextManager` is fine.
- [ ] `git rm src/samba/domain/ports.py`.
- [ ] Retarget every importer, found with `git grep -l "samba.domain.ports"` (about 48 files), editing each import line to `samba.app.ports`:
  - **app:** accept_work, adr, answer_question, change_state, completion, confirm, create_task, explore, finish, guard, machine, prompt_builder, queries, resolve, run_task, startup, tick, turn.
  - **adapters:** `__init__`, adr_files, adr_format, claude_cli, git_vcs, interactive_session, markdown_tasks, terminal.
  - **entrypoints:** orchestrator, workers.
  - **root:** bootstrap.
  - **fakes:** fake_adrs, fake_session, fake_tasks, fake_terminal, fake_vcs.
  - **tests:** test_app_queries, test_app_startup, test_app_use_cases, test_app_accept_create, test_question_rounds, test_agent_port, test_scenarios, test_tasks_port, test_adr_store, test_lock_port, test_adapters_vcs_validator_journal.
  - Keep each file's import ordering consistent.
  - Also check docstrings and comments that mention `domain/ports`, and `adapters/__init__.py`.
  - Because the architecture test allows adapters only `samba.app.ports` from `samba.app`, verify no adapter imports another `samba.app` module. If one does (for example `adr_files` or `adr_format`), move the type it needs into `app/ports.py`, or pass it as a value, rather than loosening the rule.
- [ ] Verify the rest of the Done-when checks:
  - `git grep -l "samba.domain.ports"` prints nothing.
  - `git grep -n "Clock" src/samba/domain` prints nothing.
  - `git grep -n "samba.app" src/samba/domain` prints nothing.
- [ ] Docs, see Spec changes.
- [ ] Run `uv run pyright`, `uv run pytest -q tests/unit tests/component tests/checks`, `uv run pytest -q tests/integration`. Do not run e2e yourself.
- [ ] Log in the task file's `## Log` what spec changed. No Co-Authored-By trailer or other attribution in commit messages.

### Files to change
- **New:** `src/samba/domain/now.py`, `src/samba/app/ports.py`.
- **Deleted:** `src/samba/domain/ports.py`.
- **Domain:** `domain/task.py`, `domain/questions.py`, `domain/transitions.py`.
- **App (A):** `machine.py`, `answer_question.py`, `create_task.py`, `turn.py`, `tick.py`, `queries.py`. All other app files change in B for the import only.
- **Adapters, entrypoints and root:** `adapters/system.py` (A), then all importers listed in B, `bootstrap.py`.
- **Tests:**
  - `tests/checks/test_architecture.py`.
  - `tests/fakes/fake_clock.py`, `fake_adrs.py`, `fake_session.py`, `fake_tasks.py`, `fake_terminal.py`, `fake_vcs.py`.
  - The tests listed in B, and `tests/unit/test_task_domain.py` (build `Now` directly).
- **Docs:** `docs/spec/architecture.md`, `docs/spec/running-claude.md`, `CLAUDE.md`.

### Spec changes
- `docs/spec/architecture.md`, Layers table (A+B): the Ports row becomes `src/samba/app/ports.py`, alongside the use cases that call them. Remove the justification "the domain's `Task` depends on the clock port"; the domain takes values (ADR 0017) and ports live with the use cases (ADR 0018). The Domain row gains `now.py`.
- Dependency rule (B): state that adapters depend on `app/ports.py` (and the domain) and nothing else in `app/`, that the domain imports nothing from `app/`, and that the ports are Protocols in `app/ports.py` (replace the sentence saying they live in `domain/ports.py`).
- Ports table (B): say every port, with its value types and errors, is in `app/ports.py`. The `Clock` row (A) lists `time()`, `monotonic()` and `now() -> Now` (preformatted `iso_seconds` and `log_stamp`), and notes `monotonic` is not in `Now`. Update the `Journal`, `AgentRunner`, `Tasks` and other rows where they imply the old location.
- The paragraph "The clock is threaded through ..." (A) becomes: use cases read the clock once per operation and pass a `Now` to the domain (`Task`, question helpers, effects, `apply_row`, `log_line`); the adapter preformats the timestamp texts; `MarkdownTasks` and `Orchestrator` still take a required clock; only the composition root builds `SystemClock`.
- Architecture-test description near line 206 (B): `DOMAIN_MODULES` no longer holds `domain/ports.py` and holds `domain/now.py`. `app/ports.py` is in `APP_MODULES`. Describe the three new rules.
- `docs/spec/running-claude.md` line 5 (B): `AgentRunner` (`app/ports.py`).
- `git grep -n "domain/ports\|domain.ports\|Clock" docs/spec CLAUDE.md` finds every other mention. Also check the `implementation-notes` chapter.
- `CLAUDE.md` map (B): the `domain/ports.py` line becomes an `app/ports.py` line (adjust its "at the domain level because `Task` uses the clock port" rationale). The `domain/` list gains `now.py`. Update the `adapters/system.py` mention if needed.

### Risks
- Byte-for-byte output: `SystemClock.now()` must format from a single `time()` read with the same format calls. The `iso_seconds` offset is local, so tests that assert it use fakes.
- The new "adapters import only `samba.app.ports`" rule may expose existing adapter imports of other app modules (for example `adr_format`, `markdown_tasks` or `claude_cli`). Fix those by moving shared types into `app/ports.py` or the domain, not by weakening the rule.
- Circularity: `app/ports.py` imports `domain.task`, so `domain.task` must no longer import ports. Part A guarantees this; check B's import order.
- Mypy and pyright strict: `Tick` or `Queries` that kept `clock.time()` may be left with unused variables. Re-run pyright.
- The test-first checks in B fail until the move is complete, which is expected.
- Budget: B alone is about 48 manual edits; hence two subtasks.

### How to verify
- `git grep -l "samba.domain.ports"` empty, and `ls src/samba/domain/ports.py` absent.
- `git grep -n "Clock" src/samba/domain` empty, and `git grep -n "samba.app" src/samba/domain` empty.
- `uv run pyright` reports 0 errors.
- `uv run pytest -q tests/unit tests/component tests/checks` and `uv run pytest -q tests/integration` are green.
- The Samba validation (`uv run pyright && uv run pytest -q -n auto`) passes with no changes to expected file contents or output, covering the e2e level.
- `tests/checks/test_architecture.py` has three new rule tests, each with a tmp_path case showing it catches a violation.
- `git grep -n "domain/ports\|domain.ports" docs CLAUDE.md` finds only ADR history, if anything.

### Suggested subtasks
1. **Part A** (ADR 0017): everything under "Part A", with the A-related spec edits (Layers Domain row, Clock port row, "The clock is threaded" paragraph, CLAUDE.md `domain/` list gaining `now.py`). `domain/ports.py` still exists and only `Clock` gains `now()`.
2. **Part B** (ADR 0018), depends on A: everything under "Part B" and its spec edits.

## Assumptions
- ADRs 0017 and 0018 could not be read via `samba adr show` (reported unknown in this worktree), so the plan follows the task text. The executor should read `docs/adr/` if the files exist.
- `iso_seconds()` and `log_stamp()` are dropped from the `Clock` port only if nothing outside the domain still calls them; the executor decides after grepping. Dropping them is optional.
- `Tick` and `queries` keep reading `clock.time()` for display and scheduling comparisons where no timestamp is built; only timestamp and log-line construction must use `Now`.
- Adapters other than `adapters/system.py` import only `samba.app.ports` from `samba.app` today. If one does not, the offending shared type moves to `app/ports.py` or the domain.
- Running as two chained subtasks fits the per-task cost cap better than one run, given about 48 manual import edits without sed.

## Log
- 2026-11-13 12:42 samba: dispatch_plan: plan-todo -> plan-running
- 2026-11-13 12:42 samba: permission denied: Bash (git grep -n "domain import\|import ports\|domain\.ports" -- src tests ':!src/samba/domain/ports.py' | git grep -c "" -- )
- 2026-11-13 12:42 samba: planned: plan-running -> plan-review: planned (turns 1, $0.35): Two chained parts: A makes the domain take a `Now` value (ADR 0017), B moves every port into `app/ports.py`, deletes `domain/ports.py` and adds three architecture rules (ADR 0018). Spec and CLAUDE.md are updated alongside each part. I'd run it as two subtasks, since B touches about 48 files by hand.
- 2026-11-13 12:54 samba: plan.accept: plan-review -> work-todo
- 2026-11-13 12:54 samba: dispatch_work: work-todo -> work-running
- Did A and B in one run (all steps done; cost was fine). `Clock` now has `time()`, `monotonic()`, `now() -> Now`; `iso_seconds()` and `log_stamp()` were dropped from the port (only `Now` carries them). `Task.create` is `Task.new` in the code. `FakeClock` attribute `now` renamed `t`, and it counts `now()` reads (`reads`); `Machine.fire` and `AnswerQuestion` read once per operation (component test added). `Tick` and queries keep `clock.time()` for comparisons. No adapter imported another `samba.app` module, so no type had to move.
- Spec changes: `docs/spec/architecture.md` (Layers Domain and Ports rows, Dependency rule, Ports intro and `Clock` row, "clock is threaded" paragraph now "use cases read the clock once and pass a `Now`", architecture-test list with the three new rules), `docs/spec/running-claude.md` (`AgentRunner` in `app/ports.py`), `CLAUDE.md` map (`app/ports.py`, `domain/now.py`). No new ADR: ADRs 0017 and 0018 already record the decisions.
- Checks: pyright 0 errors; unit, component, checks and integration levels pass (580). Full run left to Samba validation.
- 2026-11-13 13:01 samba: done: work-running -> work-review: validation passed (turns 2, $2.11): Implemented ADRs 0017 and 0018 in one run, as a single commit. The domain now takes a `Now` value, and every port, with its value types and errors, lives in `app/ports.py`; `domain/ports.py` is gone. pyright reports 0 errors and the unit, component, checks and integration levels pass (580 tests). I did not run the e2e level, so Samba's full validation is still to come. The spec and CLAUDE.md are updated and logged in the task file; no new ADR, since 0017 and 0018 already record the decisions.
- 2026-11-13 13:11 samba: work.accept: work-review -> done: merged 39d46cd, validated
