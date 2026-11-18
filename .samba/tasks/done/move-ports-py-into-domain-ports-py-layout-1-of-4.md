---
priority: 3
---
# Move ports.py into domain/ports.py (layout 1 of 4)

Read CLAUDE.md, docs/spec/architecture.md and ADRs 0011 to 0015 first. Behavior does not change: the black-box suite and every other test stay green, and pyright stays at 0 errors. Update the architecture chapter, any other spec chapter that names the moved files, and the CLAUDE.md map in the same change. Plan steps may use only commands in the WORKFLOW.md allow list: no git mv, no sed -i, no mkdir, no pipes or redirects. Move a file by writing it at its new path and git rm of the old one, then fix every import with Edit (use git grep to find them, in src and in tests).

Part of the layout change recorded in the architecture chapter (not an ADR): the root of src/samba holds only the layers and the entry points. This step: ports.py becomes domain/ports.py (the domain's Task already depends on the clock port, so ports sit at the domain level). Update about 40 imports in src and tests, DOMAIN_MODULES in tests/test_architecture.py, and the docs that name ports.py. No other file moves in this task.

## Plan
### Approach

Pure relocation, no behavior change. The file content is identical except the docstring wording. Its imports (`samba.domain.agent`, `launch`, `validation`, and the TYPE_CHECKING ones) are absolute, so they stay valid. `domain/task.py`, `domain/questions.py` and `domain/transitions.py` import `Clock` from it, which is now a same-package import with no cycle: `ports` imports `task` only under TYPE_CHECKING.

Allow-list limits: no git mv, sed, mkdir, pipes or redirects. Use Read, Write, Edit, `git rm`, `git grep`. `src/samba/domain/` already exists.

### Steps

- [ ] Read CLAUDE.md, docs/spec/architecture.md, `uv run samba adr show 11` through `15`.
- [ ] Read `src/samba/ports.py` in full and Write it unchanged to `src/samba/domain/ports.py`. Optionally adjust the comment on the TYPE_CHECKING block ("the domain's Task imports Clock from here" is still true).
- [ ] `git rm src/samba/ports.py`.
- [ ] Run `git grep -n "samba.ports"` and `git grep -n "import ports"`, then Edit each hit to `samba.domain.ports`. Known hits (verify against the git grep output):
  - src/samba: `app/{accept_work,turn,confirm,answer_question,create_task,explore,resolve,queries,adr,change_state,tick,machine}.py`; `orchestrator.py` (multi-line `from samba.ports import (`); `compose.py`; `adr.py`; `adapters/{adr_files,git_vcs,claude_cli,markdown_tasks,terminal,interactive_session}.py`; `domain/{transitions,task,questions}.py`.
  - docstrings naming `samba.ports`: `domain/task.py` line 3 and `adapters/__init__.py` line 1.
  - tests: `fake_vcs.py`, `fake_terminal.py`, `fake_tasks.py`, `fake_session.py`, `test_app_use_cases.py`, `test_agent_port.py`, `test_adapters_vcs_validator_journal.py`, `test_app_accept_create.py`, `test_tasks_port.py`, `test_scenarios.py`, `test_app_queries.py`.
  - Keep import ordering sensible (isort-style: `samba.domain.ports` sorts among the other `samba.domain.*` imports); not enforced by pyright.
- [ ] `tests/test_architecture.py`: in DOMAIN_MODULES replace `"ports.py"` with `"domain/ports.py"` (put it with the other domain/ entries, keep `template.py` and `prompts.py` where they are).
- [ ] Docs:
  - CLAUDE.md map: the `ports.py` bullet becomes `domain/ports.py` (the ports, Protocols `Clock`, `IdGenerator`, `AgentRunner`, `Tasks` and the rest) and mention it in the `domain/` bullet; keep the `adapters/system.py` part of that bullet.
  - docs/spec/architecture.md: the layer table row (line 13) is `src/samba/domain/ports.py`. Reword the layers sentence at lines 18 to 19 to say ports sit at the domain level, since the domain's `Task` depends on the clock port. Line 142 (`DOMAIN_MODULES`, "which also holds `ports.py`") becomes `domain/ports.py`. Check the rest of the chapter, including the line-184 area and any layout notes, with `git grep -n "ports.py"`.
  - docs/spec/running-claude.md line 5: `ports.py` becomes `domain/ports.py`.
  - Re-run `git grep -n "ports.py"` and `git grep -n "samba.ports"` to confirm nothing is left (ADRs 0011 to 0015 do not name the file; leave accepted ADRs untouched).
- [ ] Add a line to the task file's `## Log` stating the spec and CLAUDE.md changes.
- [ ] Run `uv run pyright`, then `uv run pytest -q`, as separate plain commands.

### Files to change

Listed in the steps above: `src/samba/ports.py` (removed), `src/samba/domain/ports.py` (new), about 25 source files and 11 test files for imports, `tests/test_architecture.py`, `CLAUDE.md`, `docs/spec/architecture.md`, `docs/spec/running-claude.md`.

### Spec changes

- architecture chapter: ports live in `src/samba/domain/ports.py`; the layer table, the dependency-rule sentence and the `DOMAIN_MODULES` description are updated to match (ports are at the domain level).
- running-claude chapter: the path of the `AgentRunner` port.
- No ADR needed: the layout change is recorded in the architecture chapter, not an ADR.

### Risks

- A missed import fails at test collection. Mitigation: `git grep` for `samba.ports` and `import ports` after the edits, and the full pytest run.
- Circular import: `domain/ports.py` imports `samba.domain.agent`, `launch` and `validation` at runtime. Those must not import `ports`. Today they do not (the old file imported them too), so the cycle risk is the same as before. `domain/__init__.py` should be checked for eager imports of `task`, which would pull in `ports` early.
- `test_architecture` forbids I/O imports in domain modules. ports.py imports only `contextlib`, `dataclasses` and `typing`, which are fine.
- Black-box tests never import samba, so they are unaffected.

### How to verify

- `uv run pyright` reports 0 errors.
- `uv run pytest -q` is fully green, including `test_architecture.py::test_domain_modules_exist`.
- `git grep -n "samba\.ports"` and `git grep -n "ports\.py"` show no stale references (only `domain/ports.py`).

## Assumptions
Imports of the form `from samba.ports import ...` are the only usage (the grep found no `from samba import ports`). Docs naming `ports.py` are only CLAUDE.md, architecture.md and running-claude.md. No re-export shim at the old path is wanted, since the task says the root holds only layers and entry points.

## Log
- 2026-11-11 13:47 samba: dispatch_plan: plan-todo -> plan-running
- 2026-11-11 13:47 samba: planned: plan-running -> plan-review: planned (turns 1, $0.19): Move src/samba/ports.py to src/samba/domain/ports.py by writing the new file and git rm of the old one, then rewrite every `samba.ports` import (about 40, in src and tests), DOMAIN_MODULES, and the docs that name ports.py.
- 2026-11-11 13:48 samba: plan.accept: plan-review -> work-todo
- 2026-11-11 13:48 samba: dispatch_work: work-todo -> work-running
- Moved src/samba/ports.py to src/samba/domain/ports.py (content unchanged), fixed all imports in src and tests, DOMAIN_MODULES updated. Spec/CLAUDE.md changes: architecture chapter (layer table row, dependency-rule sentence, DOMAIN_MODULES description), running-claude chapter (port path), CLAUDE.md map (`domain/ports.py`). No ADR: layout change is recorded in the architecture chapter. pyright 0 errors.
- 2026-11-11 13:56 samba: done: work-running -> work-review: validation passed (turns 2, $0.62): Moved ports.py to domain/ports.py with every import, DOMAIN_MODULES, the architecture and running-claude chapters and the CLAUDE.md map updated. pyright reports 0 errors and all 659 tests pass.
- 2026-11-11 14:00 samba: work.accept: work-review -> done: merged 3b2ddd0, validated
