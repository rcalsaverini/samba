---
priority: 3
depends_on: ["add-the-scenario-runner-and-move-the-transition-table-and-de"]
---
# Put the agent behind an AgentRunner port

Part 3 of 7 of the refactor that ADR 0011 starts. Read docs/adr/0011 and 0012 first, and 0005, 0006, 0009 and 0010 for context. Follow them; do not re-decide them.

Behavior does not change. The black-box suite must pass unchanged; if you must change a black-box test, say why in your log. Keep pyright strict at 0 errors. Layout: pure `src/samba/domain/`, use cases in `src/samba/app/`, ports in `src/samba/ports.py`, adapters in `src/samba/adapters/`.

Scope:
- A port `AgentRunner` in `ports.py`: `run(AgentRequest) -> AgentReport`, plus a readiness check that replaces `logged_in`.
- `AgentRequest`: prompt, session id and whether to resume, system prompt, remaining budget, kind (plan or work), and the working location as an opaque value. No provider or config types in it.
- `AgentReport`, a frozen dataclass in the domain: outcome (done, blocked, continue, planned or missing), summary, plan, assumptions, questions as drafts (text, context), permission denials, cost, input and output tokens, a failure (none, or a kind such as stalled, timeout or error with a detail), and whether the session was missing.
- `claude.py` becomes `adapters/claude_cli.py`. It keeps `build_argv`, the process handling, the stream log, the kill logic and the init logging, and it maps Claude's stream-json into an `AgentReport`. After this task nothing outside that module reads `res.init`, `res.result` or any provider field; the orchestrator uses only the report.
- The planning variant is a request kind, not a `PlanningConfig` inside the request.
- A small in-memory fake `AgentRunner` for the scenario runner (scripted reports), kept in `tests/`.
- Add the domain types to `tests/test_architecture.py`'s list, and update the running-claude chapter of the spec (the adapter boundary and the report).

Done when:
- Nothing outside `adapters/claude_cli.py` reads Claude's JSON (`init`, `result`, `structured_output`, `permission_denials`, `total_cost_usd`): the orchestrator and everything else use only `AgentReport`.
- A scenario shows a scripted report driving a decision of the orchestrator, or the plan says why that waits for part 4.
- The spec step is done, and pyright and the tests pass.

## Plan
### Approach

Pure refactor, behavior unchanged. The black-box suite (fake `claude` subprocess) must pass untouched. All Claude JSON knowledge (`init`, `result`, `structured_output`, `permission_denials`, `total_cost_usd`, `usage`, `is_error`, `subtype`, stderr "No conversation found") moves into `adapters/claude_cli.py`, which returns a provider-free `AgentReport`. The orchestrator is rewritten against `AgentRunner`/`AgentReport` only.

Design decisions (settle in this task, record in spec):
- **Domain type** `src/samba/domain/agent.py` (pure, no pathlib/asyncio): `AgentReport` frozen dataclass with `outcome: Literal["done","blocked","continue","planned","missing"]`, `summary: str` (whitespace-normalized), `plan: str`, `assumptions: str` (both stripped), `questions: tuple[QuestionDraft, ...]` (`QuestionDraft(text, context)` frozen), `denials: tuple[str, ...]`, `cost_usd: float`, `input_tokens: int`, `output_tokens: int`, `failure: Failure | None` (`Failure(kind: Literal["stalled","timeout","error"], detail: str)`), `session_missing: bool`. Convenience property `ok` = `failure is None`. Also `AgentRequest` (frozen) lives here or in `ports.py`; put it in the domain module and re-export from ports for convenience.
- **AgentRequest**: `prompt, session_id, resume: bool, system_prompt, max_budget_usd: float | None, kind: Literal["plan","work"], location: str`. `location` is an opaque `str` (the adapter turns it into a cwd `Path`; `ports.py` is in DOMAIN_MODULES so it cannot import pathlib). No `Path`, `ClaudeConfig` or `PlanningConfig`. Stream-log path and tasks dir are NOT in the request: they are adapter construction parameters (`ClaudeCliRunner(cfg: ClaudeConfig, planning: PlanningConfig, tasks_dir: Path, runs_dir: Path)`), and the adapter derives the stream-log file `runs/<task>/<NNN>.jsonl`. Because the current log name uses task id and `turns_total`, add `task_id: str` and `turn: int` to the request as opaque log keys (`run_key`), or add a single `log_name: str` field (e.g. `"<task_id>/003"`) that the adapter joins under its runs dir. Pick the single `log_name` string; document it. (Check this is the smallest change that keeps the `runs/<task>/NNN.jsonl` layout the black-box tests read.)
- **Port** in `ports.py`:
  ```python
  class AgentRunner(Protocol):
      async def run(self, request: AgentRequest) -> AgentReport: ...
      async def ready(self) -> Readiness: ...   # Readiness(ok: bool, detail: str), frozen, in domain/agent.py
  ```
  `ready()` replaces `logged_in`; the claude adapter keeps `claude auth status` and uses `repo` as cwd (constructor param `check_dir: Path`). `ports.py` importing `samba.domain.agent` is allowed (domain-to-domain).
