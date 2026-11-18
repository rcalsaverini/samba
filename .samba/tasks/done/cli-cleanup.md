---
priority: 3
depends_on: [task-stop-pauses-instead-of-restarting]
---
# CLI cleanup

Make the command surface consistently noun-verb: every command is either `run` or
`<noun> <verb>`, with nouns `task`, `plan`, `work`, `question` and `dev`.

Read first: SPEC §11 (CLI), `src/symphony/cli.py`, `docs/command-ideas.md` (grammar section),
and every test that runs `new`, `list`, `show`, `status` or `transitions` (grep `tests/`).

Decisions already made by the human:

- `symphony new "title"` becomes `symphony task new "title"`. The default destination flips: a new
  task lands in `plan-todo/`. `--skip-plan` puts it in `work-todo/` instead. The `--plan` flag
  goes away, and so does the top-level `new`. `--priority` and `--repo` stay.
- `task new` fills in the whole task, so the human never has to open the file after creating it:
  - Flags give every field: `task new [TITLE] [--body TEXT] [--depends-on ID[,ID...]]
    [--priority N] [--skip-plan]`. With a TITLE and no TTY, missing fields take their defaults
    (empty body, no dependencies, priority 3, planning on). This is the scripting path and what
    most tests use.
  - On a TTY (stdin and stdout), it prompts for each field the flags did not give, in this order:
    `Title:` (required, re-asked if empty), `Description (end with an empty line):` (multi-line,
    read until the first empty line), `Depends on (ids or prefixes, comma separated, empty for
    none):`, `Plan first? [Y/n]`. Priority is never prompted (flag only). Prompts read stdin, not
    `/dev/tty`.
  - Dependencies are resolved with `resolve_task_id` (prefixes allowed) and written as full ids in
    `depends_on`. An unknown or ambiguous id is re-asked at the prompt, and is exit 2 when given by
    flag.
  - No TITLE and no TTY: exit 2 with a usage message, nothing created.
  - The task file it writes is front matter (`priority`, `depends_on` when non-empty), `# Title`,
    a blank line, the body. The placeholder text "Describe the goal, the context and the
    acceptance criteria." is no longer written. stdout stays only the new file's path.
  - Tests: flags-only creation (body, dependencies resolved from a prefix, `--skip-plan`,
    priority), an unknown dependency by flag (exit 2, nothing created), no TITLE and no TTY
    (exit 2), and one pty test that answers all four prompts (reuse the pty approach in
    `tests/test_work_accept.py`).
- Remove the top-level aliases `list` and `show` and the top-level `status`. `task list` and
  `task show` are the only spellings. No deprecation shims: this is a single-user v0.
- `symphony transitions` becomes `symphony dev transitions`, with output unchanged. In
  `symphony --help` the `dev` group is listed apart from the user commands (its help text says it
  is for working on Symphony itself). The drift test between SPEC and the table keeps running it
  through the CLI, since the black-box suite must never import `symphony`.
- Update every test that used the old spellings (do not keep the old ones working to save test
  edits). Add tests: `task new` lands in `plan-todo/`, `task new --skip-plan` lands in
  `work-todo/`, the removed commands (`new`, `list`, `show`, `status`, `transitions`) are usage
  errors (exit 2), `dev transitions` prints the table.
- Update SPEC §11 (usage block and text), any other SPEC mention of the old commands (grep), and
  `CLAUDE.md`. `docs/command-ideas.md` is a historical design doc: add one line at its top noting
  the CLI cleanup changed some spellings, nothing else. No em-dashes.

Acceptance:

- `symphony --help` lists only `run`, `task`, `plan`, `work`, `question` and `dev`.
- `uv run pyright` 0 errors, `uv run pytest -q` passes.

## Plan
### Approach

All changes are in `src/symphony/cli.py` (parser plus dispatch), `src/symphony/prompts.py` (drop the placeholder template), and tests and docs. Write the black-box tests first, then the implementation. The black-box suite must never import `symphony`. Drive everything through `sb.run(...)`, and use pty for the TTY test.

Facts found while reading the code:
- `main()` in `cli.py` builds the parser. Top-level `status`, `list`, `show`, `new` and `transitions` exist. `--repo` is added in a loop over a list of subparsers (`cli.py:413`).
- `transitions` is handled before `load_config`, so it needs no repo. `sb.run` always appends `--repo`, so `dev transitions` must accept `--repo` and ignore it, with no config load.
- `cmd_new` uses `TASK_TEMPLATE` (`prompts.py:126`, only used by `cli.py`). Remove the template. Check for other uses with grep.
- `resolve_task_id(tasks, text)` raises `ResolveError`, and `.render()` gives the message. Use it for dependencies.
- The existing pty pattern is in `tests/test_work_accept.py::test_tty_prompt`. It uses `pty.openpty()`, `symphony_cmd()` from conftest, `stdin=slave, stdout=slave`, then `os.write(master, ...)`. `confirm()` already detects a TTY with `sys.stdin.isatty() and sys.stdout.isatty()`. `task new` uses the same check.

