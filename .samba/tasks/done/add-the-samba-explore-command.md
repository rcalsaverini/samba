---
priority: 3
depends_on: ["add-the-samba-adr-commands", "add-the-lifecycle-scenarios-finish-the-architecture-checks-a"]
---
# Add the samba explore command

Implement phase 2 of the ADR flow: the explore launcher. Read ADRs 0001 to 0004 first.

First step, before any other work: ADR 0002 leaves open whether this should be a Samba command or only a Claude Code skill or slash command, since Samba gains little beyond passing a fixed allow list. Ask the human this as a question, with your recommendation and reasons, and do not plan the work until it is answered.

If it is a command, the scope is:
- `samba explore "topic"` starts an interactive `claude` session in the repository, with an ADR-writing guide appended to its instructions (one decision per ADR, proposed status, number by filename, the format from ADR 0001).
- It passes the allow list from ADR 0004 explicitly: samba task new, task list and show, question list and show, adr list and show. Never plan, work or adr accept or reject, task discard, stop or retry, or question answer.
- The guide tells the explorer to say what tasks it spawned and why.
- Black-box test with the fake claude that checks the argv and allow list.

Done when the chosen option works, the spec, manual and tests are updated, and pyright and the tests pass.

## Plan
### Approach

The command is still `samba explore ["topic"] [--repo PATH]`: an interactive `claude` session in the repo, with the guide appended to the system prompt, the ADR 0004 allow list passed explicitly, a deny list for what the explorer must never run, and no isolation from the user's settings. ADR 0002 and 0004 are not edited.

Layering, following `docs/spec/architecture.md`:

1. **Pure constants and spec (domain).**
   - `prompts.py` (already in `DOMAIN_MODULES`) gets `EXPLORE_GUIDE`, `EXPLORE_ALLOW` and `EXPLORE_DENY`.
   - A new `domain/launch.py` holds `LaunchSpec(argv: tuple[str, ...], cwd: str)` and the pure function `explore_launch(command, model, topic, cwd) -> LaunchSpec`. It has no I/O, and the cwd is opaque text.
2. **Use case, `app/explore.py`.** `StartExplore(settings, location, session)` with `run(topic: str | None) -> Explored | Refused`.
   - It builds the `LaunchSpec` and calls `session.run(spec)`.
   - It returns `Explored(exit_code)`. A `LaunchError` from the port becomes `refused("...")`.
   - It never prints and does not touch `os`, `subprocess` or `pathlib`.
   - `Explored` goes in `app/results.py` next to `Text` and `Written`.
3. **Port, `ports.py`.** `InteractiveSession` (Protocol):
   - `run(spec: LaunchSpec) -> int` runs the program attached to the person's terminal and returns its exit code.
   - It raises `LaunchError(message)` when the program cannot be started, for example because `claude` is not found. `LaunchError` is defined in `ports.py` next to `StoreError`.
   - It is not async. This is not an `AgentRunner`.
4. **Adapter, `adapters/interactive_session.py`.** `TerminalSession` runs `subprocess.run(spec.argv, cwd=spec.cwd)` with stdin, stdout and stderr inherited, and no capture.
   - It ignores SIGINT in Samba while the child runs and restores the handler afterwards, so Ctrl-C reaches `claude` and Samba exits with the child's code.
   - `FileNotFoundError` and `PermissionError` become `LaunchError`.
   - It reads no stream-json, and `ClaudeCliRunner` is not reused.
5. **Composition, `compose.py`.** `build_explore(repo) -> StartExplore`. It calls `load_config(repo)` (raises `ConfigError`) and takes only `config.agent.command` and `config.agent.model`, builds `TerminalSession` and wires the use case, like `build_adr`. Nothing else from the config is used: no lock, no journal, no `.samba/` access.
6. **CLI, `cli.py`.** The parser gets `explore` with an optional `topic` and `--repo`, plus a help line. `cmd_explore(args)`:
   - calls `build_explore`, mapping `ConfigError` to `samba: config error: ...` with exit 2, as `main` already does;
   - runs the one use case and maps the result: `Refused` goes through `_report`, and `Explored` returns its `exit_code`;
   - holds no rule.

### Argv built by `explore_launch`

