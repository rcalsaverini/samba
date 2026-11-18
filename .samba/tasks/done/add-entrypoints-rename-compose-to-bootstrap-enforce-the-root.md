---
priority: 3
depends_on: ["split-config-py-into-plain-settings-and-a-workflow-md-reader"]
---
# Add entrypoints/, rename compose to bootstrap, enforce the root (layout 4 of 4)

Read CLAUDE.md, docs/spec/architecture.md and ADRs 0011 to 0015 first. Behavior does not change: the black-box suite and every other test stay green, and pyright stays at 0 errors. Update the architecture chapter, any other spec chapter that names the moved files, and the CLAUDE.md map in the same change. Plan steps may use only commands in the WORKFLOW.md allow list: no git mv, no sed -i, no mkdir, no pipes or redirects. Move a file by writing it at its new path and git rm of the old one, then fix every import with Edit (use git grep to find them, in src and in tests).

Last step of the layout change (architecture chapter). Move cli.py to entrypoints/cli.py, views.py (the table printer) to entrypoints/table.py (or a package entrypoints/cli/ if that reads better; the plan decides), and orchestrator.py to entrypoints/orchestrator.py as it is (ADR 0015 splits it in a later task). Rename compose.py to bootstrap.py, keeping it at the root: the one module allowed to import every layer and the only place that builds adapters. Update the script entry in pyproject.toml (samba = samba.entrypoints.cli:main) and __main__.py. Add the architecture test: the root of src/samba may hold only __init__.py, __main__.py, bootstrap.py and the packages domain, app, adapters and entrypoints. Rewrite the layers section of the architecture chapter and the CLAUDE.md map for the final layout, and note in the architecture chapter that this refines the last sentence of ADR 0011 (the composition root is bootstrap.py, called by every entry point). Note for the human in the final log line: the installed samba tool must be reinstalled after this merge because the script entry changes.

## Plan
### Approach

Pure structural move, no behavior change. Decision on the open point: flat modules in a package, `entrypoints/cli.py`, `entrypoints/table.py` (was `views.py`) and `entrypoints/orchestrator.py`. cli.py is 342 lines and views.py only 27, so a `cli/` package adds nothing. `entrypoints/__init__.py` stays empty, so that `bootstrap` importing `entrypoints.orchestrator` and `entrypoints.cli` importing `bootstrap` cannot form an import cycle at package load. `compose.py` becomes `bootstrap.py` at the root. Constructor signatures and function names (`build`, `build_adr`, `build_explore`, `Services`) stay the same. Only module paths change.

Known imports to fix (found with git grep):
- `src/samba/__main__.py`: `from samba.cli import main`
- `src/samba/cli.py`: imports `samba.compose`, `samba.orchestrator` (StartupError) and `samba.views`
- `src/samba/compose.py`: imports `samba.orchestrator`
- `tests/test_scenarios.py:41`: `from samba.orchestrator import Orchestrator`
- `pyproject.toml:9`: `samba = "samba.cli:main"`
- `tests/test_architecture.py`: paths `cli.py`, `orchestrator.py` and `compose.py` (lines 124, 173-187, 221, 249)

Only commands from the WORKFLOW.md allow list may be used: `git grep`, not grep; no `git mv`, no `sed -i`, no `mkdir`, no pipes or redirects. Move a file by Reading the old one, Writing the full content at the new path (Write creates the directory), then `git rm` of the old path.

### Steps

- [ ] Read CLAUDE.md, docs/spec/architecture.md, ADRs 0011 to 0015 (`uv run samba adr show 11` and so on), and docs/spec/cli.md.
- [ ] Test first, in `tests/test_architecture.py`. Add `test_the_root_holds_only_bootstrap_main_and_the_four_layers`: list the entries of `SRC`, ignoring `__pycache__`. The `.py` files must equal `{__init__.py, __main__.py, bootstrap.py}` and the directories must equal `{domain, app, adapters, entrypoints}`. Add a scanner test against a tmp_path tree with a stray `foo.py` and an extra directory, so the rule is itself tested like the others. Run it and see it fail.
- [ ] Add `tests/test_architecture.py` rules for the new layout:
  - `domain/`, `app/` and `adapters/` import neither `samba.bootstrap` nor `samba.entrypoints`. Domain and app already forbid adapters.
  - `entrypoints/*.py` import no adapter (this replaces the `cli.py` and `orchestrator.py` check).
  - Only `bootstrap.py` constructs `MarkdownTasks(`.
  - The old root modules `cli.py`, `views.py`, `orchestrator.py` and `compose.py` no longer exist.
  - Every `.py` under `entrypoints/` is accounted for (`cli.py`, `table.py`, `orchestrator.py`, `__init__.py`).
