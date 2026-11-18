---
priority: 3
depends_on: ["move-prompts-and-template-into-domain-proc-logfmt-and-adr-in"]
---
# Split config.py into plain settings and a WORKFLOW.md reader (layout 3 of 4)

Read CLAUDE.md, docs/spec/architecture.md and ADRs 0011 to 0015 first. Behavior does not change: the black-box suite and every other test stay green, and pyright stays at 0 errors. Update the architecture chapter, any other spec chapter that names the moved files, and the CLAUDE.md map in the same change. Plan steps may use only commands in the WORKFLOW.md allow list: no git mv, no sed -i, no mkdir, no pipes or redirects. Move a file by writing it at its new path and git rm of the old one, then fix every import with Edit (use git grep to find them, in src and in tests).

Part of the layout change (architecture chapter). config.py holds both the settings types the core reads (Policy, AgentSettings, Layout, Prompts, Validation, Hooks, Config) and the code that parses WORKFLOW.md from disk (load_config, front matter, the reader). Split it: the settings the core and the use cases read become plain data in domain/ with no pathlib and no yaml; reading and validating WORKFLOW.md becomes an adapter (adapters/workflow_file.py) that returns them; ConfigError goes with the types it belongs to. Path-shaped values (the repo, the workspace root) must not reach domain/ or app/: they stay in the adapters or reach the use cases as opaque text, as the use cases already receive the repo location today. The plan decides the exact fields and says what it chose. Extend tests/test_architecture.py so domain/ and app/ cannot import pathlib or yaml for the new module, and keep tests/test_config.py passing (move it only if the imports require).

## Plan
### Approach

Behavior does not change. `config.py` is split in two, and location values are kept out of the core settings entirely.

1. **`src/samba/domain/settings.py`** is plain data. Imports allowed: `dataclasses` and `typing` only (no `pathlib`, `yaml` or `shlex`). It holds:
   - `ConfigError`
   - `DEFAULT_ALLOW` and `DEFAULT_PLANNING_ALLOW`
   - the frozen dataclasses `Policy`, `AgentSettings`, `Prompts`, `Validation`, `Hooks`, a new `Repository` and `Config`
   - `Repository` has one field, `base_branch: str` (the branch work is merged into).
   - `Config` holds `policy`, `agent`, `repository`, `prompts`, `validation`, `hooks` and `warnings`. **`Layout` is removed.**
   - No field of any of these carries a folder, a worktree location or a repo location.
2. **`src/samba/adapters/workflow_file.py`** reads WORKFLOW.md. Imports allowed: `pathlib`, `yaml`, `shlex`. It holds:
   - `WORKFLOW_FILE`, `PERMISSION_MODES` and `PROMPT_KEYS`
   - `split_front_matter`, `_Reader` and `_expand`
   - `@dataclass(frozen=True) class Locations` with `repo: Path`, `samba_dir: Path` and `workspaces_root: Path`
   - `load_config(repo: Path) -> tuple[Config, Locations]`: same parsing, same error messages, same warnings, same workspaces-outside-repo check (it runs on the real Paths inside the reader)

**Who gets what (no Path to str round trip).** The composition root, `compose.py`, unpacks `config, locations = load_config(repo)` and passes `Locations` values only to the adapters that need them:
- `LogJournal(locations.samba_dir)`
- `MarkdownTasks(locations.samba_dir / "tasks", locations.samba_dir / "state", clock)`
- `FileLock(locations.samba_dir)`
- `ClaudeCliRunner(config.agent, (samba_dir / "tasks").resolve(), samba_dir / "runs", locations.repo, journal)`
- `ShellValidator(config.validation, samba_dir / "runs")`
- `GitVcs(locations, config.repository.base_branch, config.hooks, config.validation.shell)`: it uses `locations.workspaces_root` and `locations.repo` as Paths, and `base_branch` as a plain string.
- `AcceptWork(..., config.repository.base_branch, config.validation.command)`
- `build_explore` passes `str(locations.repo)` to `StartExplore`, as it does today.

The orchestrator and the use cases keep receiving the repo only as opaque text. The orchestrator's `started` log line uses `self.vcs.checkout_location()`, a `Vcs` port method that already returns text. The orchestrator drops `self.layout`. The template variable `base_branch` reads `config.repository.base_branch`.

**Moving files.** Write the new files, then `git rm src/samba/config.py`. Do not use git mv, sed, mkdir, pipes or redirects. Find old imports with `git grep -n "samba.config"` and fix each with Edit. The word `Path` must not appear in domain/settings.py, even in a docstring (the `STORAGE_WORDS` check).

