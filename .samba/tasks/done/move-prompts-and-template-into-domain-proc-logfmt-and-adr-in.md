---
priority: 3
depends_on: ["move-ports-py-into-domain-ports-py-layout-1-of-4"]
---
# Move prompts and template into domain, proc logfmt and adr into adapters (layout 2 of 4)

Read CLAUDE.md, docs/spec/architecture.md and ADRs 0011 to 0015 first. Behavior does not change: the black-box suite and every other test stay green, and pyright stays at 0 errors. Update the architecture chapter, any other spec chapter that names the moved files, and the CLAUDE.md map in the same change. Plan steps may use only commands in the WORKFLOW.md allow list: no git mv, no sed -i, no mkdir, no pipes or redirects. Move a file by writing it at its new path and git rm of the old one, then fix every import with Edit (use git grep to find them, in src and in tests).

Part of the layout change (architecture chapter): the root of src/samba holds only the layers and the entry points. This step: prompts.py and template.py become domain/prompts.py and domain/template.py. proc.py becomes adapters/process.py. logfmt.py (the kv formatter, used only by the log journal) is folded into adapters/log_journal.py. adr.py (ADR file parsing and edits, used only by adapters/adr_files.py) becomes adapters/adr_format.py. Update imports in src and tests, DOMAIN_MODULES in tests/test_architecture.py, and the docs that name these files. config.py, cli.py, orchestrator.py and compose.py do not move in this task.

## Plan
### Approach
Move five modules, one at a time, by writing the file at the new path with Write (same content, adjusted imports) and `git rm` of the old path, then fix every importer with Edit. Use only allow-listed commands (git grep, not grep; no git mv, sed -i, mkdir, pipes, redirects). `src/samba/domain/` and `src/samba/adapters/` already exist, so no mkdir is needed.

Moves:
- `prompts.py` -> `domain/prompts.py`
- `template.py` -> `domain/template.py`
- `proc.py` -> `adapters/process.py`
- `logfmt.py` -> folded into `adapters/log_journal.py`
- `adr.py` -> `adapters/adr_format.py`

### Steps
- [ ] Read CLAUDE.md, `docs/spec/architecture.md`, ADRs 0011-0015 (`uv run samba adr show N`), and the five source files.
- [ ] Baseline: `uv run pyright` and `uv run pytest -q` (run separately, plain).
- [ ] `domain/prompts.py`: Read `src/samba/prompts.py`, Write it unchanged at `src/samba/domain/prompts.py`, `git rm src/samba/prompts.py`. Fix importers: `adapters/claude_cli.py:27`, `domain/launch.py:11`, `orchestrator.py:27` (`from samba.prompts import (`), `tests/test_app_explore.py:9` -> `samba.domain.prompts`.
- [ ] `domain/template.py`: same procedure. Importer: `orchestrator.py:40` (`from samba.template import TemplateError, render`) -> `samba.domain.template`. Check `git grep -n "template" -- src tests` for any other importer (e.g. config.py, tests).
- [ ] `adapters/process.py`: Write `src/samba/proc.py` content at `src/samba/adapters/process.py`, `git rm src/samba/proc.py`. Importers: `adapters/claude_cli.py:26`, `adapters/git_vcs.py:10`, `adapters/shell_validator.py:9` -> `from samba.adapters.process import ...`. Update the module docstring if it names `proc.py`.
- [ ] `logfmt.py` into `adapters/log_journal.py`: Edit `log_journal.py` to remove `from samba.logfmt import kv` and add the `kv` function (15 lines, with its docstring "key=value log line format (spec: observability)") above `LogJournal`; `git rm src/samba/logfmt.py`. Check with `git grep -n "kv\b" -- src tests` that nothing else uses it.
- [ ] `adapters/adr_format.py`: Write `src/samba/adr.py` content at `src/samba/adapters/adr_format.py`, `git rm src/samba/adr.py`. In `adapters/adr_files.py` replace `from samba import adr` with `from samba.adapters import adr_format as adr` (keeps the body untouched) and update the docstring ("wraps `samba.adr`" -> "wraps `adr_format`"). `from samba import adr` in cli.py? `git grep -n "samba import\|samba\.adr" -- src tests` to confirm none other.
- [ ] `tests/test_architecture.py`:
  - `DOMAIN_MODULES`: replace `"template.py", "prompts.py"` with `"domain/template.py", "domain/prompts.py"` (update the comment).
  - `test_domain_and_app_code_has_no_storage_vocabulary`: skip `domain/prompts.py` (its text talks to the agent about task front matter); update the comment.
  - `ORCHESTRATOR_FORBIDDEN`: replace `samba.proc` and `samba.logfmt` with `samba.adapters.process` and `samba.adapters.log_journal` (already covered by `is_adapter`, so drop the stale names; keep `samba.workspace`, `samba.merge`, `samba.lock` as they are).
  - `test_only_the_adapter_splits_task_front_matter`: the exemption `"adr.py"` -> `"adapters/adr_format.py"`.
  - Add a small test that the five old paths are gone (`not (SRC / "proc.py").exists()` etc.) in the style of `test_the_old_task_store_is_gone_and_the_adapter_is_used`, and that `adapters/process.py`, `adapters/adr_format.py` exist.
