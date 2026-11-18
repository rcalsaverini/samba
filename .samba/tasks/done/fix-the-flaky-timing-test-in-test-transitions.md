---
priority: 3
---
# Fix the flaky timing test in test_transitions

tests/test_transitions.py has a test that failed once during a slow full-suite run (about 161 seconds) and passed on rerun. Find the timing assumption and remove it, without slowing the suite and without turning the test into a sleep-and-hope.

Done when you can explain the cause in the log, the test no longer depends on wall-clock timing (poll for the condition with a generous deadline, or make the fake deterministic), and the suite passes. Touch only the test side unless the cause is a real race in the code, in which case say so in the log and fix it.

## Plan
### Approach

I only read `tests/test_transitions.py` (no execution was possible while planning), so the cause is a hypothesis to confirm in step 1. The file has no explicit sleeps. Its wall-clock assumptions are all in the three tests that run a live orchestrator with `popen`:

- `retry_scenario` (used by `retry_plan:plan-running` and `retry_work:work-running`): `wait_for(...)` with the default 15s deadline from `tests/conftest.py:196`. The `retry_base_s=60` backoff is not an assumption of its own, but the row needs the retry to be recorded before the process is stopped.
- `test_human_row_out_of_running_stops_agent` (4 params): `wait_for` at 15s, then `proc.wait(timeout=30)`. The fake agent does `hang: 30`, so a slow run that does not kill the agent promptly can hit the same 30s limit. Under the `conftest.py` workflow, `stall_timeout_s: 10` and `turn_timeout_s: 30` can also fire first. A stall kill would end the run before the hand move is observed, or would give the wrong outcome.
- `test_illegal_move_of_running_task_keeps_agent_and_defers_log`: three chained `wait_for`s at 15s, and `proc.poll() is None` while the agent is hanging. If the `hang: 30` agent hits `stall_timeout_s: 10` first, the process can exit during a slow run.

In a 161s suite run, the process startup (git worktree, uv) and the poll loop are slowed several times over. A 15s deadline from a fresh `popen` is the likeliest to be missed. The stall timeout of 10s is a second candidate.

Fix on the test side only:

1. Reproduce first. Run these tests repeatedly under artificial load (for example `uv run pytest -q tests/test_transitions.py -n` if xdist is available, or several concurrent copies, or with a short `wait_for` deadline) and capture the failing assertion. That decides which of the candidates above is the real cause.
2. Remove the assumption:
   - If it is the `wait_for` deadline, raise the default in `tests/conftest.py` (for example to 60s). Polling returns as soon as the condition holds, so the suite is not slower. Alternatively pass an explicit generous `timeout=` in the three tests.
   - If it is the stall or turn timeout against `hang`, make the test config explicit: `sb.write_workflow` with `stall_timeout_s` and `turn_timeout_s` well above the hang duration, or a shorter, still-sufficient `hang` that does not depend on the stall limit. A fully deterministic option is for `fake_claude.py` to block until a file or fifo appears (a "release" step) instead of sleeping, but only do that if the stall case is real, because `fake_claude.py` is shared. It must stay standard library only.
   - Replace `proc.wait(timeout=30)` and the `proc.poll() is None` check with polled conditions that have generous deadlines.
3. If the investigation shows a real race in the code (for example the orchestrator not killing the agent after a hand move, or the illegal-move defer path), say so in the task's `## Log` and fix it in `src/samba/orchestrator.py`, with a black-box test first. Otherwise do not touch `src/`.
4. Write the cause explanation into the task's `## Log`. Say that SPEC.md was not changed, because no behaviour changed.

### Steps

- [ ] Read `tests/conftest.py` fully (`wait_for`, `stop`, `popen`, `write_workflow` defaults) and the hang/stall handling in `src/samba/claude.py` and `src/samba/orchestrator.py`.
- [ ] Reproduce the flake under load and record which assertion or timeout failed.
- [ ] Decide between a deadline change, an explicit workflow timeout, or a deterministic fake, and apply the smallest change.
- [ ] Replace fixed-duration waits (`proc.wait(timeout=30)`, `poll()` checks) with polling on the actual condition.
- [ ] Re-run the three affected tests many times (for example 20 loops) under load to confirm they are stable.
- [ ] Run `uv run pyright` (0 errors), then `uv run pytest -q` as a separate command. Check that the runtime is still about 25s.
- [ ] Add the cause and fix to the task file's `## Log`.

