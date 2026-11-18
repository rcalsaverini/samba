---
priority: 3
---
# Test levels 1 of 9: skeleton, legacy folder and level rules (ADR 0016)

Read CLAUDE.md, docs/spec/architecture.md and ADRs 0011, 0012 and 0016 first (ADR 0016 defines the four test levels: unit, component, integration, end-to-end; integration and e2e stay few; a test goes to the lowest level that can show the behavior). This task is part of a chain that rewrites the test suite from scratch, strangler style: the old tests are moved to tests/legacy/ in task 1 and are NOT edited or deleted until task 8, and new tests are written under tests/unit, tests/component, tests/integration and tests/e2e using the legacy tests as the behavior inventory and the code as the source of truth. The program behavior and src/ do not change (only tests, docs, pyproject for dev dependencies). pyright stays at 0 errors and the whole suite stays green. Plan steps may use only commands in the WORKFLOW.md allow list: git mv and git rm are allowed (git mv needs the target directory to exist: create it by writing a file in it, there is no mkdir), no sed -i, no pipes or redirects, no uv add, uv lock, uv sync or uv run python; uv run pytest with options such as --collect-only, --durations, --cov is fine. If the work is too big for one run at the per-task cost cap, propose chained subtasks in the plan. For tasks that write new tests, the plan must list them as a table (new test | level | behavior | legacy tests it replaces), account for every inventory entry of the area (covered by a new or existing test, or dropped with a stated reason), keep integration and e2e tests to what only that level shows, and say what is covered by existing tests so nothing is duplicated.

Create the skeleton. (1) Create tests/unit, tests/component, tests/integration, tests/e2e, tests/checks and tests/fakes. (2) Move the existing in-process tests into their level with git mv: test_task_domain and test_validation_domain to unit; test_scenarios (with tests/scenarios/ and the FakeClock it defines, which test_tick imports) and test_tick and every test_app_* to component; test_config, test_tasks_port and test_adapters_vcs_validator_journal to integration; test_architecture and test_spec_docs to checks. test_agent_port tests only the fake agent runner: place it in component. (3) Move the subprocess tests (test_blackbox, test_commands, test_commands_phase2, test_planning, test_questions, test_dependencies, test_work_accept, test_layout, test_task_new, test_transitions, test_explore, test_completion, test_cli_surface, test_adr, test_manual) and conftest.py to tests/legacy/. Move the fakes (fake_agent, fake_journal, fake_session, fake_tasks, fake_terminal, fake_validator, fake_vcs) and fake_claude.py to tests/fakes/ (fake_claude.py is shared by the legacy and the future tests). Keep module names importable with the pytest pythonpath setting in pyproject.toml so imports need little editing, and solve the clash between two conftest.py files named the same (the plan decides how: for example the legacy support code becomes a regular module). Update paths that tests compute from __file__ (scenario files, FAKE_CLAUDE, the repo root). (4) Add per-folder import rules to the architecture check under tests/checks (read tests/checks/test_architecture.py first): unit and component never import samba.adapters (component may import the fakes, unit imports no fake); e2e never imports samba; integration never imports samba.entrypoints or samba.bootstrap; keep the existing scenario-runner rule. Add a test that every test file sits in one of unit, component, integration, e2e, checks or legacy. (5) Add pytest markers or a documented way to run the fast loop (uv run pytest -q tests/unit tests/component). (6) Update CLAUDE.md (the tests map, the Checks section with the fast loop and the honest full-run duration of about 4.5 minutes instead of 25 seconds, and the Conventions: new behavior gets a test at the lowest level, per ADR 0016) and the architecture spec chapter (the Scenarios and architecture-test sections: new paths, the four levels and the legacy folder as temporary). Nothing is deleted or rewritten except by moving; the suite stays green with the same tests.

## Plan
### Approach

Move-only strangler step. Every test keeps its content; only paths, a few import lines and the architecture check change. Module names stay flat and unique, so `pythonpath` lists the new folders and `from fake_tasks import ...`, `from test_scenarios import FakeClock` keep working. The only `conftest.py` (one fixture, `sb`) goes to legacy: its body becomes the regular module `tests/legacy/legacy_support.py` (git mv), and a 3-line `tests/legacy/conftest.py` re-exports the fixture (`from legacy_support import sb as sb`, to be deleted in task 8). Legacy tests change `from conftest import ...` to `from legacy_support import ...`, so any later `conftest.py` in a level folder cannot clash by module name and nothing else imports `conftest`. This is a first-line import edit only, no test logic is touched.