### Steps

- [ ] Run `uv run samba adr list`, then `uv run samba adr show 11` to `15`. Read docs/spec/architecture.md and workflow-config.md.
- [ ] Tests first, in tests/test_architecture.py:
  - Add `"domain/settings.py"` to `DOMAIN_MODULES`. `test_domain_modules_exist` fails until the file exists.
  - Add `test_domain_and_app_import_no_pathlib_or_yaml`. For every module in `DOMAIN_MODULES` and `APP_MODULES`, `imported_modules` must contain neither `pathlib` nor `yaml` (top-level name). Today `FORBIDDEN` already bars `pathlib` in the domain, so `yaml` is the new part there. Use an explicit shared set so the intent is visible.
  - Add a scanner self-test on a tmp file with `import yaml` and `from pathlib import Path`.
  - Extend `test_the_root_modules_moved_into_their_layers`: `config.py` no longer exists at the root, and `adapters/workflow_file.py` and `domain/settings.py` exist.
  - Add a test that domain/settings.py defines no `Layout` and no field named `repo`, `samba_dir` or `workspaces_root` (scan `code_without_comments` for those words).
  - In `test_only_the_adapter_splits_task_front_matter`, replace `"config.py"` with `"adapters/workflow_file.py"` in the exempt tuple.
- [ ] Write `domain/settings.py`: copy the types and constants, drop `Layout`, add `Repository`, and update `Config`.
- [ ] Write `adapters/workflow_file.py` as described above, importing the types from `samba.domain.settings`.
- [ ] `git rm src/samba/config.py`.
- [ ] Fix imports and call sites with Edit:
  - `src/samba/compose.py`: imports `Config` from `samba.domain.settings` and `load_config`, `Locations` from `samba.adapters.workflow_file`. Rewire `build` and `build_explore` as in "Who gets what". Replace every `config.layout.*` and `layout.*` use.
  - `src/samba/cli.py`: `ConfigError` from `samba.domain.settings` (cli may not import adapters).
  - `src/samba/orchestrator.py`: `Config` from `samba.domain.settings`. Remove `self.layout`. Use `self.vcs.checkout_location()` in the `started` log. Use `config.repository.base_branch` for the template variable.
  - `src/samba/adapters/git_vcs.py`: new constructor `(locations: Locations, base_branch: str, hooks: Hooks, shell)`. Replace `layout.repo`, `layout.samba_dir`, `layout.workspaces_root` with the `Locations` fields and `layout.base_branch` with `self.base_branch`. Import `Locations` from `samba.adapters.workflow_file` (adapter to adapter is allowed) and `Hooks` from the domain. Keep the `workspace_location` and `checkout_location` return values the same.
  - `src/samba/adapters/shell_validator.py` and `src/samba/adapters/claude_cli.py`: import path only.
  - tests/test_scenarios.py: import from `samba.domain.settings`. Replace `Layout(...)` in `lifecycle_config` with `repository=Repository(base_branch=...)`. Check that its fake Vcs has `checkout_location`.
  - tests/test_adapters_vcs_validator_journal.py: build `Locations(repo=..., samba_dir=..., workspaces_root=...)` and pass `base_branch` to `GitVcs`. Hooks and Validation imports change to the domain.
  - tests/test_config.py: `cfg, loc = load_config(tmp_path)`. Layout assertions become `loc == Locations(...)` and `cfg.repository == Repository("main")`. Update the imports and the docstring.
- [ ] Update the docs (see Spec changes).
- [ ] Run `uv run pyright`, then `uv run pytest -q`, as separate plain commands. Fix whatever they report.
- [ ] Add a line to the task file's `## Log` saying what changed in the spec, CLAUDE.md and the docs.
- [ ] Commit with no Co-Authored-By trailer or other attribution line.

### Files to change

- New: `src/samba/domain/settings.py` and `src/samba/adapters/workflow_file.py`.
- Removed: `src/samba/config.py`.
- Imports and rewiring: `src/samba/compose.py`, `src/samba/cli.py`, `src/samba/orchestrator.py`, `src/samba/adapters/git_vcs.py`, `src/samba/adapters/shell_validator.py` and `src/samba/adapters/claude_cli.py`.
- Tests: `tests/test_architecture.py`, `tests/test_config.py`, `tests/test_scenarios.py` and `tests/test_adapters_vcs_validator_journal.py`. Also the fake Vcs file (tests/fake_vcs.py) only if it lacks `checkout_location`.
- Docs: `CLAUDE.md`, `docs/spec/architecture.md` and `docs/spec/workflow-config.md`. Check `docs/spec/implementation-notes.md` and `docs/spec/layout.md` with `git grep -n "config.py"` and `git grep -n "load_config"`.