- [ ] Create `src/samba/entrypoints/__init__.py` (a one-line docstring only, no imports).
- [ ] Write `src/samba/entrypoints/orchestrator.py` with the content of `orchestrator.py` unchanged, except the docstring at line 51 now says `samba.bootstrap`. `git rm src/samba/orchestrator.py`.
- [ ] Write `src/samba/entrypoints/table.py` with the content of `views.py`. Docstring: "table printer of the CLI entry point". `git rm src/samba/views.py`.
- [ ] Write `src/samba/bootstrap.py` from `compose.py`: update the module docstring to say bootstrap, and change the import to `from samba.entrypoints.orchestrator import Orchestrator`. `git rm src/samba/compose.py`.
- [ ] Write `src/samba/entrypoints/cli.py` from `cli.py` with imports `samba.bootstrap`, `samba.entrypoints.orchestrator` and `samba.entrypoints.table`. `git rm src/samba/cli.py`.
- [ ] Edit `src/samba/__main__.py` to `from samba.entrypoints.cli import main`. Edit `pyproject.toml` to `samba = "samba.entrypoints.cli:main"`.
- [ ] Edit `tests/test_scenarios.py` to import `samba.entrypoints.orchestrator`. Update the remaining paths in `tests/test_architecture.py` (`compose.py` to `bootstrap.py`, `cli.py` to `entrypoints/cli.py`, `orchestrator.py` to `entrypoints/orchestrator.py`, including the `no_direct_clock` list and the `test_the_cli_adapter_holds_no_rule` test). The `time.time` call in the table printer is not scanned, as before.
- [ ] `git grep -nE "compose|samba\.cli|samba\.views|samba\.orchestrator|views\.py|cli\.py|orchestrator\.py"` over src, tests, docs, README.md and CLAUDE.md; fix every stale hit (see Files to change). Check `docs/manual.md` and `README.md` for `compose`, and fix any hit (the earlier count showed 9 and 3 hits for broader terms, probably only "orchestrator" prose).
- [ ] Update the docs (see Spec changes).
- [ ] Run `uv run pyright` (0 errors), then `uv run pytest -q`. The black-box suite runs `python -m samba` (tests/conftest.py `samba_cmd`), so it exercises `__main__.py`, not the script entry in pyproject.toml. Do not run `uv sync` (not on the allow list); `uv run` refreshes the project environment itself.
- [ ] Append to the task's `## Log` what the spec changed, and a final line: "NOTE for the human: reinstall the installed samba tool after this merge, because the script entry changed to samba.entrypoints.cli:main."

### Files to change

- Created: `src/samba/entrypoints/__init__.py`, `entrypoints/cli.py`, `entrypoints/table.py`, `entrypoints/orchestrator.py`, `src/samba/bootstrap.py`.
- Removed (git rm): `src/samba/cli.py`, `views.py`, `orchestrator.py`, `compose.py`.
- Edited: `src/samba/__main__.py`, `pyproject.toml`, `tests/test_scenarios.py`, `tests/test_architecture.py`, `CLAUDE.md`, `docs/spec/architecture.md`, `docs/spec/cli.md` (lines 71 and 76: `cli.py` to `entrypoints/cli.py`, `compose.py` to `bootstrap.py`).
- Check, edit if they name the moved files: `docs/spec/states.md`, `docs/spec/README.md`, `docs/spec/observability.md`, `docs/manual.md`, `README.md`.

### Spec changes

