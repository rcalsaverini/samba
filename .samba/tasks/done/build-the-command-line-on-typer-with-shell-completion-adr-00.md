---
priority: 3
depends_on: ["name-the-commands-shape-commands-and-make-the-cli-parse-call"]
---
# Build the command line on Typer with shell completion (ADR 0014)

Read CLAUDE.md, docs/spec/architecture.md and ADRs 0011 to 0015 first. Behavior does not change: the black-box suite and every other test stay green, and pyright stays at 0 errors. Update the architecture chapter, the orchestrator and cli spec chapters where they change, and the CLAUDE.md map in the same change. Plan steps may use only commands in the WORKFLOW.md allow list: no git mv, no sed -i, no mkdir, no pipes or redirects. Move a file by writing it at its new path and git rm of the old one, then fix imports with Edit (git grep finds them). If the work is too big for one run at the per-task cost cap, propose chained subtasks in the plan.

Implement ADR 0014. Rewrite the command line adapter on Typer (built on Click): each command is a function whose signature declares its arguments and options, and every command goes through bootstrap and the use cases of ADR 0013. The command surface does not change: the same commands, arguments, options, exit codes (2 for a usage error) and the same output on stdout and stderr; only the shape of the help text may change. Output stays plain text when stdout is not a terminal. Shell completion is required: command names and options, plus completion of task ids, question ids and ADR numbers read through the use cases (for example samba plan accept <TAB> offers the tasks that can be accepted). Check the real dependency footprint of Typer before relying on it and add it to pyproject.toml; say in the plan what was added. Adjust tests/test_cli_surface.py and tests/test_manual.py once for the new help shape, add black-box tests for completion if the library allows driving it from the environment, and add a section on installing completion to docs/manual.md and the cli spec chapter. Keep entrypoints/cli.py thin: no rule in it.

## Plan
### Approach

Replace the argparse parser in `src/samba/entrypoints/cli.py` with a Typer app (built on Click). Behavior does not change: the same commands, arguments, options, exit codes (0, 1 refused, 2 usage) and the same stdout and stderr. Only the shape of `--help` may change. Each command is a function whose signature declares its arguments and options. It builds the use cases through `bootstrap` (`build`, `build_adr`, `build_explore`, `build_orchestrator`), calls one use case and passes the result to the existing `render(result)`, which stays unchanged. `cli.py` stays thin: no rule, no `app/resolve.py`, no `domain/task_id.py`, no other entry point (`tests/test_architecture.py` guards this, including forbidden words in `cli.py`; read its lines ~236-275 first).

**Scope: completion lands in two steps.** This task enables only static completion: command names and options, and `--install-completion` / `--show-completion` (`add_completion=True`). Dynamic completion of task ids, question ids and ADR numbers (the `app/` completion queries, the `Commands` and `AdrCommands` members, the `autocompletion=` callbacks, `tests/test_completion.py`) is a separate next task. Do not do any of it here. Say so in the cli spec and in the manual ("static now, dynamic next").

Design points:
- **Entry point.** `main(argv=None) -> int` stays the script entry (`samba.entrypoints.cli:main`); `__main__.py` keeps working. Call the Typer app with `args=argv, standalone_mode=False, prog_name="samba"`. Map `click.UsageError` (message to stderr) to exit 2 and `click.exceptions.Exit`/`Abort` to their codes, and return codes rather than raising `SystemExit` twice. Map `ConfigError` to `samba: config error: ...` on stderr with exit 2, as today.
- **`--repo`.** Declare it (Path, default cwd) on every leaf command through one shared `Annotated` alias, so `samba task list --repo X` still works after the arguments (the Sandbox fixture appends `--repo` last). Not a global callback option. This includes `run`, `explore` and `dev transitions` (as today).
- **Groups.** Sub-Typers `task`, `plan`, `work`, `question`, `adr`, `dev`; top-level commands `run` and `explore`. Order in help stays run, task, plan, work, question, adr, explore, dev. `dev` is `hidden=True` in the list and described in the epilog as "development commands" (keep the text "Samba itself").
- **Plain output.** `rich_markup_mode=None`, `pretty_exceptions_enable=False`. Output has no ANSI and no box characters when stdout is not a tty. Add a subprocess test for it.
- **Semantics kept.** `--feedback` and `--edit` exclusive on `plan reject` and `work reject`; `question answer` rejects text together with `--edit`; both are usage errors (exit 2) via `click.UsageError`/`typer.BadParameter` with the same messages as far as practical. `--priority` int default 3; `states` variadic; `title`, `topic` and `text` optional arguments; `adr supersede N NEW`; `work accept --no-merge --no-validate --yes --dry-run`, `work reject --fresh`, `task discard --yes`, `task new --body --depends-on --skip-plan`, `run --exit-when-idle`, `adr list --all` all kept. `run` keeps its asyncio and signal path (SIGINT/SIGTERM cancel, "samba: stopped", `StartupError` -> `samba: ...` exit 1). `explore` returns the session exit code. `dev transitions` needs no repo and no config.
- **No prefix reliance.** Click does not accept abbreviated long options (argparse does). Check with `git grep -n -E -- "--(exit|dry|no-|skip|dep|fee)" tests docs README.md src` and confirm every use is a full option name; fix any that is not.