`[*command, TOPIC?, "--append-system-prompt", EXPLORE_GUIDE, "--allowedTools", *EXPLORE_ALLOW, "--disallowedTools", *EXPLORE_DENY, ("--model", model)?]`

- The topic is the positional first prompt, placed right after the command because the flags after it are variadic. A missing topic means no positional.
- There is no `-p`, `--output-format`, `--json-schema`, `--permission-mode`, `--setting-sources`, `--strict-mcp-config`, `--settings` or `--add-dir`. The user's own settings and CLAUDE.md apply, and anything outside the allow list prompts the human.
- `EXPLORE_ALLOW`:
  - `Bash(samba task new:*)`, `Bash(samba task list:*)`, `Bash(samba task show:*)`
  - `Bash(samba question list:*)`, `Bash(samba question show:*)`
  - `Bash(samba adr list:*)`, `Bash(samba adr show:*)`
  - `Read`, `Grep`, `Glob`
  - `Edit(docs/adr/**)`, `Write(docs/adr/**)`, so ADR files can be written without a prompt.
- `EXPLORE_DENY`, each as `Bash(samba <x>:*)`: `plan`, `work`, `adr accept`, `adr reject`, `adr supersede`, `task discard`, `task stop`, `task retry`, `question answer`. Deny is a hard block, so it holds even if the user's settings allow these.

### The guide (`EXPLORE_GUIDE`, pure text, no em-dashes, generic wording "the project's ADRs")

Sections: Role, ADR writing, Background research and Reporting.
- **Role.** An interactive exploration with the human. The output is decisions, not code.
- **ADR writing.**
  - First run `samba adr list --all` and read the relevant ones with `samba adr show N`.
  - One decision per ADR, and split drafts that contain two.
  - Write `docs/adr/NNNN-short-title.md`, numbered by filename, with the next free number.
  - Front matter has `status: proposed`, `date` and `supersedes: []`.
  - The body has Context, Decision and Consequences (ADR 0001 format).
  - Never edit an accepted ADR: write a new one that supersedes it.
  - Never accept, reject or supersede. The human does that, in the chat or with `samba adr`.
- **Background research.** Use Claude Code subagents in the chat. Use `samba task new` only for work that must outlive the chat. Read the result with `samba task show`. Nothing is merged. Findings worth keeping go into an ADR.
- **Reporting.** Say what tasks were spawned and why, when they are spawned and again at the end of the session.

### Steps

Plan steps use allow-listed commands only: `git grep` (not `grep`), no pipes, no redirects, no `&&`, no `git mv`.

- [ ] Read `docs/spec/architecture.md`, ADRs 0011 and 0012, and the spec chapters `cli`, `running-claude`, `prompts` and `workflow-config`.
- [ ] Use `git grep -n "adr" -- tests/test_manual.py tests/test_architecture.py` to see how a new command and new modules are checked.
- [ ] **Tests first.**
  - [ ] `tests/fake_session.py`: `FakeSession` implements `InteractiveSession`. It records the `LaunchSpec`s it gets, returns a scripted exit code, and can be scripted to raise `LaunchError`.
  - [ ] `tests/test_app_explore.py` (unit, in-process, imports `samba.app`, the domain and the fake):
    - a topic gives `[*command, topic, ...]` with `cwd` equal to the repo location;
    - no topic gives no positional;
    - `--model` is present only when a model is configured;
    - there is no `-p` and no `--permission-mode`;
    - `--allowedTools` equals the exact ADR 0004 list above;
    - `--disallowedTools` equals the deny list;
    - the allow and deny lists do not overlap, and every forbidden command of ADR 0004 is denied;
    - the guide contains `proposed`, `docs/adr`, one decision per ADR, `NNNN`, and the sentence about reporting spawned tasks and why;
    - `Explored(exit_code)` carries the session's exit code;
    - a `LaunchError` becomes `Refused("refused", ("samba: ...",))`.
  - [ ] `tests/test_explore.py` (black-box, never imports `samba`), using `sb.run("explore", ...)` and `sb.calls("repo")`. The fake records calls under the cwd name, which is `repo` in the sandbox.
    - The argv starts with the topic and has no `-p`.
    - `--append-system-prompt` text contains the key phrases above.
    - `--allowedTools` has exactly the seven samba entries plus the file entries, and none of `plan`, `work`, `adr accept`, `adr reject`, `adr supersede`, `task discard`, `task stop`, `task retry`, `question answer`.
    - `--disallowedTools` lists each forbidden command.
    - The cwd the fake ran in is the repo (`--repo` is honoured).
    - `claude.model` from `WORKFLOW.md` becomes `--model`.
    - The fake's exit code is returned by `samba explore`.
    - A missing `WORKFLOW.md` gives exit 2 and `config error` on stderr, and nothing is launched.
    - A missing `claude` binary (`claude.command` pointing at a nonexistent program) gives exit 1 with a `samba:` message.
    - No `.samba/` directory is created.
  - [ ] Update `tests/test_cli_surface.py` to expect `explore` in the help (`["run", "task", "plan", "work", "question", "adr", "explore", "dev"]`, and rename the test from "seven nouns").
  - [ ] `tests/test_architecture.py`: append `domain/launch.py` to `DOMAIN_MODULES` and `app/explore.py` to `APP_MODULES`.
  - [ ] Run the new tests once and see them fail for the right reason.
