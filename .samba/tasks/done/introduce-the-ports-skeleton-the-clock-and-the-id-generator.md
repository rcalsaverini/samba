---
priority: 3
---
# Introduce the ports skeleton, the clock and the id generator

Part 1 of 7 of the refactor that ADR 0011 starts. Read docs/adr/0011 and 0012 first, and 0005, 0009 and 0010 for context. Follow them; do not re-decide them. Run `samba adr list` to see the rest.

This is a refactor in a chain of seven: behavior does not change. The black-box suite must pass unchanged; if you must change a black-box test, say why in your log. Keep pyright strict at 0 errors.

Layout decided for the whole chain: pure `src/samba/domain/`, use cases in `src/samba/app/`, ports (Protocols) in `src/samba/ports.py`, adapters in `src/samba/adapters/`. This task creates the skeleton only. Later tasks move the existing modules; do not move them here.

Scope:
- Ports `Clock` (wall time and monotonic time) and `IdGenerator` (new session ids), with system adapters in `adapters/`.
- Thread the clock through `Machine`, the transition effects (`not_before`, `first_dispatched_at`), the question helpers that stamp times (`add_questions`, `answer_question`, `dismiss_open`), `log_line`, and the orchestrator's `time.time`, `time.monotonic` and `uuid` calls. Defaults build the system adapters, so the CLI keeps working; the full composition root comes in part 6.
- `tests/test_architecture.py`: reads source files (never imports samba) and asserts that the modules listed as domain import none of os, time, datetime, uuid, subprocess, asyncio, logging, pathlib, and no adapter. The list starts with the modules that are already clean and grows as later tasks move modules in.
- A new spec chapter `architecture` (layers, the dependency rule, the ports and where each lives today) with its index line in docs/spec/README.md, and the CLAUDE.md map updated.