### Steps

- [ ] 1. Tests first, with the new spellings. Do not keep old spellings working.
  - [ ] `tests/test_blackbox.py` (`test_new_command_creates_todo_task`, ~line 424): rewrite to `task new`. It now lands in `plan-todo/`. Assert `# Add CSV export!`, `priority: 2` and the slug dedupe (`-2`). Assert the placeholder text is absent.
  - [ ] New `tests/test_task_new.py`, with no pty except the last test:
    - [ ] `--skip-plan` lands in `work-todo/`.
    - [ ] Flags only: `--body "text"`, `--depends-on <prefix>`, `--priority 4`. Create the dependency first with `sb.add_task`. Assert the file is exactly front matter (`priority`, plus `depends_on` as full ids), `# Title`, a blank line, then the body. With no `--depends-on` there is no `depends_on` line. Check the front-matter format against how `config`/`tasks` parse `depends_on` (list syntax in SPEC §15). Assert stdout is only the file path.
    - [ ] Default priority is 3 with a TITLE and no TTY. Check whether `priority: 3` is written. Settle it and document it in SPEC.
    - [ ] Comma-separated `--depends-on a,b`.
    - [ ] An unknown `--depends-on` gives exit 2 and creates nothing (no file in any state folder). Do the same for an ambiguous prefix.
    - [ ] No TITLE and no TTY (subprocess with captured stdio) gives exit 2, a usage message on stderr, and nothing created.
    - [ ] pty test: answer all four prompts (`Title:`, `Description (end with an empty line):` with a multi-line description ending in a blank line, `Depends on (...)` with a prefix, `Plan first? [Y/n]` with `n`). Assert the file is in `work-todo/` with the resolved `depends_on`, the body and the title. Also test re-asking: an empty title, then an unknown dependency, then a valid one. Read from the master fd in a loop with a timeout, to avoid deadlocks and flaky output.
  - [ ] New `tests/test_cli_surface.py` (or in test_blackbox):
    - [ ] Each of `new`, `list`, `show`, `status`, `transitions` gives exit 2 (argparse invalid choice).
    - [ ] `dev transitions` exits 0 and prints the table (header row and e.g. `plan.accept`).
    - [ ] `symphony --help` lists exactly `run, task, plan, work, question, dev`. Parse the `{...}` choices line or the command list. Check how argparse renders it, since the usage line shows choices. Use `sub.metavar` or a custom format so `dev` is shown apart, as in the next step.
  - [ ] Replace `test_aliases_match_canonical_forms` (test_blackbox.py:624) with the removed-commands test. `test_list_without_filter_equals_status` (~463) and `test_status_command_lists_tasks` (~434) move to `task list`.
  - [ ] Replace `sb.run("status")` with `sb.run("task", "list")` in `tests/test_planning.py:223`, `tests/test_layout.py:80` and `tests/test_dependencies.py:124`. Replace `sb.run("new", "Design the thing", "--plan")` in `test_planning.py:214` with `task new "Design the thing"` (the default is now plan-todo). Adjust the assertion on the destination if it changes.
  - [ ] Replace `sb.run("transitions")` with `sb.run("dev", "transitions")` in `tests/test_blackbox.py:514`, `tests/test_transitions.py:23` and `:258`. Update the docstring at test_transitions.py:3. Also grep `tests/` for helper functions that create tasks via `new`. Grep showed none other than the ones above.