- [ ] Docs (see Spec changes), then run `git grep -nE "prompts\.py|template\.py|proc\.py|logfmt|adr\.py"` and `git grep -n "samba\.\(prompts\|template\|proc\|logfmt\|adr\)\b"` over src, tests, docs, CLAUDE.md, README.md to confirm no stale reference (note `app/adr.py` is legitimate and stays).
- [ ] Run `uv run pyright` (0 errors) and `uv run pytest -q`. Check no leftover `__pycache__`/old files at the root: `src/samba` root should hold only `__init__`, `__main__` (if any), `cli.py`, `compose.py`, `config.py`, `orchestrator.py`, `views.py` plus the layer packages (verify with Glob).
- [ ] Add a line to the task file `## Log` saying which spec chapters and CLAUDE.md changed. Commit without any Co-Authored-By trailer.

### Files to change
- New: `src/samba/domain/prompts.py`, `src/samba/domain/template.py`, `src/samba/adapters/process.py`, `src/samba/adapters/adr_format.py`
- Removed: `src/samba/prompts.py`, `template.py`, `proc.py`, `logfmt.py`, `adr.py`
- Edited: `src/samba/adapters/log_journal.py` (adds `kv`), `adapters/adr_files.py`, `adapters/claude_cli.py`, `adapters/git_vcs.py`, `adapters/shell_validator.py`, `domain/launch.py`, `orchestrator.py`
- Tests: `tests/test_architecture.py`, `tests/test_app_explore.py`
- Docs: `CLAUDE.md`, `docs/spec/architecture.md`, `docs/spec/prompts.md`, and `docs/spec/observability.md` if it names `logfmt.py` (git grep found no hit, re-check)

### Spec changes
- `docs/spec/architecture.md`: Domain row (line 11): drop "`template.py` and `prompts.py` are pure and follow later", say they are `domain/template.py` and `domain/prompts.py`. `Adrs` row (line 44): "wraps `adr.py`" -> "wraps `adapters/adr_format.py`". Line 134: "`proc.py`" -> "`adapters/process.py`". Lines 143-144: DOMAIN_MODULES now holds `domain/template.py` and `domain/prompts.py`. Line 149: orchestrator forbidden list names `proc`/`logfmt`; reword to the new module locations (adapters in general). Also describe the layout step 2 of 4 wherever the chapter tracks the layout change (check for a layout/refactor section).
- `docs/spec/prompts.md` line 130: `prompts.py` -> `domain/prompts.py`.
- `CLAUDE.md` map: `domain/launch.py` entry (`EXPLORE_*` in `domain/prompts.py`); `adr.py` entry -> `adapters/adr_format.py` (and keep the `adapters/adr_files.py` sentence consistent); the `adapters/claude_cli.py` entry loses "`logfmt.py`: the `kv` log line format" and the `log_journal` entry gains "(and the `kv` log line format)"; `proc.py` entry -> `adapters/process.py`; `prompts.py` and `template.py` entries -> `domain/prompts.py`, `domain/template.py`; the `test_architecture.py` bullet is unchanged. Keep prose free of em-dashes.
- `docs/manual.md`: none, because it names no module files (verified by git grep).