- **Adapter** `src/samba/adapters/claude_cli.py` (create it with Write from the content of `claude.py`, then remove the old file with `git rm src/samba/claude.py`; `git mv` is not in the allow list): keep `build_argv`, `ancestor_memory_files`, `LINE_LIMIT`, `STDERR_KEEP`, process loop, kill logic, stream log writing, init logging. Keep the old `RunResult` as a private `_RunResult` (rename, underscore), including its property parsing; add `_to_report(res) -> AgentReport`. Internal `Invocation` is replaced by building argv from `(AgentRequest, tasks_dir)`: `kind == "plan"` selects `PLAN_OUTCOME_SCHEMA_JSON`, `dontAsk`, `planning.allow`, `planning.model or cfg.model`. Failure mapping must reproduce `RunResult.error()` strings exactly (they land in `## Log` and sidecar `last_error`): stalled -> `"agent stalled (no output)"`, timeout -> `"turn timeout"`, no result -> `claude exited N without a result <tail>`, `is_error` -> `claude reported an error: ...`, else `claude exited N`. `failure.detail` holds the full message; orchestrator uses `failure.detail` as the error text (keep `kind` for decisions). `ok` mapping = old `ok` (exit 0, not is_error, not timed out, not stalled). Init logging (`claude_context`, once per runner instance, replacing `Orchestrator.logged_init`), `malformed_lines` warning and `claude_stderr` debug log move into the adapter's `run` (needs `logging` and the `kv` formatter: move `kv` unchanged into a new neutral module `src/samba/logfmt.py` and import it from the adapter, from `samba/transitions.py` and from the orchestrator, so the adapter never imports the transition shell and the log line format stays identical). Duration/events are not in the report.
- **Orchestrator**: `Orchestrator(config, clock=None, ids=None, agent=None)`; default `agent or ClaudeCliRunner(...)` (same interim "optional port defaults to the adapter" rule as clock). `startup` calls `await self.agent.ready()`; error message stays `claude auth status says not logged in; run `claude auth login`. {detail}` (put that text assembly in the orchestrator from `Readiness.detail`, or keep the wording by having the adapter return the detail only; keep the message byte-identical). `_invoke` builds `AgentRequest(location=str(ws), kind="plan" if planning else "work", log_name=...)`, accumulates `report.cost_usd`, tokens, returns `AgentReport`. Replace uses: `res.session_missing`, `res.denials`, `res.ok` -> `res.failure is None`, `res.error()` -> `res.failure.detail`, `res.outcome` (`"missing"` instead of `None`; the `turn_end` log already prints `outcome or "missing"`, and the `no_structured_output` warning fires when `"missing"`), `res.summary`, `res.plan`, `res.assumptions`, `res.questions` (adapt `_ask` and `add_questions`, which take `(text, context)` pairs: pass `[(q.text, q.context) for q in report.questions]` or accept drafts). Remove `from samba.claude import ...` and the `claude_context` block. `Path` stays in the orchestrator for workspaces only.
- **No decision extraction in this task** (decided by the reviewer after plan review): part 4 designs `decide_after_turn` with `Budget` and `RetryPolicy`, and a `decide` written here would be designed twice. The orchestrator's post-run branching stays inline and unchanged. A scenario that shows a scripted report driving a decision therefore waits for part 4; say so in the task `## Log`.
- **Scenarios**: none in this task (see above).
- **Fake runner** `tests/fake_agent.py`: `FakeAgentRunner` implementing `AgentRunner`: constructor takes a list of scripted `AgentReport`s (or callable of request), records `requests`, returns them in order; `ready()` returns ok by default. Standard library only. Add a self test in `tests/test_scenarios.py` (or a small new `tests/test_agent_port.py`) that the fake satisfies the protocol and that it returns the scripted reports in order and records the requests (does not import adapters). Do not drive the orchestrator with it yet (needs part 4 or the optional `agent=` parameter: a quick in-process orchestrator test with the fake is optional and must not import adapters; skip unless cheap).
- **Tests first**: black-box suite is the guard. New tests: `tests/test_architecture.py` additions (below) and a new check that no module outside `adapters/claude_cli.py` mentions the Claude JSON fields: scan sources with `ast`/text for `structured_output`, `permission_denials`, `total_cost_usd`, `"init"` subscripting like `.init`/`res.result`, and `samba.claude` imports; fail on hits. Write that first, watch it fail, then implement.