### Files to change

- `tests/test_transitions.py` (the three live-orchestrator tests / `retry_scenario`).
- Possibly `tests/conftest.py` (the `wait_for` default or the test workflow timeouts).
- Possibly `tests/fake_claude.py`, only if a deterministic release mechanism is chosen.
- `src/` only if a real race is found.

### Risks

- The failure cannot be reproduced locally. In that case the fix is based on the strongest candidate, and the log should say so.
- A larger `wait_for` default can hide real hangs behind slower failures. Failures that were already due to a stuck process will take longer to report, but they will still fail.
- Changing `conftest.py` affects every test file, so keep the change to deadlines only.
- Editing `fake_claude.py` must keep it standard library only, because the black-box suite is meant to be reused against a future rewrite.
- `tests/test_transitions.py` and `tests/test_manual.py` must still never import `samba`.

### How to verify

- `uv run pyright` reports 0 errors.
- `uv run pytest -q` passes in about 25s.
- `uv run pytest -q tests/test_transitions.py` repeated about 20 times under CPU load (or with an artificially slowed process start) passes every time.
- grep the changed tests for `time.sleep` and for fixed `timeout=` values that are tied to the fake's `hang`.

## Assumptions
The cause is not yet confirmed; I could not run tests during planning. I assumed the flaky test is one of the live-orchestrator ones (`retry_scenario`, `test_human_row_out_of_running_stops_agent`, `test_illegal_move_of_running_task_keeps_agent_and_defers_log`) because they are the only ones with timing dependence. I also assumed that raising a polled deadline is acceptable and that no real code race exists.

## Log
- 2026-11-08 13:46 samba: dispatch_plan: plan-todo -> plan-running
- 2026-11-08 13:46 samba: planned: plan-running -> plan-review: planned (turns 1, $0.11): Reproduce the flake under CPU load, identify which fixed timeout in tests/test_transitions.py (most likely the 15s `wait_for` deadlines and the fake's 30s `hang` against the 10s stall timeout and 30s `proc.wait`) is the assumption, and replace it with a generous polled deadline or a deterministic fake. Test-side only unless a real race is found.
- 2026-11-08 14:21 samba: plan.accept: plan-review -> work-todo
- 2026-11-08 14:21 samba: dispatch_work: work-todo -> work-running
- work: Cause (not reproduced locally; found by reading, so it is the strongest candidate): the three live-orchestrator tests (`retry_scenario`, `test_human_row_out_of_running_stops_agent`, `test_illegal_move_of_running_task_keeps_agent_and_defers_log`) raced wall-clock limits. The fake agent did `hang: 30` while the test workflow has `stall_timeout_s: 10` and `turn_timeout_s: 30`, so on a slow machine the stall kill could fire (or `proc.wait(timeout=30)` / `proc.poll() is None` be hit) before the test finished its hand move; the `wait_for` default of 15s from a fresh `popen` could also be missed. No real code race: src/ untouched.
- work: Fix, test side only, in tests/test_transitions.py: those tests poll with `GENEROUS_S = 90`, the agent hangs `HANG_S = 600`, and the workflow sets stall/turn timeouts to 900 so no timeout can fire before the test acts. Only the orchestrator stopping the agent can end the run. Polling returns as soon as the condition holds, so the suite is not slower. SPEC.md not changed: no behaviour changed. conftest.py and fake_claude.py untouched.
- 2026-11-08 14:25 samba: permission denied: Bash (python3 - <<'EOF'
import re
p='tests/test_transitions.py'
s=open(p).read()
s=s.replace('''    sb.add_task("t1", state=st)
- 2026-11-08 14:28 samba: done: work-running -> work-review: validation passed (turns 2, $0.44): I removed the wall-clock assumptions from the three live-orchestrator tests in tests/test_transitions.py: polling deadlines are now 90s, and the fake agent hangs 600s with stall and turn timeouts raised to 900s. The cause is a hypothesis from reading the code, not a reproduced failure. Pyright reports 0 errors and the full `uv run pytest -q` passes. The change is committed, and src/ and SPEC.md are untouched.
- 2026-11-08 14:37 samba: work.accept: work-review -> done: merged 106b253, validated
