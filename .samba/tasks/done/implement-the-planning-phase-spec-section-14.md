# Implement the planning phase (SPEC section 14)

Implement SPEC.md section 14 ("Planning phase (v0.2)") completely.

Acceptance criteria:

- Every black-box test listed in SPEC 14.10 exists in `tests/test_blackbox.py` (or a new
  `tests/test_planning.py` using the same `Sandbox` fixture) and passes.
- `tests/fake_claude.py` supports the step fields in SPEC 14.9 and stays standard-library only.
- The earlier sections that 14 says to update (layout, states, config, prompts, status) are updated
  in SPEC.md, so the spec stays consistent.
- All existing tests still pass, unchanged. `uv run pyright` reports 0 errors.

## Plan

- [x] Read SPEC and code
- [x] Tests first: `tests/test_planning.py` (all 11 items of 14.10 plus extras)
- [x] Config, tasks (states, sidecar, section replace), prompts, claude argv, orchestrator, cli
- [x] fake_claude `plan`/`questions` fields
- [x] SPEC updates
- [x] pyright 0 errors, pytest 51 passed

## Log

- Settled details left open by the spec are listed at the top of SPEC section 14 (idle exit waits on
  `plan/`, `last_outcome = "approved"`, `##` headings in plans demoted to `###`, `prompts.plan`
  override semantics, status shows phase in STATE column).
- Only change to existing test support: `tests/conftest.py` STATES now includes the plan states
  (existing tests unchanged). The fake's exhausted-steps default is now `{}` (done/planned by mode).
- A Bash call running a Python script to batch-edit files was denied; I redid the edits with Edit.
- 2026-11-06 22:43 symphony: permission denied: Bash (python3 - <<'EOF'
import re
p='src/symphony/config.py'
s=open(p).read()
s=s.replace('PROMPT_KEYS = ("continue", "validat)
- 2026-11-06 22:43 symphony: validation passed, moved to review (turns 1, $0.89): Implemented SPEC section 14 (plan/plan-review states, planning runs, approval/revision flow, config, `new --plan`, status phase) with 17 new black-box tests in tests/test_planning.py, the fake's `plan`/`questions` fields, and updated SPEC sections. pyright reports 0 errors and all 51 tests pass; committed on the branch.