Done when:
- No direct `time.time`, `time.monotonic`, `datetime.now` or `uuid` call remains in the orchestrator, `transitions.py` effects or the question helpers.
- `tests/test_architecture.py` passes, and the spec step is done (the plan's "Spec changes" section).
- pyright and the tests pass.

## Plan
### Approach

Add the skeleton and thread time and ids through behind two Protocols. Defaults build the system adapters, so every existing call site keeps working and the black-box suite is unchanged. Nothing is moved. All new parameters are optional with a system default, and the composition root comes in part 6.

### Steps

- [ ] Read `docs/adr/0011` and `0012`, plus `0005`, `0009` and `0010` (run `samba adr list`), and `docs/spec/states.md` and `implementation-notes.md`.
- [ ] Write `tests/test_architecture.py` first. It never imports samba: it parses source files with `ast`.
  - It holds `DOMAIN_MODULES = ["ports.py", "template.py", "prompts.py", "deps.py"]`, with a comment that later tasks append to it.
  - For each module it asserts that no import (`import x`, `from x import`) resolves to `os`, `time`, `datetime`, `uuid`, `subprocess`, `asyncio`, `logging` or `pathlib`, or to `samba.adapters*`.
  - It asserts that each listed file exists, so a rename is noticed.
  - It asserts that `orchestrator.py` and the effect code in `transitions.py` contain no `time.time(`, `time.monotonic(`, `datetime.now(` or `uuid.` calls. The `time.sleep` for DEBUG_FIRE_DELAY is allowed.
- [ ] Create `src/samba/ports.py`. It imports only `typing`, and defines `Clock(Protocol)` with `time() -> float` and `monotonic() -> float`, and `IdGenerator(Protocol)` with `new_session_id() -> str`.
- [ ] Create `src/samba/adapters/__init__.py` and `adapters/system.py`. `SystemClock` calls `time.time` and `time.monotonic`. `UuidGenerator` returns `str(uuid.uuid4())`.
- [ ] Update `tasks.py`.
  - `now_iso(clock)` returns `datetime.fromtimestamp(clock.time()).astimezone().isoformat(timespec="seconds")`.
  - `add_questions`, `answer_question` and `dismiss_open` take a `clock: Clock` parameter. Make it a required parameter, and update the callers: `orchestrator.py` (`add_questions`), `cli.py` (`answer_question`) and the `dismiss_open` effect.
  - `SidecarStore.__init__` gets `clock: Clock | None = None`, defaulting to `SystemClock()`, and `save` uses it for `updated_at`.
- [ ] Update `transitions.py`.
  - Effects get the clock. Change the `Effect` signature to `(Sidecar, Ctx, Clock) -> None`, or build the effects as closures. `_set` and `_attempts_inc` ignore it. `_retry_delay` and `_first_dispatch` use `clock.time()`, and `_dismiss_open` passes the clock to `dismiss_open`.
  - `_apply(row, side, ctx, clock)`.
  - `log_line(message, clock=None)` defaults to `SystemClock()` and stamps with `datetime.fromtimestamp(clock.time())`. `entry_line` takes the clock as well.
  - `Machine.__init__(tasks, sidecars, guard=None, clock=None)` stores `self.clock`, and `fire` and `observe` use it.
  - Remove `import time` only if the DEBUG sleep is moved. Otherwise keep it for the sleep only.
- [ ] Update `orchestrator.py`.
  - `Orchestrator.__init__(config, clock=None, ids=None)` stores `self.clock` and `self.ids`, and passes the clock to `SidecarStore` and `Machine`.
  - Replace `time.time()` (line ~252) with `self.clock.time()`, `time.monotonic()` (~279) with `self.clock.monotonic()`, and `uuid.uuid4()` (~486) with `self.ids.new_session_id()`.
  - Pass the clock to `log_line` calls (~222, 382, 449) and to `add_questions` (~617).
  - Remove the `time` and `uuid` imports.
- [ ] Update `cli.py`. Pass a `SystemClock()` where `answer_question` and `log_line` are called (or rely on the defaults). Keep the commands working unchanged.
- [ ] Spec. Create `docs/spec/architecture.md`. It covers the layers (domain, use cases, adapters, with the target dirs `domain/`, `app/`, `ports.py`, `adapters/`), the dependency rule (inward only, ADR 0011), and the ports table (`Clock` and `IdGenerator` in `ports.py`, implemented in `adapters/system.py`). It also says where each concern lives today (task store in `tasks.py`, runner in `claude.py`, git in `workspace.py` and `merge.py`, lock in `lock.py`, terminal in `cli.py` and `views.py`), which modules `test_architecture.py` guards, and that more ports and modules arrive in the chain. Add the index line to `docs/spec/README.md`: "architecture.md: read when touching the layers, the dependency rule, ports or adapters." If `implementation-notes.md` mentions time or uuid use, adjust it. No em-dashes.
- [ ] Update the CLAUDE.md map: add `ports.py`, `adapters/system.py`, the `architecture` chapter in the spec list, and `tests/test_architecture.py` under tests. Say that it reads sources and never imports samba. Check `tests/test_manual.py`, which is unaffected because there is no new command.
- [ ] Run `uv run pyright` (0 errors) and `uv run pytest -q` separately. Add `## Log` lines to the task file: the spec step was done, and no black-box test was changed (or why one was).

### Files to change

- New: `src/samba/ports.py`, `src/samba/adapters/__init__.py`, `src/samba/adapters/system.py`, `tests/test_architecture.py`, `docs/spec/architecture.md`
- Edit: `src/samba/tasks.py`, `src/samba/transitions.py`, `src/samba/orchestrator.py`, `src/samba/cli.py`, `docs/spec/README.md`, `CLAUDE.md`, possibly `docs/spec/implementation-notes.md`

### Risks

- Timestamp format drift. `datetime.fromtimestamp(t).astimezone().isoformat(timespec="seconds")` matches `datetime.now().astimezone()...`. The log stamp `%Y-%m-%d %H:%M` is local time in both cases. Black-box tests that match on log lines would catch any difference.
- The `Effect` signature change touches the whole EFFECTS table. The module-level assertion loop must keep working, and `samba dev transitions` output must stay byte-identical, because the states chapter embeds it and a test compares them.
- Unexpected callers of `add_questions`, `answer_question` or `dismiss_open`, such as `views.py` or the tests. Grep again before editing. Black-box tests do not import samba, so only src callers matter.
- Pyright strict on the Protocols and optional defaults. Use `X | None = None` and then `clock or SystemClock()`.
- The architecture test must stay robust: use `ast`, not regex, for imports, so docstrings mentioning `time` do not trip it. The call check on `orchestrator.py` and `transitions.py` can be a simple text search that excludes comments.

### How to verify

- `uv run pyright` reports 0 errors.
- `uv run pytest -q` passes, including `test_architecture.py`, `test_manual.py` and the unchanged black-box suite.
- `grep -nE "time\.(time|monotonic)|datetime\.now|uuid" src/samba/orchestrator.py` finds nothing. In `transitions.py` and the question helpers only the sleep and the clock-based formatting remain.
- Temporarily adding `import os` to a listed module makes `test_architecture.py` fail, then revert.
- `uv run samba dev transitions` output equals the table embedded in `docs/spec/states.md`.

### Suggested subtasks

None. The change is small enough for one session.

## Assumptions
- The Clock port is minimal: `time() -> float` (wall, epoch seconds) and `monotonic() -> float`. Timestamp strings (`now_iso`, the log-line stamp) are formatted from `clock.time()`, which yields the same local-time output as today.
- `SidecarStore.save` (`updated_at`) also takes an optional clock, because it is the same kind of call. `views.py` (`time.time` for display) and `lock.py` / `claude.py` (monotonic deadlines, sleep) stay as they are. They are outside the listed scope and later tasks move them behind adapters. The architecture spec chapter will list them as "not yet behind a port".
- `DEBUG_FIRE_DELAY` and its `time.sleep` in `Machine.fire` stay for now. That is a test-only knob, and `transitions.py` is not on the domain list yet.
- The initial domain list is the modules already clean: `ports.py`, `template.py`, `prompts.py` and `deps.py`. The check inspects each module's own imports only. `deps.py` imports `samba.tasks`, which is not an adapter yet. If `deps.py` or `prompts.py` fail the check when written, drop them from the list instead of changing them.
- Tests never import samba. The architecture test parses sources with `ast` and reads the file text. It does not import the package.

## Log
- 2026-11-10 18:01 samba: dispatch_plan: plan-todo -> plan-running
- 2026-11-10 18:01 samba: planned: plan-running -> plan-review: planned (turns 1, $0.18): Add `ports.py` (Clock, IdGenerator), system adapters in `adapters/`, and thread the clock and id generator through Machine, the question helpers, `log_line` and the orchestrator with system defaults. Also add `tests/test_architecture.py`, a new `architecture` spec chapter and a CLAUDE.md map update. Behavior does not change.
- 2026-11-10 18:41 samba: plan.accept: plan-review -> work-todo
- 2026-11-10 18:41 samba: dispatch_work: work-todo -> work-running
- Work done: all plan steps implemented (ports.py, adapters/system.py, clock/ids threaded through tasks.py, transitions.py, orchestrator.py, cli.py; tests/test_architecture.py; spec chapter architecture + README index; CLAUDE.md map). Plan checkboxes done.
- Spec step done: new docs/spec/architecture.md and index line; implementation-notes needed no change.
- No black-box test was changed. pyright 0 errors; full pytest 307 passed.
- 2026-11-10 18:46 samba: permission denied: Bash (sed -i.bak -e 's/^Effect = Callable\[\[Sidecar, Ctx\], None\]/Effect = Callable[[Sidecar, Ctx, Clock], None]/' -e 's/def)
- 2026-11-10 18:49 samba: done: work-running -> work-review: validation passed (turns 2, $0.66): Added ports.py (Clock, IdGenerator), adapters/system.py, and threaded the clock and id generator through tasks, transitions, orchestrator and cli with system defaults. Added tests/test_architecture.py, the architecture spec chapter with its index line, and the CLAUDE.md map update. pyright reports 0 errors, all 307 tests passed and no black-box test was changed.
- 2026-11-10 18:52 samba: work.accept: work-review -> done: merged e22f275, validated