- [ ] **Implement.** `domain/launch.py`, the constants in `prompts.py`, `LaunchError` and `InteractiveSession` in `ports.py`, `Explored` in `app/results.py`, `app/explore.py`, `adapters/interactive_session.py`, `compose.build_explore`, the parser and `cmd_explore` in `cli.py`.
  - Keep `cli.py` free of the names the architecture test forbids (`human_events`, `merge.`, `TaskId.slug`, `Machine`), and keep `compose.py` the only place that builds adapters.
  - Keep stream-json field names out of the new adapter, since only `adapters/claude_cli.py` may mention them.
  - Keep `Path`, `mtime`, `sidecar` and `front matter` out of `domain/` and `app/` code.
- [ ] **Spec.**
  - `architecture.md`: add the `InteractiveSession` row to the Ports table (`run(spec) -> exit code`, raises `LaunchError`, adapter `TerminalSession` in `adapters/interactive_session.py`) and mention `build_explore` in the composition paragraph.
  - `cli.md`: add the usage line, the `explore` section (argv, allow and deny lists, exit codes, no lock, no `.samba/` access, config needed only for `claude.command` and `claude.model`), and fix the "every command is `run` or `<noun> <verb>`" sentence and the `--help` description, since `explore` is a verb-less command.
  - `running-claude.md`: an "Interactive explore session" paragraph. It is not headless, is not isolated, nothing parses its output, and the allow list is passed explicitly.
  - `prompts.md`: the explore guide.
  - Record the resolution of the open point in ADR 0002 as "settled here" in `cli.md`. Do not edit ADR 0002.
- [ ] **Manual and map.**
  - Add a `samba explore` section to `docs/manual.md`, since `tests/test_manual.py` fails otherwise. Cover the session, the allow and deny lists, that ADRs come out as `proposed`, and how to accept them with `samba adr`.
  - Update the CLAUDE.md map: `cmd_explore`, `compose.build_explore`, `domain/launch.py`, `app/explore.py`, `adapters/interactive_session.py` and `tests/fake_session.py`.
- [ ] Add a `## Log` line to the task file saying the details the spec left open were settled (deny list, `Edit` and `Write` scoped to `docs/adr`, no isolation, SIGINT handling).
- [ ] Run `uv run pyright` (0 errors), then `uv run pytest -q`, as separate plain commands.

### Files to change

- New: `src/samba/domain/launch.py`, `src/samba/app/explore.py`, `src/samba/adapters/interactive_session.py`, `tests/fake_session.py`, `tests/test_app_explore.py`, `tests/test_explore.py`.
- Edit: `src/samba/prompts.py`, `ports.py`, `app/results.py`, `compose.py`, `cli.py`.
- Edit tests: `tests/test_cli_surface.py`, `tests/test_architecture.py`.
- Docs: `docs/spec/architecture.md`, `cli.md`, `running-claude.md`, `prompts.md`, `docs/manual.md`, `CLAUDE.md`.

### Risks