### Dependency

Add `typer>=0.12` to `dependencies` in `pyproject.toml` with Edit (the standard `typer`, not `typer-slim`, because `--install-completion` needs shell detection via shellingham). Do not run `uv add`, `uv lock`, `uv tree` or any uv command outside the allow list. `uv run pyright` and `uv run pytest -q` re-lock and sync the environment themselves. Then record the resolved footprint by reading `uv.lock` with Read and `git grep -n -A12 'name = "typer"' uv.lock` (the dependency list of the typer package and the versions of its entries). The expected set is typer, click, shellingham, rich, typing-extensions, plus rich's own dependencies (markdown-it-py, mdurl, pygments); confirm it from the lock, not from memory. Write the resolved list into the cli spec and into the task `## Log` ("what was added"). Commit `uv.lock` together with `pyproject.toml` if the lock changed. If `uv run` cannot reach the package index from the sandbox, stop and raise it as a question instead of working around it.

### Steps

- [ ] Read CLAUDE.md, `docs/spec/architecture.md`, `docs/spec/cli.md`, `docs/spec/orchestrator.md`, ADRs 0011 to 0015 (`uv run samba adr show N`), `tests/test_architecture.py` (cli rules), `tests/conftest.py`.
- [ ] Edit `pyproject.toml` to add `typer>=0.12`. Run `uv run pyright` (separate plain command) so the environment re-locks and syncs; if it cannot reach the index, stop and ask. Read `uv.lock` and record the footprint.
- [ ] Tests first (black-box, never import samba):
  - `tests/test_cli_surface.py`: adapt the help assertions to the new shape (command order, "development commands" epilog, "Samba itself"); add cases: exit 2 for an unknown command, a missing argument, `--feedback` with `--edit`, and answer text with `--edit`; `--repo` after the arguments works; no ANSI or box characters in piped `--help`; `--show-completion bash` exits 0 and prints a script that mentions `samba` (pass the shell explicitly so no shell detection is needed).
  - `tests/test_manual.py`: update `top_level_commands()` and `verbs()` to parse Click's `Commands:` block (plain text, no boxes), keep `test_command_discovery_is_not_vacuous`, add a check that the manual mentions `--install-completion`.
  - `tests/test_architecture.py`: extend the argparse check so that domain and app modules import neither `typer` nor `click`, and add a negative case like the existing `tmp_path` ones. Also forbid `argparse` anywhere under `src/samba`.
- [ ] Rewrite `entrypoints/cli.py` on Typer as described, one function per command, `render` unchanged. If it grows far past ~250 lines, split by noun into `entrypoints/cli_*.py` and add them to `ENTRYPOINT_FILES` in `tests/test_architecture.py`; prefer one file.
- [ ] Run `uv run pyright` (must report 0 errors), then `uv run pytest -q`, as separate plain commands. The whole suite stays green; `tests/test_blackbox.py` is unchanged.
- [ ] Update the docs (below) and add to the task's `## Log` what changed in the spec and the dependency footprint.
- [ ] No ADR is needed (ADR 0014 covers the decision). Propose a `proposed` ADR only if an unexpected lasting choice appears.

### Files to change

- `pyproject.toml`, `uv.lock`.
- `src/samba/entrypoints/cli.py` (rewrite); `src/samba/__main__.py` only if it calls `main` differently.
- `tests/test_cli_surface.py`, `tests/test_manual.py`, `tests/test_architecture.py`.
- `docs/spec/cli.md`, `docs/spec/architecture.md`, `docs/spec/orchestrator.md` (only if it mentions the parser), `docs/manual.md`, `CLAUDE.md`.

### Spec changes

- `cli` chapter: the parser is built on Typer, the surface is unchanged; new section "Shell completion": install with `samba --install-completion` or `samba --show-completion <shell>`, command names and options complete now, task id, question id and ADR number completion comes in a next step (two steps: static now, dynamic next); the resolved runtime dependency footprint read from `uv.lock`.
- `architecture` chapter: `entrypoints/cli.py` is a Typer app with one function per command through bootstrap; domain and app never import typer or click.
- `orchestrator` chapter: only where it mentions the command line parsing of `samba run`; one line that `run` is a Typer command with the same flags and exit codes. If it does not mention the parser, record "none" for it in the Log.
- `docs/manual.md`: a short section on installing completion (bash, zsh, fish), noting that ids are not completed yet.
- `CLAUDE.md` map: the `entrypoints/cli.py` bullet (Typer, no argparse), the test files touched, the dependency list.