- [ ] 2. Implement in `cli.py`.
  - [ ] Remove the `status`, `list`, `show`, `new` and `transitions` top-level subparsers and the matching dispatch branches (`cli.py:421`, `462-468`). Remove `cmd_task_list`'s mention of `status` in its docstring, and fix the module docstring on line 1.
  - [ ] Add `task new [TITLE] [--body TEXT] [--depends-on IDS] [--priority N] [--skip-plan] [--repo]` in `task_sub`. TITLE is `nargs="?"`. `--depends-on` takes a string split on commas, and strip empty parts. Remove `--plan`.
  - [ ] Add a `dev` noun with a subparser `transitions` (and `--repo`, accepted and unused). Handle it before `load_config`. Note that the loop adding `--repo` must include the new parsers. `args.command == "dev"` and `args.dev_command == "transitions"`.
  - [ ] Keep `dev` listed apart in `--help`. Use the `help` text "commands for working on Symphony itself". Suggested route: `add_subparsers(dest="command", required=True, title="commands", metavar="COMMAND")` for user commands, and use `help=argparse.SUPPRESS` for `dev` in the first group. Add a custom epilog or `ArgumentParser.format_help` override that appends a "Development commands:" section with `dev`. The acceptance criterion is that `--help` lists only the six nouns, and `dev` is visibly separate (a section header is enough). Make sure `dev` still parses with SUPPRESS. Verify by running `uv run symphony --help`.
  - [ ] `cmd_task_new(config, title, body, depends, priority, skip_plan)`:
    - TTY check: `sys.stdin.isatty() and sys.stdout.isatty()`.
    - Decide which fields are missing: title (if None), body (if `--body` is None), depends (if `--depends-on` is None), plan (if `--skip-plan` is not given). On a TTY, prompt only for those fields, in the order Title, Description, Depends on, Plan first. Do not prompt for priority.
    - Prompts read `sys.stdin` (`input()` or `sys.stdin.readline()`; `print(..., end="", flush=True)` for the prompt text, matching `confirm()`). Description is read until the first empty line (handle EOF as end). Title is re-asked while empty. Dependencies: re-ask on `ResolveError` or an unknown id, printing the error to stderr. `Plan first? [Y/n]`: empty or `y` means plan, `n` means skip.
    - Without a TTY and without a title: print a usage message to stderr and return 2, before touching the store. Use `p_tnew.error(...)` or print the usage.
    - Resolve dependencies through `resolve_task_id(tasks, text)`, then check the task actually exists (`tasks.state_of(id) is not None`), since `resolve_task_id` may return the text as-is when nothing matches. Read `views.py` to confirm how it signals unknown ids, and handle both cases. By flag: error to stderr and return 2, nothing created. Validate all flags before writing anything.
    - Write the file: front matter with `priority: N` and `depends_on` (only when non-empty), `# Title`, a blank line, then the body. If there is no front matter, there is no `---` block. Match the existing front-matter parser's list format for `depends_on` (see `tasks.py`/`deps.py`). Destination: `plan-todo` by default, `work-todo` with `--skip-plan`. Print only the path. Keep slug and dedupe logic. Hold `repo_lock` if existing creation did not (it did not; keep it that way unless tick races matter, and say so in the Log if changed).
  - [ ] Remove `TASK_TEMPLATE` from `prompts.py` and its import.
- [ ] 3. Docs.
  - [ ] `SPEC.md` §11: replace the usage block (`task new ...` with all flags, `dev transitions`, remove `list`, `show`, `status`, `new`, `transitions` lines). Describe `task new` prompts, defaults, dependency resolution, exit codes and `dev` in the text. Add `task new` to the command lists where relevant. Grep SPEC for old spellings: lines ~178 (`symphony transitions` becomes `symphony dev transitions`), ~190 (`new` has no source folder: `task new`), 755 (`symphony status` becomes `task list`), 882 and 890 (`status` mentions), 984, 997, 1113 to 1114 (remove the `--plan` line, describe the new default), 1146 (`new --plan` scenario becomes `task new` lands in plan-todo), 1153, 1183. Also `require_plan` or config text, if it mentions `new`. Check §11's exit-code bullet for the usage-error case.
  - [ ] Regenerate the embedded transitions table only if the table itself changed (it should not). The drift test must still pass.
  - [ ] `CLAUDE.md` Map: the `cli.py` line (`run`, `task new|list|show|retry|stop|discard`, `plan`/`work`/`question` commands, `dev transitions`, no aliases) and the `transitions.py` line (`symphony dev transitions`).
  - [ ] `docs/command-ideas.md`: add one line at the very top, e.g. "Note: the CLI cleanup changed some command spellings (`task new`, `dev transitions`; top-level `new`, `list`, `show`, `status` removed); this doc is historical." Change nothing else. No em-dashes anywhere.
- [ ] 4. Check there are no remaining references: `rg "symphony (new|list|show|status|transitions)"` and `rg '"(new|status|list|show|transitions)"' src tests`. Prompts in `prompts.py` may mention `symphony new` or `status`: grep and fix if so.
- [ ] 5. Run `uv run pyright` (0 errors), then `uv run pytest -q` as separate plain commands.
- [ ] 6. Append a line to the task file's `## Log` saying the spec details settled (priority default written or not, `dev` help layout, `--repo` accepted by `dev transitions`).

### Files to change

- `src/symphony/cli.py`, `src/symphony/prompts.py`
- `tests/test_blackbox.py`, `tests/test_planning.py`, `tests/test_layout.py`, `tests/test_dependencies.py`, `tests/test_transitions.py`, plus new `tests/test_task_new.py` and `tests/test_cli_surface.py`
- `SPEC.md`, `CLAUDE.md`, `docs/command-ideas.md`

### Risks

