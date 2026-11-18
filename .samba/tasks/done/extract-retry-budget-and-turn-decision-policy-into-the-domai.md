---
priority: 3
depends_on: ["put-the-agent-behind-an-agentrunner-port"]
---
# Extract retry, budget and turn decision policy into the domain

Part 4 of 7 of the refactor that ADR 0011 starts. Read docs/adr/0011 and 0012 first, and 0005, 0008, 0009 and 0010 for context. Follow them; do not re-decide them.

Behavior does not change. The black-box suite must pass unchanged; if you must change a black-box test, say why in your log. Keep pyright strict at 0 errors. Layout: pure `src/samba/domain/`, use cases in `src/samba/app/`, ports in `src/samba/ports.py`, adapters in `src/samba/adapters/`.

Scope:
- `RetryPolicy` in the domain: given the settings and the failed attempts, either a retry with a delay or give up (today inline in `Orchestrator._fail`).
- `Budget` in the domain: cap, spent, left, exceeded (today written four times in the orchestrator).
- `decide_after_turn`: given an `AgentReport` (part 3), the task's counters and the settings, return one action: finish with an event, run validation, record questions, continue, or fail with an error. It also carries the rules for a missing outcome, a missing session and the give-up reflection.
- One turn flow shared by planning and work, replacing the near-duplicate `_plan` and `_work` in the orchestrator, as a use case in `app/` that talks to the `AgentRunner` port and the existing validation call.
- Scenarios (ADR 0012) for: the backoff table, budget cases, `decide_after_turn` for every outcome of a work run and of a plan run, a missing outcome, a missing session, and the give-up rule. Use the fake `AgentRunner` for one or two end-to-end turn scenarios.
- Add the new modules to `tests/test_architecture.py`. Update the orchestrator and running-claude chapters of the spec only where a rule was written down differently from what the code did (say so in the log if you find such a gap).

Done when:
- The orchestrator has one budget check, one place deciding the retry delay and no duplicated plan and work turn code.
- The spec step is done, and pyright and the tests pass.

## Plan
### Approach

Pull the three policy decisions out of `orchestrator.py` into pure domain code, then replace the near-duplicate `_plan` and `_work` loops with one turn flow in a new `app/` use case that drives the `AgentRunner` port. Behavior must not change: the black-box suite passes unchanged. Write the scenario JSON and runner tests first (red), then the code.

Design:

**`src/samba/domain/policy.py`** (pure, add to `DOMAIN_MODULES`)
- `Budget(cap: float | None, spent: float)` frozen dataclass: `left` (None if no cap, else cap - spent), `exceeded` (left is not None and left <= 0), plus `Budget.of(cap, side.cost_usd_total)` helper. Replaces `_budget_left` and the three `<= 0` checks (pre-invoke in work, pre-invoke in plan, and two post-invoke).
- `RetryPolicy(max_attempts, base_s, max_backoff_s)` with `decide(attempts_failed_before: int) -> Retry(delay, attempts) | GiveUp(attempts)`. Retry when `attempts+1 < max_attempts`, delay = `min(base * 2 ** (attempts_new - 1), max_backoff)`. Also expose `delay_for(attempt)`. Replaces the inline code in `_fail`.
- `decide_after_turn(report, stage, counters, settings) -> Action`, where
  - inputs: `AgentReport`, `stage` (`plan|work`), `TurnCounters(turn, budget: Budget)`, `TurnSettings(validate_enabled: bool, max_turns)`.
  - Action union of frozen dataclasses: `Fail(error)`, `Finish(event, what, summary)` (events `budget`, `done`, `planned`, `work_blocked`, `plan_blocked`), `RunValidation`, `RecordQuestions(then=Finish)` (blocked: record questions, then finish), `Continue`.
  - Rule order, copied from the code: (1) `report.failure` -> `Fail(failure.detail)`; (2) budget exceeded -> `Finish("budget", f"budget exceeded (${spent:.2f})", summary=report.summary)`; (3) work: `done` -> `RunValidation` if validate on else `Finish("done","done")`; `blocked` -> `RecordQuestions` + `Finish("work_blocked","blocked")`; `continue`/`missing` (and `planned`) -> `Continue`; (4) plan: outcome not in (planned, blocked) or empty plan -> `Fail("planning run returned no valid outcome and plan")`; planned -> `Finish("planned","planned")`; blocked -> `RecordQuestions` + `Finish("plan_blocked","blocked")`. Also expose small pure helpers: `session_reset_needed(report)` (session_missing), `should_reflect(settings, side, stage, in_running_folder)` for the give-up reflection (work stage only, `reflect_on_give_up`, session present), and the pre-invoke `budget_gate(budget) -> Finish | None`.
  - `max_turns` exhaustion becomes `Fail(f"max_turns ({n}) exhausted")` decided by a helper `after_last_turn`.
  - Missing outcome: the warning log is emitted by the use case when `report.outcome == "missing"`; the domain only returns `Continue` (work) or `Fail` (plan).