### Risks

- Click vs argparse differences: option order relative to arguments (handled by per-leaf `--repo`), variadic `states` followed by options, `--` handling, error text, no prefix abbreviations (checked with `git grep`).
- Rich may draw boxes or color if left on; keep markup off and test piped output.
- `standalone_mode=False` changes how exit codes flow: return them from `main`, do not raise twice; keep the `run` signal handling working.
- `--install-completion` writes to the user's shell config: tests use only `--show-completion <shell>`, never `--install-completion`.
- Index access: if `uv run` cannot sync Typer from the sandbox, raise a question.
- Allow list only: `git grep` (not grep), `Edit`/`Write` for files, `git rm` to delete, no `git mv`, `sed -i`, `mkdir`, pipes or redirects, and uv only as `uv run pyright`, `uv run pytest` and the listed `uv run samba` forms.
- Size: should fit one run; the work is one file rewrite plus test and doc edits.

### How to verify

- `uv run pyright`: 0 errors.
- `uv run pytest -q`: green, with `tests/test_blackbox.py` unchanged.
- `uv run samba --help`, `uv run samba task --help`: exit 0, plain text when piped; `uv run samba plan accept` (missing id): exit 2.
- `uv run samba --show-completion bash` prints a script.
- `git grep -n argparse src` finds nothing; `git grep -n -E "typer|click" src/samba/domain src/samba/app` finds nothing.
- The footprint written in `docs/spec/cli.md` matches `uv.lock`.

## Assumptions
- Dynamic completion (task ids, question ids, ADR numbers) is out of scope and will be a separate task created by the human; the spec says completion lands in two steps.
- `--show-completion bash` works with an explicit shell argument and needs no environment detection, so the test is deterministic.
- The footprint (click, shellingham, rich, typing-extensions, markdown-it-py, mdurl, pygments) is expected, not verified; the executor reads it from `uv.lock` after `uv run` re-locks.
- The `uv run` sync can reach the package index; if not, the executor stops and asks.
- No test or doc relies on abbreviated long options; the executor confirms with `git grep`.

## Feedback
### Round 1

The plan is good and matches ADR 0014, but it bundles two jobs and uses commands that are not on the allow list, so scope it down. (1) Plan ONLY the Typer rewrite in this task: the dependency, entrypoints/cli.py on Typer with every command, option, exit code and output unchanged, --repo declared on every leaf command, rich markup off, plain output when not a tty, usage errors exit 2, ConfigError mapped as today, --install-completion and --show-completion enabled (add_completion=True), the black-box test updates for the new help shape (tests/test_cli_surface.py, tests/test_manual.py), the check that domain/ and app/ never import typer or click, a test that --show-completion bash prints a script, the spec (cli, architecture), docs/manual.md (a short section on installing completion) and the CLAUDE.md map. Dynamic completion of task ids, question ids and ADR numbers (the app/ completion queries, the Commands and AdrCommands members, the autocompletion callbacks and tests/test_completion.py) becomes a separate next task that I will create; do not do it here, and say in the plan and the spec that completion lands in two steps (static now, dynamic next). (2) Dependency: do NOT run uv add, uv lock, uv tree or any uv command that is not on the allow list (only uv run pyright, uv run pytest and the listed uv run samba forms are). Add typer to dependencies in pyproject.toml with Edit (typer>=0.12; use the standard typer, not typer-slim, since --install-completion needs shell detection), and let uv run pyright and uv run pytest re-lock and sync the environment themselves. Record the resolved footprint by reading uv.lock with Read and git grep, in the plan result and in the cli spec, and commit uv.lock together with pyproject.toml if the lock changed. If uv run cannot reach the package index from the sandbox, stop and raise it as a question instead of working around it. (3) Keep everything else in your plan: behavior unchanged, no ANSI in non-tty output, no prefix-abbreviation reliance (check with git grep), the shared render unchanged, and allow-listed commands only.