### Spec changes

- `docs/spec/architecture.md`:
  - The "Configuration" paragraph now says the settings are plain data in `domain/settings.py`: `Policy`, `AgentSettings`, `Prompts`, `Validation`, `Hooks`, `Repository` (the base branch) and `Config`, plus `ConfigError` and the `DEFAULT_*` lists. It says the core carries no location (ADR 0011).
  - The same paragraph says `adapters/workflow_file.py` reads and validates WORKFLOW.md, and `load_config` returns the `Config` plus a `Locations` of real paths (repo, Samba directory, workspaces root). Bootstrap hands `Locations` only to `GitVcs`, `FileLock`, `MarkdownTasks`, `LogJournal` and `ClaudeCliRunner`.
  - The same paragraph says `Layout` is gone, and that the orchestrator and use cases get the repo as opaque text through the `Vcs` port.
  - "Moved into `domain/`" mentions `settings.py`.
  - The architecture-test list says the domain and app modules import neither `pathlib` nor `yaml`, and that `config.py` no longer exists at the root.
  - Update any list that names `config.py`.
- `docs/spec/workflow-config.md`: line 7 and the lines after it say `load_config` splits keys into the parts `Policy`, `AgentSettings`, `Layout`, `Prompts`, `Validation` and `Hooks`. Change this to `adapters/workflow_file.load_config`, the parts defined in `domain/settings.py` (including `Repository` for `base_branch`, no `Layout`) and the separate `Locations`. The file format is unchanged.
- `CLAUDE.md` map: replace the `config.py` entry with `domain/settings.py` (plain settings, `ConfigError`, defaults) and `adapters/workflow_file.py` (loads and validates WORKFLOW.md, returns `Config` and `Locations`). Update the `compose.py` description if it names `config.py`.
- No change to the behavior chapters (states, orchestrator, cli and the others).

### Risks

- Missed `layout` call sites. `git grep -n "layout\." src tests` after the edit must show none, and pyright catches the rest.
- The `started` log line must keep the same `repo=` text. `checkout_location()` returns `str(repo)`, which matches. Check that no black-box test compares it differently.
- The scenarios fake Vcs may lack `checkout_location`. Check before editing the orchestrator.
- The word `Path` in domain/settings.py fails `STORAGE_WORDS`. Words like `repo` are fine in docs, but the new test forbids location fields in the module.
- `cli.py` cannot import adapters, so `ConfigError` must come from the domain.
- Dataclass defaults (`Config.warnings`, `AgentSettings.planning_allow`, `Prompts.overrides`) must be preserved exactly.
- Circular imports: `adapters/git_vcs.py` imports `Locations` from `adapters/workflow_file.py`, and `workflow_file.py` imports only the domain, so no cycle.
- `test_config.py` expectations for the resolved paths must still match (`ws.resolve()`, the `repo / "state"` case).

### How to verify

- `uv run pyright` reports 0 errors.
- `uv run pytest -q` is fully green, including `test_blackbox.py` (it never imports `samba`), `test_config.py`, `test_architecture.py` and `test_scenarios.py`.
- `git grep -n "samba.config"` returns nothing. `git grep -n "Layout"` in src and tests returns nothing. `git grep -n "config.py"` returns only intentional mentions.
- `git grep -n "pathlib\|import yaml" src/samba/domain src/samba/app` returns nothing.

### Suggested subtasks

None. This is one cohesive change.