- `docs/spec/architecture.md`, Layers: rewrite the table for the final layout. Rows: Domain, Use cases (`app/`), Adapters, and a new Entry points row (`src/samba/entrypoints/`: `cli.py` the thin argparse adapter, `table.py` the table printer, `orchestrator.py` the poll loop and workers, kept as is until ADR 0015's split). Add the root: only `__init__.py`, `__main__.py` and `bootstrap.py` live at `src/samba/`, and `bootstrap.py` is the one module allowed to import every layer. Drop the "Target location" wording, since the layout is now the real one.
- Same chapter, Dependency rule: replace `compose.py` with `bootstrap.py`; entry points depend on bootstrap, use cases, the domain and ports, never on adapters; no inner layer imports `bootstrap` or `entrypoints`. Add a note that this refines the last sentence of ADR 0011: the composition root is `bootstrap.py`, called by every entry point.
- Same chapter: update Ports table references (`cli.py` to `entrypoints/cli.py`, `compose.build` to `bootstrap.build`, the `Journal` row), "Where each concern lives" (`entrypoints/orchestrator.py`, `entrypoints/table.py`, bootstrap) and "The architecture test" list (the new root-layout rule, the new import rules, the moved paths).
- `docs/spec/cli.md`: path updates only.
- `CLAUDE.md` map: update the `cli.py`, `compose.py`, `views.py` and `orchestrator.py` entries to the new paths and names (`entrypoints/cli.py`, `bootstrap.py`, `entrypoints/table.py`, `entrypoints/orchestrator.py`), and note the root rule. This includes the `compose.build(...)` mentions at lines 22 and 67, and the test_scenarios line 95.
- No ADR is needed: the decision is already ADR 0011 and 0015 territory. Only the architecture chapter note refines ADR 0011.

### Risks

- Import cycle: `entrypoints/__init__.py` must not import anything. `bootstrap` imports `entrypoints.orchestrator`, and `entrypoints.cli` imports `bootstrap`, which is fine as long as the package `__init__` is empty.
- The installed `samba` script entry changes, so a stale venv or tool install breaks `samba` until reinstalled (`uv sync`, `uv tool install --reinstall`). Hence the log note.
- Content copied by hand (cli.py has 342 lines, orchestrator.py 313): copy verbatim, then check that pyright and the suite pass. `git diff -M` should show high similarity for the renames.
- `test_architecture.py` string checks (for example the `Machine` and `merge.` words in cli) must keep pointing at the new paths, or they pass vacuously: `read_text` on a missing path raises, so the tests would fail loudly.
- Root test must ignore `__pycache__`.

### How to verify

- `uv run pyright`: 0 errors.
- `uv run pytest -q`: all green, including the black-box suite, `test_manual.py`, `test_scenarios.py` and the new root-layout test (confirm it failed before the move).
- `uv run samba --help` works (the only help form on the allow list; `python -m samba` is covered by the black-box suite).
- `git ls-files src/samba` at the root shows only `__init__.py`, `__main__.py`, `bootstrap.py` and the four packages.
- `git grep -nE "samba\.(cli|views|orchestrator|compose)\b|compose\.py"` returns nothing outside docs/adr history.

### Suggested subtasks

None; the change is small and has to land atomically.

## Assumptions
- Flat modules in `entrypoints/` (cli.py, table.py, orchestrator.py), not an `entrypoints/cli/` package.
- `entrypoints/__init__.py` is empty to avoid import cycles.
- The black-box tests invoke `samba` through the venv script or `python -m samba`; if the script, `uv sync` must regenerate it (to be checked by the executor in conftest.py).
- No new ADR; the architecture chapter note refines ADR 0011.
- I could not run a final git grep over docs/manual.md and README.md for `compose`/`views`; the plan includes that check as a step.

## Log
- 2026-11-11 14:27 samba: dispatch_plan: plan-todo -> plan-running
- 2026-11-11 14:28 samba: permission denied: Bash (git grep -nE "orchestrator\.py|cli\.py|views|compose|`orchestrator`" -- docs/spec docs/manual.md README.md CLAUDE.md doc)
- 2026-11-11 14:28 samba: planned: plan-running -> plan-review: planned (turns 1, $0.22): Move cli.py, views.py (as table.py) and orchestrator.py into a new samba/entrypoints/ package, rename compose.py to bootstrap.py, fix all imports, add a root-layout architecture test, and rewrite the architecture chapter, CLAUDE.md map and cli chapter. Behavior is unchanged.
- 2026-11-11 14:29 samba: plan.accept: plan-review -> work-todo
- 2026-11-11 14:29 samba: dispatch_work: work-todo -> work-running
- Work done as planned, no deviation. Moved cli.py, views.py (as table.py), orchestrator.py into entrypoints/, compose.py to bootstrap.py; script entry and __main__ updated. Root-layout architecture test written first and seen failing, then green. pyright 0 errors, pytest 668 passed.
- Spec changes: docs/spec/architecture.md (layers table with Entry points row and root rule, dependency rule with bootstrap and the ADR 0011 refinement note, ports table paths, where-each-concern-lives, architecture test list), docs/spec/cli.md (paths), CLAUDE.md map. No ADR: no new decision.
- NOTE for the human: reinstall the installed samba tool after this merge, because the script entry changed to samba.entrypoints.cli:main.
- 2026-11-11 14:37 samba: done: work-running -> work-review: validation passed (turns 2, $0.93): I moved cli.py, views.py (now table.py) and orchestrator.py into `entrypoints/` and renamed compose.py to bootstrap.py. I also updated the script entry, `__main__.py`, the tests, the architecture and cli chapters, and the CLAUDE.md map. I added an architecture test for the root layout and watched it fail before the move. pyright reports 0 errors and 668 tests pass. The installed samba tool must be reinstalled after this merge, because the script entry is now `samba.entrypoints.cli:main`; the task log says so too.
- 2026-11-11 14:41 samba: work.accept: work-review -> done: merged 7ccf099, validated