### Steps
- [ ] Read ADRs 0005, 0006, 0009, 0010, 0011, 0012 and the `running-claude` and `architecture` spec chapters (quick skim for wording to keep).
- [ ] Run `uv run pytest -q` and `uv run pyright` for a green baseline.
- [ ] Write failing tests: `tests/test_architecture.py` (add `domain/agent.py` to `DOMAIN_MODULES`; new test that Claude JSON field names appear only in `adapters/claude_cli.py`; add `agent_runner`-related check that `orchestrator.py` does not import `samba.claude`/`claude_cli`... adapters default import is allowed like `SystemClock`, so assert only no field reads); `tests/fake_agent.py` with its self test.
- [ ] Add `domain/agent.py` (`QuestionDraft`, `Failure`, `AgentReport`, `AgentRequest`, `Readiness`). Pure: no pathlib/asyncio/logging.
- [ ] Add `AgentRunner` Protocol to `ports.py`.
- [ ] Create `src/samba/adapters/claude_cli.py` with Write (the content of `claude.py`, adapted) and remove the old file with `git rm src/samba/claude.py`; add `src/samba/logfmt.py` with `kv`; implement `ClaudeCliRunner` (`run`, `ready`), `_to_report`, private `_RunResult`, init/malformed/stderr logging; adjust imports (`samba.config`, `samba.proc`, `samba.prompts`).
- [ ] Rewire `orchestrator.py` to `AgentRunner`/`AgentReport`; remove `logged_init`; keep log lines and messages identical.
- [ ] Run black-box suite; fix any drift (do not edit black-box tests; if one must change, note why in the task `## Log`).
- [ ] Update spec: `running-claude` (new section "Adapter boundary and the report": `AgentRequest` fields, `AgentReport` fields, failure kinds and their detail strings, `ready()` replacing `claude auth status` call, planning is request kind `plan`, only `adapters/claude_cli.py` reads stream-json; adjust "Reading the stream"/"Outcome" wording so they say the adapter maps into the report); `architecture` (Ports table rows for `AgentRunner`, the new module in Where each concern lives, remove "Claude runner: `claude.py`" from the not-yet list, Architecture test paragraph and list); `orchestrator.md` pseudocode line 76 mention if it references `run_claude`; `implementation-notes` if it mentions the module.
- [ ] Update `CLAUDE.md` map (`claude.py` -> `adapters/claude_cli.py`, add `domain/agent.py`, `tests/fake_agent.py`) and check `tests/test_spec_docs.py` for any chapter checks that the new spec text must satisfy.
- [ ] `uv run pyright` (0 errors) then `uv run pytest -q`, as separate commands.
- [ ] Write the task `## Log` entry: what moved, that no black-box test changed (or why), and the spec details settled (`log_name`, opaque `location`, failure detail strings, `missing` outcome).

### Files to change
- New: `src/samba/domain/agent.py`, `src/samba/adapters/claude_cli.py` (moved from `src/samba/claude.py`), `src/samba/logfmt.py`, `tests/fake_agent.py`.
- Edit: `src/samba/ports.py`, `src/samba/orchestrator.py`, `src/samba/transitions.py` (import `kv`), `tests/test_architecture.py`, `tests/test_scenarios.py`, `docs/spec/running-claude.md`, `docs/spec/architecture.md`, possibly `docs/spec/orchestrator.md` and `docs/spec/implementation-notes.md`, `CLAUDE.md`.
- Delete: `src/samba/claude.py` (via `git rm`).
- Untouched: `tests/test_blackbox.py`, `tests/conftest.py`, `tests/fake_claude.py`.

### Risks
- **Error string drift**: `last_error` and `## Log` messages come from `RunResult.error()`; black-box tests assert on some. Map failure details to the exact old strings.
- **Log format drift**: `claude_context`, `malformed_lines`, `claude_stderr` log lines must keep their keys; `kv` moves to `logfmt.py` so the adapter does not import the transition shell.
- **Stream log path**: runs dir layout `runs/<task>/<NNN>.jsonl` and the `give_up` reflection invocation (`_fail` calls `_invoke` too) must keep working with the new request; `_invoke` increments `turns_total` before building `log_name`.
- **Planning request**: argv for plan runs (schema, `dontAsk`, allow, model fallback) must be identical; budget flag formatting `.4f` unchanged.
- **`ports.py` purity**: it is in `DOMAIN_MODULES`; no `pathlib`, hence `location: str`. `domain/agent.py` likewise must avoid forbidden imports.
- **Outcome `None` vs `"missing"`**: every `outcome is None` check must become `== "missing"`; `_plan` condition `outcome not in ("planned","blocked")` already covers it; work branch `else -> continue` must still treat missing as continue.
- **Cancellation**: cancelling the worker must still kill the process group; keep `run` a plain coroutine with the same try/finally.
- **Scope creep**: no logic moves in this task. Denial logging, the failure check and the budget check keep their current order in the orchestrator.
- Part 4 (`app/`) will move the orchestrator; keep the new constructor parameter `agent` simple so it carries over.