- **Allow and deny rule syntax.** `Edit(docs/adr/**)` and the deny-over-allow precedence must match what the installed Claude Code does. The fake cannot check this, and the agent cannot run `claude` (not on the allow list). Use the syntax as written (gitignore-style path patterns, `Bash(prefix:*)` rules, deny wins over allow) and say in the spec and in the `## Log` that it was not verified against a real claude, so the human checks it in one real run.
- **Real TTY.** Tests cannot exercise the terminal, and the agent cannot run `samba explore`. State in the final report that the real run is still to be done by the human.
- **SIGINT.** If Samba kept the default handler, Ctrl-C would raise `KeyboardInterrupt` in the parent while the child runs. The adapter ignores SIGINT only while the child runs.
- **Architecture test rules.** The use case must not import `os`, `subprocess` or `pathlib`, and `cwd` is text. `prompts.py` is in `DOMAIN_MODULES`, so the guide must stay free of I/O imports.
- **`--help` and manual drift.** `test_cli_surface` and `test_manual` both read the real help output, so they fail until the new command is added to both the surface test and the manual.
- **Per-task paths.** The fake claude keys its call log on the cwd name, so the black-box tests depend on the sandbox repo being named `repo`.

### How to verify

1. `uv run pytest -q tests/test_app_explore.py tests/test_explore.py tests/test_cli_surface.py tests/test_architecture.py tests/test_manual.py`. The new tests fail before the implementation and pass after.
2. `uv run pyright` reports 0 errors.
3. `uv run pytest -q` passes in full.
4. `uv run samba --help` lists `explore` (the black-box tests cover the rest of the command surface; `uv run samba explore ...` is not on the allow list, so do not run it).
5. The real interactive run in a throwaway repo is done by the human after merge. Say so in the final `## Log` line.

### Suggested subtasks

None. The pieces depend on each other and are small enough for one pass.

## Assumptions
1. The use case receives the session port and calls it, returning `Explored(exit_code)`. This lets the CLI map the result like every other command, and means the real adapter uses `subprocess.run` (not `execvp`), so the process comes back with the child's exit code.
2. `LaunchSpec` lives in a new pure module `domain/launch.py`, and the guide and the two lists are in `prompts.py`, which is already in `DOMAIN_MODULES`.
3. Beyond the samba commands of ADR 0004, the allow list adds `Read`, `Grep`, `Glob`, and `Edit` and `Write` scoped to `docs/adr/**`, so the explorer can write ADRs. A deny list is added as a hard block.
4. `explore` is a top-level command, not a noun, so the spec sentence "every command is `run` or `<noun> <verb>`" and the `--help` surface test change.
5. `build_explore` loads the whole `WORKFLOW.md` through `load_config` but uses only `claude.command` and `claude.model`. A missing or invalid config is exit 2, like the other commands.
6. I read architecture.md, the real `compose.py`, `ports.py`, `cli.py` and the test files, but not ADRs 0011 and 0012 themselves. The first step of the plan is to read them.
7. The allow and deny rule syntax matches Claude Code's, which has to be checked during implementation.

## Questions
### q1 (round 1, answered)

Should exploration be a Samba command (`samba explore "topic"`) or only a Claude Code skill or slash command? I recommend the command.

Context: ADR 0002 leaves this open. For the command: it enforces the ADR 0004 allow list through explicit `claude` flags regardless of user settings, it is covered by black-box tests with the fake claude, and it ships and versions with Samba. For a skill: less code, but the allow list depends on the user's permission mode, nothing tests it, and the skill must be copied into each repo. The answer decides the whole scope: a CLI command with tests, spec and manual updates, or a single skill file.

Answer: It should be a command that puts me in a session with the agent, with exploration skills loaded

## Feedback
### Round 1