### Risks
- Storage-vocabulary test flags `domain/prompts.py` once it is under `domain/`; handled by the exemption above. Alternative (rejected): rewording the prompts, which changes agent behavior.
- `test_domain_modules_import_no_io_and_no_adapter`: `domain/prompts.py` imports only `json` and `domain/template.py` only `re`, so it passes.
- Circular imports: `adapters/adr_format.py` imports `samba.domain.ports`, which does not import it back. `domain/launch.py` importing `samba.domain.prompts` is within the domain.
- Missed importers that only fail at runtime (e.g. lazy imports inside functions): `git grep` all of `samba.proc`, `samba.adr`, `samba.prompts`, `samba.template`, `samba.logfmt` and also `from samba import <name>` forms before running tests.
- `adapters/adr_files.py` alias `import adr_format as adr` keeps the diff minimal; if pyright complains about cyclic module access, import the names directly.

### How to verify
- `uv run pyright` reports 0 errors.
- `uv run pytest -q` all green (includes `test_architecture.py`, `test_blackbox.py`, `test_manual.py`, `test_spec_docs.py`, `test_adr.py`, `test_explore.py`).
- `git grep -nE "samba\.(prompts|template|proc|logfmt|adr)\b|\bproc\.py|logfmt|src/samba/adr\.py"` returns nothing outside `docs/adr/` historical text.
- Glob `src/samba/*.py` shows only entry points and root modules that stay (cli, compose, config, orchestrator, views, `__init__`).

## Assumptions
- Behavior is unchanged, so no new black-box test is needed. The existing suite, `tests/test_architecture.py` and pyright are the safety net.
- `tests/test_architecture.py::test_domain_and_app_code_has_no_storage_vocabulary` will flag `domain/prompts.py`, because the prompt text says "front matter" (about the agent's task file). I assume the right fix is to exempt that one file in the test, not to reword the prompts (rewording would change behavior). The test comment already anticipates this.
- `adr.py` moves as `adapters/adr_format.py`. It imports `AdrError` from `samba.domain.ports`, which is allowed for an adapter. `kv` keeps its name; it becomes a module-level function in `log_journal.py` (private `_kv` is fine only if nothing else uses it; `git grep` showed only `log_journal.py` does).
- No ADR is needed: this is the layout change already decided in the architecture chapter and ADRs 0011 to 0015.

## Log
- 2026-11-11 14:00 samba: dispatch_plan: plan-todo -> plan-running
- 2026-11-11 14:00 samba: planned: plan-running -> plan-review: planned (turns 1, $0.17): Pure file moves (5 files) with import fixes in src, tests, the architecture guard and docs. The one wrinkle is the storage-vocabulary test, which would start flagging domain/prompts.py.
- 2026-11-11 14:01 samba: plan.accept: plan-review -> work-todo
- 2026-11-11 14:01 samba: dispatch_work: work-todo -> work-running
- Work done: moved prompts/template to domain/, proc to adapters/process.py, adr to adapters/adr_format.py, folded logfmt `kv` into adapters/log_journal.py; imports, tests/test_architecture.py (DOMAIN_MODULES, exemptions, new "old paths gone" test) updated. pyright 0 errors, pytest 660 passed.
- Spec changes: docs/spec/architecture.md (domain row, Adrs row, process.py, DOMAIN_MODULES, orchestrator forbidden list), docs/spec/prompts.md (domain/prompts.py), CLAUDE.md map. No ADR: layout already decided.
- 2026-11-11 14:09 samba: done: work-running -> work-review: validation passed (turns 2, $0.62): Moved prompts.py and template.py into domain/, proc.py to adapters/process.py and adr.py to adapters/adr_format.py. Folded logfmt's kv into adapters/log_journal.py. Fixed imports in src and tests, the architecture test and the docs. pyright reports 0 errors and pytest passes (660 tests). Spec chapters architecture and prompts and the CLAUDE.md map are updated; no ADR was needed. All committed.
- 2026-11-11 14:12 samba: work.accept: work-review -> done: merged 74a3a20, validated