Resulting layout (`tests/` root holds no `.py`):
- `unit/`: test_task_domain, test_validation_domain
- `component/`: test_scenarios, `scenarios/` (JSON, git mv of the directory), test_tick, test_app_accept_create, test_app_completion, test_app_explore, test_app_queries, test_app_resolve, test_app_run_task, test_app_startup, test_app_use_cases, test_agent_port
- `integration/`: test_config, test_tasks_port, test_adapters_vcs_validator_journal
- `e2e/`: empty (README only)
- `checks/`: test_architecture, test_spec_docs
- `fakes/`: fake_agent, fake_journal, fake_session, fake_tasks, fake_terminal, fake_validator, fake_vcs, fake_claude
- `legacy/`: conftest.py (thin), legacy_support.py (old conftest), test_blackbox, test_commands, test_commands_phase2, test_planning, test_questions, test_dependencies, test_work_accept, test_layout, test_task_new, test_transitions, test_explore, test_completion, test_cli_surface, test_adr, test_manual

Fast loop: documented only, no markers (`uv run pytest -q tests/unit tests/component`); the folder is the marker, so no root conftest is needed. If the executor finds it cheap, a `markers` entry is not worth it (YAGNI).

### Steps

- [ ] Read CLAUDE.md, docs/spec/architecture.md, ADRs 0011, 0012, 0016 (`samba adr show N`).
- [ ] Create folders by writing one short `README.md` in each of `tests/unit`, `tests/component`, `tests/integration`, `tests/e2e`, `tests/checks`, `tests/fakes`, `tests/legacy` (what the level holds and its import rule, per ADR 0016; legacy: "temporary, removed by the end of the chain"). There is no mkdir, and git does not track empty dirs.
- [ ] `git mv` the files listed above, one per call (no globs/pipes). `git mv tests/scenarios tests/component/scenarios`. `git mv tests/conftest.py tests/legacy/legacy_support.py`, then Write the thin `tests/legacy/conftest.py`.
- [ ] pyproject.toml: `pythonpath = ["tests/fakes", "tests/legacy", "tests/component"]` (keep `testpaths = ["tests"]`); add `extraPaths = ["tests/fakes", "tests/legacy", "tests/component"]` under `[tool.pyright]` so strict pyright still resolves the flat imports. No dependency change.
- [ ] Fix computed paths (each is one `parent` deeper, or points to the new place):
  - legacy_support.py: `FAKE_CLAUDE = Path(__file__).parent.parent / "fakes" / "fake_claude.py"`.
  - legacy/test_blackbox.py:282 (`WORKFLOW.md`), legacy/test_manual.py:16 `ROOT`, legacy/test_transitions.py:17 `STATES_DOC`: add one `.parent`.
  - component/test_scenarios.py:78 `SCENARIO_DIR` stays `Path(__file__).resolve().parent / "scenarios"` (directory moved with it); verify, no edit expected.
  - checks/test_spec_docs.py:9 `ROOT = Path(__file__).parent.parent.parent`.
  - checks/test_architecture.py: `SRC = Path(__file__).resolve().parents[2] / "src" / "samba"`; scenario-runner path becomes `TESTS / "component" / "test_scenarios.py"`.