- `sb.run` appends `--repo` to every call, so `dev transitions` must accept it. The removed-command tests then get exit 2 from argparse regardless of `--repo`.
- Splitting `--help` so `dev` appears apart while the "lists only six" criterion holds: argparse has no native support, so use a custom group or epilog and test it.
- pty tests can hang or flake. Use timeouts, read output until the expected prompt, and kill the process on failure.
- `resolve_task_id` behavior on unknown ids: confirm by reading `views.py` before writing the dependency checks.
- `priority` default: the task says default 3. Decide whether to write `priority: 3` explicitly. The task says front matter holds `priority`, so write it always. Make tests match, and note the choice in SPEC.
- Existing tests may assert the old placeholder text or `Describe the goal` (grep). Update if so.
- `tasks.ensure()` must run before writing to `plan-todo`.

### How to verify

- `uv run pyright` reports 0 errors.
- `uv run pytest -q` passes (about 25s).
- `uv run symphony --help` lists only `run`, `task`, `plan`, `work`, `question`, `dev`, with `dev` separate. `symphony new x`, `list`, `show x`, `status` and `transitions` each exit 2. `symphony dev transitions` prints the table.
- In a scratch repo: `symphony task new "Hello" --body "b" --depends-on <prefix>` prints a path in `plan-todo/`, and the file has the expected content. Add `--skip-plan` and the path is in `work-todo/`.
- `rg` finds no old spellings in SPEC, CLAUDE.md or tests, and no em-dashes were added.

### Suggested subtasks

None: it is one coherent change. If it must be split, do (a) the removal and `dev` group with the test updates, then (b) `task new` with prompts.

## Log
- 2026-11-07 21:46 symphony: dispatch_plan: plan-todo -> plan-running
- 2026-11-07 21:47 symphony: planned: plan-running -> plan-review: planned (turns 1, $0.21): Plan to turn the CLI into strict noun-verb (`run`, `task`, `plan`, `work`, `question`, `dev`), add a full-featured `task new` (flags plus TTY prompts), remove the old top-level commands, and update tests, SPEC, CLAUDE.md and docs. Tests come first.
- 2026-11-07 22:58 symphony: plan.accept: plan-review -> work-todo
- 2026-11-07 22:59 symphony: dispatch_work: work-todo -> work-running
- work: all plan steps done (tests first, cli.py, prompts.py, SPEC, CLAUDE.md, command-ideas). Settled details, all in SPEC §11: `priority: 3` is always written (default 3); `--help` shows the five user commands in the normal list and `dev` in a "development commands" epilog section (argparse cannot hide a subparser's help line, so `dev` has no `help=`); `dev transitions` accepts `--repo` and ignores it, no config load; `task new` takes no repo lock; EOF at a prompt is exit 1. Note: `uv run symphony --help` and sed were denied, so help layout was checked through a test only.
- 2026-11-07 23:06 symphony: permission denied: Bash (sed -i 's/sb.run("status")/sb.run("task", "list")/' tests/test_planning.py tests/test_layout.py tests/test_dependencies.)
- 2026-11-07 23:06 symphony: permission denied: Bash (uv run symphony --help)
- 2026-11-07 23:06 symphony: permission denied: Bash (grep -nE "symphony (new|list|show|status|transitions)|\bstatus\b|`new`|--plan|\bnew\b|transitions" SPEC.md)
- 2026-11-07 23:06 symphony: permission denied: Bash (grep -nE "symphony (new|list|show|status|transitions)|--plan|`new`|`status`|`list`|`show`" SPEC.md CLAUDE.md)
- 2026-11-07 23:09 symphony: done: work-running -> work-review: validation passed (turns 2, $0.99): The CLI is now noun-verb: `run`, `task`, `plan`, `work`, `question` and `dev`. The old top-level `new`, `list`, `show`, `status` and `transitions` are usage errors (exit 2). `task new` takes flags plus TTY prompts and defaults to `plan-todo/`. `dev transitions` replaces `transitions`. `uv run pyright` reports 0 errors and `uv run pytest -q` passes (259 tests). Work is committed on `symphony/cli-cleanup` in two commits (code and tests, then docs). I could not run `uv run symphony --help` directly (denied), so the help layout is checked only through the new test. Where the spec left a detail open, I settled it and wrote it into SPEC §11: - **Priority:** `priority: 3` is always written to the front matter. - **`dev` in help:** `dev` is listed in a "development commands" section after the five user commands. It can't be hidden from the main command list with `help=` (argparse printed `==SUPPRESS==`), so it has no `help=` text. - **`dev transitions`:** it accepts `--repo` and ignores it, and it loads no config. - **Locking:** `task new` takes no repo lock, since it only writes one new file. - **End of input:** EOF at a prompt exits 1 and creates nothing. The new tests are in `tests/test_task_new.py` (including the pty prompt tests) and `tests/test_cli_surface.py`.
- 2026-11-07 23:13 symphony: work.accept: work-review -> done: merged 061c8b2, validated