## Assumptions
- `base_branch` goes on a new tiny frozen dataclass `Repository(base_branch: str)` in domain/settings.py, held by `Config.repository`. I did not put it on `Policy` (limits and scheduling) or `Validation`. Executor may pick another home if one fits better, but must say so in the Log.
- `load_config(repo: Path) -> tuple[Config, Locations]`. `Locations` is defined in `adapters/workflow_file.py` (not a sibling module) and holds `repo`, `samba_dir` and `workspaces_root`, all resolved `Path` values.
- `Hooks` stays in domain/settings.py (plain strings and numbers). `GitVcs` takes `(locations, base_branch, hooks, shell)`.
- The orchestrator's `started` log line takes the repo from `self.vcs.checkout_location()`, which already returns `str(repo)`, so the log output is unchanged. This assumes the fake Vcs used by the scenarios implements `checkout_location` (it is a `Vcs` port method). If it does not, add it to the fake.
- `Services` keeps `config: Config`, and `Services` also gains `locations: Locations` only if something in cli.py needs it. At planning time cli.py read no layout field, so probably not.
- `domain/settings.py` is the module name; `workflow_file.py` is fixed by the task.
- No new ADR: ADR 0011 already says the core knows no folder or path. If the executor thinks `Repository` or `Locations` is a lasting decision, it may propose a short one.
- tests/test_config.py stays in place. Only its imports and its expectations change.

## Feedback
### Round 1

Good plan overall (domain/settings.py plus adapters/workflow_file.py, ConfigError and DEFAULT_* in the domain, tests first, import list). One change: do not keep Layout with path fields in domain/settings.py, even as str. repo, samba_dir and workspaces_root are folders and worktree locations, and ADR 0011 says the core knows no folder or path; a database or Linear store would make samba_dir and workspaces_root meaningless in the core config. Instead: (1) the core settings carry no location at all. base_branch becomes a plain setting of the domain (the plan picks where, for example on an existing type or a small Repository type), and the orchestrator and use cases keep getting the repo as opaque location text from bootstrap as they do today. (2) The path-shaped values (repo, samba_dir, workspaces_root) become a small Locations dataclass of real Path values that lives in the adapters package (in adapters/workflow_file.py or a sibling module of your choice), is returned by the reader next to the Config, and is passed by bootstrap only to the adapters that need it (GitVcs, FileLock, MarkdownTasks, LogJournal, ClaudeCliRunner). No Path to str round trip then. Hooks is plain strings and numbers, so it can stay with the domain settings if GitVcs only needs the values. (3) Keep everything else as planned, including the workspaces-outside-repo check in load_config, the architecture tests (no pathlib or yaml in domain/ and app/), the root-modules test and the docs. Update the plan and the Spec changes section for this split.

## Log
- 2026-11-11 14:13 samba: dispatch_plan: plan-todo -> plan-running
- 2026-11-11 14:13 samba: planned: plan-running -> plan-review: planned (turns 1, $0.20): Move the settings types, ConfigError and the DEFAULT_* lists into a pure domain/settings.py. Layout's path fields become absolute text. Move the YAML reader and load_config to adapters/workflow_file.py. Fix imports and the architecture test, and update the spec and CLAUDE.md.
- 2026-11-11 14:14 samba: plan.reject: plan-review -> plan-todo: feedback round 1
- 2026-11-11 14:14 samba: dispatch_plan: plan-todo -> plan-running
- 2026-11-11 14:15 samba: planned: plan-running -> plan-review: planned (turns 2, $0.54): Revised for round 1. The core settings carry no location: `Layout` is gone and `base_branch` becomes a plain `Repository` setting. A `Locations` dataclass of real Path values lives in `adapters/workflow_file.py`, is returned by `load_config` next to `Config`, and goes only to the adapters that need it. The orchestrator gets the repo as opaque text from the `Vcs` port.
- 2026-11-11 14:15 samba: plan.accept: plan-review -> work-todo
- 2026-11-11 14:15 samba: dispatch_work: work-todo -> work-running
- Done as planned: domain/settings.py (with `Repository`, no `Layout`), adapters/workflow_file.py (`Locations`, `load_config` returns `(Config, Locations)`), config.py removed, call sites rewired, tests updated and architecture tests extended. pyright 0 errors, pytest 663 passed. Spec: architecture.md (Configuration paragraph, domain list, architecture-test list) and workflow-config.md (load_config parts) updated; CLAUDE.md map updated. No ADR (ADR 0011 already covers it).
- 2026-11-11 14:23 samba: done: work-running -> work-review: validation passed (turns 3, $1.14): Split config.py into a plain domain/settings.py (new `Repository`, no `Layout`) and adapters/workflow_file.py, where `load_config` returns `(Config, Locations)`. The git adapter takes `Locations` plus the base branch, and the orchestrator logs the repo through `vcs.checkout_location()`. Pyright reports 0 errors and pytest passes (663). The architecture tests now bar pathlib and yaml from domain/ and app/, and the architecture chapter, workflow-config and the CLAUDE.md map are updated.
- 2026-11-11 14:27 samba: work.accept: work-review -> done: merged 04e9851, validated