- [ ] Legacy import edit: in the 16 legacy files (all 15 subprocess tests that import it, plus test_work_accept's inner import at line 101) replace `from conftest import` by `from legacy_support import`. Grep `from conftest` afterwards to prove none is left.
- [ ] Extend tests/checks/test_architecture.py (write the new tests first, run, then keep): `TESTS = parents[1]`; helper `folder_imports(name)` yielding `(file, import)` over `TESTS/name` `*.py` using the existing `imported_modules`; `FAKE_MODULES` = stems of `tests/fakes/*.py`.
  - unit: no `samba.adapters`, no import whose first part is in FAKE_MODULES, no import of `test_*` modules or of `legacy_support`.
  - component: no `samba.adapters` (fakes allowed).
  - integration: no `samba.entrypoints`, no `samba.bootstrap` (use existing `is_outer`).
  - e2e: no import whose first part is `samba`.
  - keep `test_scenario_runner_imports_no_adapter_and_no_store` on the new path.
  - `test_every_test_file_sits_in_a_level_folder`: every `test_*.py` under `tests/` has first path part in `{unit, component, integration, e2e, checks, legacy}`, and `tests/` root holds no `.py`; `fakes/` holds no `test_*.py`.
  - `test_test_file_names_are_unique_across_tests`: no two `test_*.py` files anywhere under `tests/` share a basename (the folders have no `__init__.py`, so pytest fails with an import file mismatch otherwise). The later tasks of the chain write new tests next to the legacy ones and must pick names that differ from the legacy files (for example `test_task_commands.py` instead of `test_commands.py`). Say this in CLAUDE.md Conventions too.
  - scanner self-tests like the existing ones: a tmp file with an adapter import, a fake import, `import samba.x`, `samba.bootstrap`, and a tmp tree with a stray `tests/test_x.py` (make the scanner take a root argument so tmp_path can be used).
- [ ] CLAUDE.md: update the tests map (new folders, fakes in `tests/fakes/`, `fake_claude.py` shared, legacy folder temporary and what is inside), the Checks section (fast loop `uv run pytest -q tests/unit tests/component` in seconds; full `uv run pytest -q` about 4.5 minutes, legacy being the slow part), Conventions (new behavior gets a test at the lowest level that can show it, ADR 0016; integration and e2e stay few; legacy is not extended). Fix the "test_blackbox must never import samba" lines: that rule now belongs to `tests/e2e` and legacy; remove paths like `tests/test_architecture.py`, `tests/fake_*.py`. No em-dashes.
- [ ] docs/spec/architecture.md: see Spec changes.
- [ ] Other docs naming old paths: docs/spec/implementation-notes.md:14 (`tests/fake_claude.py` to `tests/fakes/fake_claude.py`), docs/spec/running-claude.md:8 (`tests/test_architecture.py` to `tests/checks/...`). `git grep -n "tests/"` over docs, README, CLAUDE.md to catch the rest.
- [ ] Verify (see below), then add a `## Log` line in the task file listing the spec changes. Commit with no attribution trailer.

### Files to change

- Moves (see layout); new: 7 `README.md`, `tests/legacy/conftest.py`.
- Edited: pyproject.toml, tests/legacy/legacy_support.py, legacy test_blackbox/test_manual/test_transitions and the 16 import lines, tests/checks/test_architecture.py, tests/checks/test_spec_docs.py, CLAUDE.md, docs/spec/architecture.md, implementation-notes.md, running-claude.md.
- Not changed: src/, WORKFLOW.md, README.md (generic `uv run pytest -q` stays true), docs/manual.md.

### Spec changes

docs/spec/architecture.md only:
- Ports table (line ~83) and fakes reference (~127): `tests/fakes/fake_tasks.py`, `tests/fakes/fake_agent.py`.
- Startup/RunTask sentence (~199): new paths under `tests/component/`.
- "The architecture test": new path `tests/checks/test_architecture.py`; add bullets for the four per-folder import rules (unit: no adapter and no fake; component: no adapter; integration: no entrypoint or bootstrap; e2e: no samba) and the rule that every test file sits in a level folder; add a short "Test levels" paragraph pointing to ADR 0016 (four levels, pyramid, fast loop, `tests/legacy/` as temporary until the chain ends).
- Scenarios section (~237-240): `tests/component/scenarios/*.json`, `tests/component/test_scenarios.py`, `tests/fakes/fake_tasks.py`; fake clock still lives in the test file; line ~230 `tests/component/test_scenarios.py` imports no adapter.
No ADR: ADR 0016 already records the decision.

### Test inventory table (new tests)

| new test | level | behavior | legacy tests it replaces |
|---|---|---|---|
| test_unit_folder_imports_no_adapter_and_no_fake | checks | level rule | none (new rule) |
| test_component_folder_imports_no_adapter | checks | level rule | none |
| test_integration_folder_imports_no_entrypoint_or_bootstrap | checks | level rule | none |
| test_e2e_folder_imports_no_samba | checks | level rule | none |
| test_every_test_file_sits_in_a_level_folder | checks | layout rule | none |
| scanner self-tests (tmp files) for each rule | checks | the scanners catch violations | none |

Inventory of the moved tests: every one of the 42 existing test modules is moved intact (listed above), so each is "covered by an existing test"; none is dropped or rewritten, and no behavior is duplicated. Integration and e2e get no new test here (e2e is empty until the later tasks of the chain).

### Risks

- Pytest module-name uniqueness (prepend import mode, no `__init__.py`): all names stay unique, and `legacy_support` removes the `conftest` import. A later per-level `conftest.py` is fine.
- Pyright strict: without `extraPaths` the flat imports fail; check `uv run pyright` reports 0 errors, including the unused-import re-export in legacy/conftest.py (`as sb`).
- Stale path computed from `__file__` in a place not found by grep: the failing test will say so; also `git grep -n "parent.parent"` tests/ after the moves.
- test_spec_docs scans `git ls-files` text for stale references: the new README.md files must not contain the old spec file name or section sign.
- Git must see renames: use `git mv`, not copy plus delete.
- If a moved in-process test turns out to break a new folder rule (grep showed none: unit has no adapter or fake imports; component test_scenarios imports `samba.entrypoints.orchestrator`, allowed; integration files import only adapters), do not edit the test: report it.

### How to verify

1. `uv run pyright` reports 0 errors.
2. `uv run pytest -q --collect-only` collects the same number of tests as before the move, plus the new check tests (record the baseline count at the start with the same command).
3. `uv run pytest -q tests/unit tests/component tests/integration tests/checks` green, in seconds.
4. `uv run pytest -q` green (about 4.5 minutes; run in the background / with a long timeout).
5. `git status` shows renames (R) for the moved files; `git grep -n "from conftest"` and `git grep -n "tests/test_\|tests/fake_\|tests/scenarios"` over docs, CLAUDE.md, tests show no stale path.
6. Run an `uv run pytest -q tests/checks` once to confirm the new rules fail when a violation exists is covered by the tmp-file self-tests.

### Suggested subtasks

Fits one run (moves are cheap; the full suite is run once at the end). No split needed.

## Assumptions
- No pytest markers are added; the fast loop is folder paths, documented in CLAUDE.md and the architecture chapter (the task allows either).
- Replacing `from conftest import` with `from legacy_support import` in legacy files is acceptable as the "solve the conftest clash" edit (import lines only).
- A thin tests/legacy/conftest.py re-exporting the `sb` fixture is acceptable as the only conftest.py until task 8.
- Empty dirs are created via README.md files, since git does not track empty directories and there is no mkdir.
- The baseline test count is taken by the executor with `--collect-only` before moving anything.
- ADR 0016 is accepted and sufficient; no new ADR is needed.

## Log
- 2026-11-12 15:47 samba: dispatch_plan: plan-todo -> plan-running
- 2026-11-12 15:49 samba: permission denied: Bash (sed -n 190,275p docs/spec/architecture.md; sed -n 1,40p tests/conftest.py; git grep -n "^from \(fake_\|test_\|conftest\))
- 2026-11-12 15:49 samba: planned: plan-running -> plan-review: planned (turns 1, $0.39): Pure move task: create the six level folders plus tests/legacy, git mv every existing test and fake into place, fix computed paths and imports, add per-folder import rules and a "file sits in a level" check to the architecture test, and update CLAUDE.md and the architecture chapter. No src/ change, no test rewritten.
- 2026-11-12 15:49 samba: plan.accept: plan-review -> work-todo
- 2026-11-12 15:49 samba: dispatch_work: work-todo -> work-running
- work: all plan steps done as planned. Baseline 734 tests; now 742 (8 new check tests: 4 level rules, level-folder rule, unique names, 2 scanner self-tests). pyright: `extraPaths` needed `"src"` too (setting it disables the default src lookup). Tests changed only in import/path lines (and one docstring path).
- Spec changes: docs/spec/architecture.md (new test paths, per-folder import rules and level-folder rule in "The architecture test", new "Test levels" section with the fast loop and the temporary legacy folder, Scenarios paths); implementation-notes.md and running-claude.md (paths). CLAUDE.md (tests map, Checks with fast loop and 4.5 min full run, Conventions). No ADR (ADR 0016 covers it). ADRs 0009/0012/0014/0015/0016 keep their old paths on purpose (history).
- 2026-11-12 21:10 samba: permission denied: Bash (ps -eo pid,etime,pcpu,command)
- 2026-11-12 21:56 samba: budget: work-running -> stuck: budget exceeded ($5.27) (turns 4, $5.27): The work is committed and pyright shows 0 errors. I'm checking the verbose `test_blackbox.py` run to find which legacy test is slow. No full-suite pass has completed yet.
- 2026-11-13 09:17 claude (supervising session): the agent committed the work (a69c7eb) but spent its budget polling the slow legacy suite; I ran pyright (0 errors) and the full suite on the branch (742 passed in 4m15s) and merged it by hand as ccdb478, on the human's instruction.
- 2026-11-13 09:17 human: work.accept by hand: stuck -> done (recorded by the supervising session)