### How to verify
- `uv run pyright` reports 0 errors.
- `uv run pytest -q` passes, with `tests/test_blackbox.py` unmodified (`git diff main -- tests/test_blackbox.py tests/conftest.py tests/fake_claude.py` is empty).
- `git grep -nE "structured_output|permission_denials|total_cost_usd|samba\.claude" -- src tests/test_*.py` (use `git grep`: plain `grep` is not in the allow list) hits only `adapters/claude_cli.py` (and the architecture test's own pattern list).
- `tests/test_architecture.py` lists `domain/agent.py` and passes, and the fake runner self test passes.
- Manually read the updated `running-claude` and `architecture` chapters; no em-dashes in prose.

### Suggested subtasks
None needed; the work is one coherent change.

## Assumptions
- `AgentRequest.location` is an opaque `str` because `ports.py` is in DOMAIN_MODULES and may not import pathlib.
- A `log_name` string field (e.g. `<task>/003`) is added to the request so the adapter keeps writing `runs/<task>/NNN.jsonl`; the tasks dir and runs dir are adapter constructor parameters.
- The readiness check returns a small `Readiness(ok, detail)`; the orchestrator keeps the exact existing startup error message.
- Failure `detail` carries the exact old `RunResult.error()` strings so black-box assertions on logs and `last_error` still hold.
- Decided by the reviewer after plan review: no `decide` function and no `agent_decision` scenario in this task. Part 4 designs the turn decision once, together with `Budget` and `RetryPolicy`, and writes the scenarios then. Verification and file operations fit the allow list in WORKFLOW.md (`git rm` and Write instead of `git mv`, `git grep` instead of `grep`, no redirects or pipes), so no permission denial turns into a question.
- The adapter owns the `claude_context`, malformed-lines and stderr logging, with the init log emitted once per runner instance.

## Log
- 2026-11-10 19:09 samba: dispatch_plan: plan-todo -> plan-running
- 2026-11-10 19:10 samba: planned: plan-running -> plan-review: planned (turns 1, $0.26): Introduce an AgentRunner port with AgentRequest and a frozen domain AgentReport, move claude.py into adapters/claude_cli.py where all stream-json reading and failure classification lives, switch the orchestrator to the report only, and add a scripted FakeAgentRunner plus a small pure domain decision function so a scenario shows a report driving a decision.
- 2026-11-10 19:11 samba: plan.accept: plan-review -> work-todo
- 2026-11-10 19:11 samba: dispatch_work: work-todo -> work-running
- Claude: implemented. `claude.py` moved to `adapters/claude_cli.py` (`ClaudeCliRunner`, private `_RunResult`, `_to_report`); `domain/agent.py` holds `AgentRequest`, `AgentReport`, `Failure`, `QuestionDraft`, `Readiness`; `AgentRunner` in `ports.py`; `kv` moved to `logfmt.py`; orchestrator uses only the report (`agent=` optional parameter, defaults to the adapter). `tests/fake_agent.py` + `tests/test_agent_port.py` added; architecture test lists `domain/agent.py` and checks that only the adapter mentions Claude's JSON fields (`no_structured_output`, a log event name, is exempt).
- Claude: settled in spec (running-claude, "Adapter boundary and the report"; architecture): `location` is an opaque str; `log_name` is `<task id>/<turn>` and the adapter writes `runs/<log_name>.jsonl` (tasks dir, runs dir, check dir are adapter constructor args); failure detail strings equal the old `RunResult.error()`; outcome `missing` replaces `None`. No black-box test, conftest or fake_claude changed.
- Claude: no scenario with a scripted report in this task, as decided at plan review: the turn decision (`decide_after_turn`, with `Budget` and `RetryPolicy`) is designed once in part 4, and the scenarios come with it.
- 2026-11-10 19:19 samba: permission denied: Bash (sed -i '' -e 's/_structured_text/structured_text/g' -e 's/  # pyright: ignore\[reportPrivateUsage\]//' src/samba/adapter)
- 2026-11-10 19:25 samba: done: work-running -> work-review: validation passed (turns 3, $1.68): The failure was a race in the `settle` helper in `tests/test_commands.py`, not in the refactor. The task file can move between the `state_of` and `task_text` reads, so I made `settle` retry when it hits `FileNotFoundError`. `tests/test_commands.py` passes (26 tests) and pyright reports 0 errors. I did not rerun the full suite after the fix; the fix is committed.
- 2026-11-10 19:29 samba: work.accept: work-review -> done: merged ad4fa32, validated