**`src/samba/app/turn.py`** (use case, imports domain and ports only)
- `TurnFlow` class (or function `run_turns`) with injected: `AgentRunner`, `IdGenerator`, a persistence interface (`save sidecar`, `append_log`, `set_section`, `render_questions`; a small Protocol `TurnStore` defined in `app/` or `ports.py`), the settings, a `validate` async callable, and a `prompts` object carrying the first/resume/continue/validate_failed prompts built by the orchestrator, plus callbacks `on_turn(n)`.
- One loop for both stages: `max_turns` turns for work, 1 for plan. Each turn: budget gate, invoke (assign session id, increment `turns_total`, build `AgentRequest` with `max_budget_usd = budget.left`, `kind`, `log_name`, accumulate cost/tokens, save), retry once on `session_missing` (clear the stage's session id, send the first prompt, no resume), log denials, call `decide_after_turn`, then execute the action: `Fail` -> return it to the caller, `Finish` -> return `Finish`, `RecordQuestions` -> record then finish, `RunValidation` -> run validate, on failure set the next prompt to `validate_failed` + tail, `Continue` -> next prompt `continue`. Returns a `TurnResult` (`Finished(event, what, summary)` or `Failed(error)`) so the orchestrator maps it to `_finish` / `_fail` (which fire the Machine rows).
- The use case keeps `kv` logs `turn_start`, `session_missing`, `turn_end`, `no_structured_output` exactly as today (grep `logfmt` use; `logging` is fine in app/).

**Orchestrator changes** (`src/samba/orchestrator.py`)
- `_work` keeps workspace ensure, sidecar branch/workspace, building variables/system prompt/first prompt and TemplateError handling per stage (plan vs work prompt building stays here or moves to a small helper), then calls the shared flow once and dispatches on its result. Delete `_plan`, the inline loop, and `_budget_left`; `_invoke` moves into the use case (the give-up reflection reuses a single-turn call of it: have the flow expose `invoke_once(...)`).
- `_fail` uses `RetryPolicy.decide` for the delay and attempt count (one place deciding the delay), and `should_reflect` for the reflection decision; the `self.tasks.state_of(...) == running folder` check stays in the orchestrator as an input boolean.
- `Running.turn` updates via the `on_turn` callback.

### Steps
- [ ] Read ADRs 0005, 0008, 0009, 0010, 0011, 0012, `docs/spec/{architecture,orchestrator,running-claude,prompts,states}.md`, and `tests/test_planning.py` / `test_agent_port.py` for how the fake runner and prompts are used.
- [ ] Run baseline `uv run pyright` and `uv run pytest -q` and note they are green.
- [ ] Create scenario files first (red): `tests/scenarios/retry.json` (kind `retry_policy`), `budget.json` (kind `budget`), `turn_decision.json` (kind `turn_decision`), and `turn_flow.json` (kind `turn_flow`, 1 or 2 scenarios with a scripted fake `AgentRunner`).
- [ ] Extend `tests/test_scenarios.py`: loaders and parametrized tests for the new kinds, add the kinds to `test_every_scenario_file_has_a_known_kind`, and keep the "no adapter, no `samba.tasks`" rule (the turn-flow scenarios use `tests/fake_agent.py` and an in-memory store, not the task store).
- [ ] Scenario content, retry: the backoff table with defaults (base 10, cap 300): attempts 1..6 -> 10, 20, 40, 80, 160, 300 (capped); `max_attempts` 3: attempts 1 and 2 retry, 3 gives up; `max_attempts` 1 gives up at once; a custom base and cap; plan and work give the same result.
- [ ] Scenario content, budget: no cap (left none, never exceeded); cap 5 spent 2 (left 3); spent equal to cap (exceeded); spent above cap (exceeded, negative left); cap 0.
- [ ] Scenario content, `turn_decision`: work with done/validate on, done/validate off, blocked with questions, blocked without questions (synthesized question stays in the use case, assert `RecordQuestions` with empty drafts), continue, missing (continue), failure (each kind), budget exceeded after a turn (with summary), budget exceeded and failure together (failure wins), `session_missing` helper, last turn exhausted; plan with planned+plan, planned without plan (fail), blocked+plan, blocked without plan (fail), missing (fail), `continue` (fail), failure, budget; give-up reflection rule: work with session and flag on -> reflect, flag off, no session, plan stage, task left the running folder.
- [ ] Create `domain/policy.py` with `Budget`, `RetryPolicy`, the Action types and `decide_after_turn` and helpers; make the domain scenarios pass.
- [ ] Create `app/__init__.py` and `app/turn.py`; implement the shared flow; make the turn-flow scenarios pass (plan run end to end; work run: continue then done with validation failing once then passing; session-missing retry).
- [ ] Rewire `orchestrator.py`: remove `_plan`, the work loop, `_invoke`, `_budget_left`; use the flow, `RetryPolicy`, `Budget`. Confirm only one budget check and one delay computation remain (`git grep -n "<= 0" -- src/samba/orchestrator.py` and `git grep -n "2 \*\*" -- src/samba/orchestrator.py` find none; use `git grep`, plain `grep` is not in the allow list).
- [ ] Update `tests/test_architecture.py`: append `domain/policy.py` to `DOMAIN_MODULES`; add `app/turn.py` (and `app/__init__.py`) to a new `APP_MODULES` list checked for no adapter imports, and include it in the "no direct clock or uuid calls" check. Add a test that `app/` modules import no `samba.adapters`.
- [ ] Spec: update `docs/spec/architecture.md` (layers table says where policy and turn flow live now, Scenarios table adds the new kinds, architecture test paragraph), and fix `orchestrator.md` Worker pseudocode / `running-claude.md` only where they differ from the code. Known candidates: the pre-invoke budget check (each turn including the first), failure taking priority over budget, the budget-exceeded log line including the run summary after a turn, and the give-up reflection also requiring the task to still be in its running folder. Say in the task `## Log` which of these were real gaps. No em-dashes.
- [ ] Update `CLAUDE.md` Map: add `domain/policy.py` and `app/turn.py` entries.
- [ ] Run `uv run pyright` (0 errors) and `uv run pytest -q` separately; confirm black-box tests are untouched (`git diff --stat tests/test_blackbox.py` empty).
- [ ] Append to the task file `## Log`: what moved, any spec gaps found, and that no black-box test changed.

### Files to change
- New: `src/samba/domain/policy.py`, `src/samba/app/__init__.py`, `src/samba/app/turn.py`
- New: `tests/scenarios/retry.json`, `budget.json`, `turn_decision.json`, `turn_flow.json`
- Edit: `src/samba/orchestrator.py`, `tests/test_scenarios.py`, `tests/test_architecture.py`
- Edit docs: `docs/spec/architecture.md`, `docs/spec/orchestrator.md` and `docs/spec/running-claude.md` (only for real gaps), `CLAUDE.md` (map), the task file `## Log`
- Possibly edit: `src/samba/ports.py` (a `TurnStore` style Protocol, if placed there rather than in `app/`), `tests/fake_agent.py` only if it needs a helper.

### Risks
- Subtle ordering changes: failure before budget; `_fail` on `TemplateError`; `Running.turn` visible in `task list`/status; the reflection turn also bumping `turns_total` and cost before `give_up` fires. Keep each as is and cover with scenarios.
- Domain purity: no `asyncio`, `logging` or `pathlib` imports in `policy.py`; float formatting for `$%.2f` must stay in one place so log lines match black-box assertions.
- Session handling mutates the sidecar before the request is sent (`turns_total += 1`, save); the flow must keep that order since the crash recovery and `task show` read it.
- The reflection turn calls the runner outside the main loop and must suppress `TemplateError` like today.
- Strict pyright: Action unions need exhaustive `match`; avoid `Any` in the store Protocol.
- Scope creep: do not move validation, workspaces, prompts or Machine into the domain; those are later parts of the chain.

### How to verify
- `uv run pyright` reports 0 errors.
- `uv run pytest -q` passes, including `tests/test_blackbox.py`, `test_planning.py` and `test_agent_port.py`, with no black-box test edited.
- `uv run pytest -q tests/test_scenarios.py tests/test_architecture.py` shows the new scenario cases and the new module checks.
- `git grep -nE "_budget_left|def _plan|2 \*\*" -- src/samba/orchestrator.py` returns nothing.
- Spec text matches the code for budget, retry delay and give-up reflection.

### Suggested subtasks
Not needed; one change set is coherent. If it grows, split as (a) domain policy plus scenarios, (b) turn use case plus orchestrator rewire plus spec.

## Assumptions
- `src/samba/app/` does not exist yet; this task creates it (`app/__init__.py`, `app/turn.py`) and adds `app/turn.py` to `tests/test_architecture.py` only for the "no direct clock/uuid" check. It is NOT in DOMAIN_MODULES, because it may import asyncio and logging.
- Domain modules may not import `asyncio`, `logging` or `pathlib`, so the use case owns all logging and I/O, and domain returns plain frozen dataclasses.
- The turn use case receives the validation call, the prompt builders and the sidecar/task persistence as injected callables or a small protocol defined in app/, and stays free of adapters. Orchestrator keeps `_validate`, `_variables`, `_prompt`, `_system_prompt`, and the Machine.
- Behavior-preserving quirks are kept exactly: the budget check runs before each invoke (every turn, including turn 1) and again after the turn, but only after a failure check; a failure takes priority over budget after a turn; budget finish after a turn carries `res.summary`, pre-invoke budget finish carries none; the session-missing re-invoke uses the first prompt and clears the session id; denials are logged once for the final report only.
- `Sidecar.questions` recording (`_ask`) and `set_section` writes stay in the orchestrator or use-case side effects executed from the returned action, not in the domain.
- A possible spec gap: running-claude says missing outcome is treated as `continue` for work; code does so. For planning, spec says missing is a failure and code agrees. Another: orchestrator Worker pseudocode checks budget only after the run while code also checks before each turn. I will check these during the spec step and record in the log only the gaps I really find.

- Decided by the reviewer after plan review: the persistence Protocol of the turn use case (`TurnStore` or similar) is interim. Part 5 replaces it with the `Tasks` port and the `Task` aggregate, so keep it as small as the flow needs (save the sidecar, append a log line, set a section, render questions) and do not design it for reuse. Verification commands fit the allow list in WORKFLOW.md (`git grep` instead of `grep`, no redirects or pipes), so no permission denial turns into a question. The task is large: if you run short of turns or budget, stop after the domain policy plus scenarios plus the orchestrator using `Budget`, `RetryPolicy` and `decide_after_turn` (part (a) of "Suggested subtasks"), commit, and say in the log that the use-case extraction (part (b)) remains.

## Log
- 2026-11-10 19:29 samba: dispatch_plan: plan-todo -> plan-running
- 2026-11-10 19:29 samba: planned: plan-running -> plan-review: planned (turns 1, $0.26): Add pure `domain/policy.py` (RetryPolicy, Budget, decide_after_turn) and an `app/turn.py` use case that replaces `_plan`/`_work`/`_invoke` duplication in the orchestrator, with new scenario kinds plus two fake-runner turn scenarios. Behavior stays unchanged and the black-box suite runs as is.
- 2026-11-10 19:30 samba: plan.accept: plan-review -> work-todo
- 2026-11-10 19:30 samba: dispatch_work: work-todo -> work-running
- Work log (agent): all plan steps done (parts (a) and (b) both). Moved: `domain/policy.py` (`Budget`, `RetryPolicy`, `should_reflect`, `budget_gate`, `session_reset_needed`, `after_last_turn`, `decide_after_turn` with the Fail/Finish/RunValidation/RecordQuestions/Continue actions) and `app/turn.py` (`TurnFlow.run` for plan and work, `TurnFlow.invoke` also used by the give-up reflection, interim `TurnStore` Protocol, implemented by `_TurnStore` in the orchestrator). Orchestrator lost `_plan`, the work loop, `_invoke`, `_ask`, `_budget_left`; `_fail` uses `RetryPolicy.decide`.
- Scenarios added: `retry.json`, `budget.json`, `turn_decision.json`, `turn_rules.json`, `turn_flow.json` (fake `AgentRunner`, in-memory store); `test_architecture.py` has `APP_MODULES` and `domain/policy.py` in `DOMAIN_MODULES`.
- Spec gaps found (real): the Worker pseudocode in `orchestrator.md` lacked the pre-turn budget check, failure winning over the budget, and the run summary in the budget line; the give-up reflection also requires the task to still be in its running folder. Fixed in `orchestrator.md`; `architecture.md` and `CLAUDE.md` updated. `running-claude.md` needed no change.
- Small deviations: prompts (`continue`, `validate_failed`, `resume`/first) are now rendered eagerly in `_setup` inside the TemplateError handler instead of lazily; configs are validated so no black-box difference. The `no_structured_output` warning stays work-only.
- No black-box test changed (`tests/test_blackbox.py` untouched). pyright 0 errors; pytest passed before the final doc edits (408 tests before the new scenarios).
- 2026-11-10 19:43 samba: done: work-running -> work-review: validation passed (turns 2, $1.19): Moved retry, budget and after-turn decisions into `domain/policy.py`. Planning and work now share one turn flow, `TurnFlow` in `app/turn.py`, which replaces `_plan`, the work loop and `_invoke` in the orchestrator. I added scenarios (including fake-runner turn flows) and architecture checks, and updated the spec and `CLAUDE.md`. pyright reports 0 errors and all 471 tests pass; no black-box test changed.
- 2026-11-10 19:46 samba: work.accept: work-review -> done: merged 37bd15c, validated