Your worktree is now reset to current main, which has the new architecture. Re-read CLAUDE.md, docs/spec/architecture.md and ADRs 0011 and 0012 first; the plan was written against deleted code (claude.py, tasks.py). Redo it so that: (1) explore is a use case in src/samba/app/ that returns a launch spec (argv, cwd); the guide, allow list and deny list are pure constants (prompts.py or domain), no I/O; (2) a new port in ports.py and an adapter in src/samba/adapters/ do the exec of an interactive claude; ClaudeCliRunner stays the only reader of stream-json and is not reused for this; (3) cmd_explore in cli.py is thin: it calls compose (add a build entry that needs only claude.command and claude.model, like build_adr), runs the one use case, prints the result and maps its kind to the exit code; cli.py holds no rule and compose.py is the only place that builds adapters; (4) tests: a fake of the new port plus a unit or scenario test for the use case (argv, allow and deny lists), a black-box test with the fake claude for the argv, and append any new domain or app module to DOMAIN_MODULES or APP_MODULES in tests/test_architecture.py; (5) update spec chapters architecture (ports table), cli, running-claude, prompts, manual, and the CLAUDE.md map; (6) keep the plan steps to allow-listed commands only (git grep, no pipes, no redirects). Keep the rest: command not skill, interactive session, guide appended to the system prompt, ADR 0004 allow list passed explicitly plus a deny list, no isolation from the user's settings, ADR 0002 not edited.

## Log
- 2026-11-10 17:28 samba: dispatch_plan: plan-todo -> plan-running
- 2026-11-10 17:29 samba: plan_blocked: plan-running -> question: blocked (turns 1, $0.13): The task requires asking the human first whether explore should be a Samba command or only a Claude Code skill or slash command. I have not planned the work until that is answered.
- 2026-11-11 09:04 samba: question.answer: add-the-samba-explore-command/q1 answered
- 2026-11-11 09:04 samba: question.answer: question -> plan-todo
- 2026-11-11 09:04 samba: dispatch_plan: plan-todo -> plan-running
- 2026-11-11 09:05 samba: planned: plan-running -> plan-review: planned (turns 2, $0.56): `samba explore "topic"` becomes a thin launcher that `exec`s an interactive `claude` in the repo. It appends an ADR and exploration guide to the system prompt and passes an explicit allow list and deny list from ADR 0004. Tests go first, using the fake claude and black-box argv checks, followed by the spec, manual and CLAUDE.md updates.
- 2026-11-11 09:39 samba: plan.reject: plan-review -> plan-todo: feedback round 1
- 2026-11-11 09:39 samba: dispatch_plan: plan-todo -> plan-running
- 2026-11-11 09:41 samba: planned: plan-running -> plan-review: planned (turns 3, $1.31): Revised plan against the new layered architecture: explore is a use case in `app/` that builds a pure launch spec and hands it to a new `InteractiveSession` port, with a `subprocess` adapter that inherits the terminal. `cmd_explore` stays thin, composition goes through a new `compose.build_explore`, and the tests have three layers: a use case unit test with a fake port, a black-box argv test with the fake claude, and the architecture test lists.
- 2026-11-11 09:41 samba: plan.accept: plan-review -> work-todo
- 2026-11-11 09:41 samba: dispatch_work: work-todo -> work-running
- Work done as planned. Details the spec left open were settled: the deny list (plan, work, adr accept/reject/supersede, task discard/stop/retry, question answer), `Edit` and `Write` scoped to `docs/adr/**`, no isolation from user settings, SIGINT ignored in Samba while the child runs. Spec changes: `architecture.md` (InteractiveSession row, build_explore), `cli.md` (usage, command list sentence, `explore` section; the ADR 0002 open point is settled there, ADR 0002 untouched), `running-claude.md` (Interactive explore session), `prompts.md` (Explore guide); also `docs/manual.md` and the CLAUDE.md map. No new ADR: the decision is ADR 0002/0004 applied. NOT verified against a real claude: the allow/deny rule syntax (`Edit(docs/adr/**)`, deny over allow) and the real TTY run; the human should do one real `samba explore` in a throwaway repo after merge. Plan step "read ADRs 0011/0012" was only partly done (read ADR 0004 and the architecture code instead).
- 2026-11-11 09:50 samba: done: work-running -> work-review: validation passed (turns 4, $2.07): Added `samba explore [topic]`: a use case builds a pure launch spec (guide, ADR 0004 allow list, deny list) and an `InteractiveSession` port with a `TerminalSession` adapter runs an interactive `claude`. It comes with unit and black-box tests, spec, manual and CLAUDE.md updates. pyright reports 0 errors and all 659 tests pass. I have not run it against a real `claude`: the allow/deny rule syntax (`Edit(docs/adr/**)`, deny over allow) and the real terminal run still need one human check.
- 2026-11-11 09:55 samba: work.accept: work-review -> done: merged 48d1b91, validated