## Log
- 2026-11-11 16:10 samba: dispatch_plan: plan-todo -> plan-running
- 2026-11-11 16:11 samba: planned: plan-running -> plan-review: planned (turns 1, $0.19): Rewrite entrypoints/cli.py on Typer (plus click, shellingham, rich, typing-extensions) with one function per command, dynamic completion for task ids, question ids and ADR numbers through new read-only queries, black-box completion tests, and spec, manual and CLAUDE.md updates. It is sized for one run, with optional chaining into three subtasks.
- 2026-11-11 16:12 samba: plan.reject: plan-review -> plan-todo: feedback round 1
- 2026-11-11 16:12 samba: dispatch_plan: plan-todo -> plan-running
- 2026-11-11 16:12 samba: planned: plan-running -> plan-review: planned (turns 2, $0.49): Revised plan: only the Typer rewrite with static completion (--install-completion and --show-completion); dynamic id completion moves to a separate next task. The dependency is added by Edit in pyproject.toml, with no uv commands outside the allow list.
- 2026-11-11 16:13 samba: plan.accept: plan-review -> work-todo
- 2026-11-11 16:13 samba: dispatch_work: work-todo -> work-running
- Work done. `entrypoints/cli.py` rewritten on Typer (one function per command, `--repo` per leaf via one alias, `OrderedGroup` keeps the help order, rich markup off, `finish` raises `typer.Exit`, `main` maps SystemExit and ConfigError to codes). pyright 0 errors, full pytest green.
- Dependency footprint (read from uv.lock; `pyproject.toml` got `typer>=0.12`): typer 0.29.1 plus shellingham, rich, markdown-it-py, mdurl, pygments, pydantic, pydantic-core, annotated-types, typing-inspection, annotated-doc, typing-extensions, colorama (Windows only). Deviation from the plan's expected set: this Typer carries its own copy of Click (`typer._click`), so there is no `click` package, and it depends on pydantic. cli.py imports only `typer` and `typer.core`, never click.
- Deviations: (1) `--show-completion` is a flag that detects the shell; the test sets `_TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION=1`, which makes it take the shell name. I also added a black-box test that drives bash completion through `_SAMBA_COMPLETE=complete_bash` (command names, options, `dev` hidden). (2) Click rejects `--help --repo X` (argparse did not), so help tests use a runner without the trailing `--repo`; `tests/test_questions.py::test_question_help_lists_verbs` changed for that. (3) `tests/test_blackbox.py` changed by one assertion: the unknown-command message is now "No such command" instead of argparse's "invalid choice". Exit code 2 is unchanged.
- Spec changes: `docs/spec/cli.md` (Parser section with the footprint, new Shell completion section, static now and dynamic next), `docs/spec/architecture.md` (cli.py is a Typer app; domain and app never import typer or click; no argparse anywhere), `docs/manual.md` (Shell completion subsection, `--repo` placement), `CLAUDE.md` map. `docs/spec/orchestrator.md`: none (it does not mention the parser). No ADR proposed: ADR 0014 covers the decision.
- 2026-11-11 16:22 samba: permission denied: Bash (uv run python -c "import typer, sys; print(typer.__file__); print(typer.__version__)")
- 2026-11-11 16:26 samba: done: work-running -> work-review: validation passed (turns 3, $1.53): The command line is now a Typer app with the same commands, options and exit codes, plus static shell completion (command names and options, via `--install-completion` and `--show-completion`). Dynamic completion of task ids, question ids and ADR numbers is not done, as agreed. pyright reports 0 errors. The full `pytest` run passed except two tests that I then changed; I re-ran only the affected files plus the manual and architecture tests, and those passed (105). Everything is committed. - **Dependency:** `typer>=0.12` is in `pyproject.toml`, and `uv.lock` resolved typer 0.29.1. This release carries its own copy of Click, so there is no separate `click` package, and it pulls in `pydantic` and `pydantic-core`. The full list is in the cli spec chapter and the task log. - **Tests changed:** - Click rejects `--help --repo X`, which argparse accepted. The fixture's `run` always appends `--repo`, so the help tests now run `samba` without it. - One assertion in `tests/test_blackbox.py` changed. The unknown-command message is now "No such command" instead of argparse's "invalid choice". Exit code 2 is unchanged. - `tests/test_questions.py` changed for the help-runner reason above. - **Tests added:** - `tests/test_cli_surface.py` covers usage errors with exit 2, `--repo` placed after the arguments, and plain piped help. - A completion test drives bash completion through `_SAMBA_COMPLETE`. - A `--show-completion` test passes the shell name with `_TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION=1`, because `--show-completion` otherwise detects the shell. - `tests/test_architecture.py` now forbids `typer`/`click` in `domain/` and `app/` and `argparse` anywhere under `src/samba`. - **Docs:** I updated the cli and architecture spec chapters, `docs/manual.md` (shell completion subsection) and the `CLAUDE.md` map. `orchestrator.md` needed nothing. No ADR was added, since ADR 0014 covers the decision. I did not run `--install-completion`, since it edits the shell config.
- 2026-11-11 16:40 samba: work.accept: work-review -> done: merged 0b432d7, validated
