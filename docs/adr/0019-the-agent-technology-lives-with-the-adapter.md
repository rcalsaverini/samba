---
status: accepted
date: 2026-11-13
supersedes: []
---

# 0019: The agent's technology and each adapter's configuration live with the adapter

Wording clarified on 2026-11-13: the adapter import rule exempts the helper modules `process.py`,
`locations.py`, `adr_format.py` and `claude_settings.py`, which implement no port, and
`workflow_file.py` imports the settings types it builds. The decision is unchanged.

## Context

ADR 0011 says the domain knows no process, and the `principles` chapter (principle 4) says it knows
no agent output format; principle 7 says an adapter decides how, never whether. ADR 0006 chose the
`claude` command line as the agent and says the runner builds the command line. The agent runner
follows that: `build_argv` in `adapters/claude_cli.py` builds `-p`, `--output-format`,
`--allowedTools`, `--permission-mode`, `--model`, `--setting-sources` and the rest from an
`AgentRequest` and the settings. Three places do not follow it.

- `explore_launch` in `domain/launch.py` builds the `claude` command line of `samba explore`:
  `--append-system-prompt`, `--allowedTools`, `--disallowedTools` and `--model`, with the topic as
  the positional prompt. It returns `LaunchSpec(argv, cwd)`, a domain value, and the
  `InteractiveSession` port in `app/ports.py` takes that spec. `StartExplore` in `app/explore.py`
  holds the program (`self.command`) and the model, and `TerminalSession` in
  `adapters/interactive_session.py` only runs the argv. So the port is written in the language of
  one technology, and a second agent, or a different way to start a chat, would change the domain,
  the use case and the port.
- `AgentSettings` in `domain/settings.py` says in its docstring that it is how the `claude` CLI is
  run. Its fields are `command`, `permission_mode`, `args`, `isolate_user_config`,
  `turn_timeout_s`, `stall_timeout_s`, `model`, `allow`, `planning_model` and `planning_allow`.
  Only `ClaudeCliRunner` reads most of them. `StartExplore` reads `command` and `model`. The
  `PromptBuilder` in `app/prompt_builder.py` reads `allow`, `planning_allow` and `permission_mode`
  to render `allowed_tools_note` into the protocol prompt, so the use-case layer imports a type
  named for the CLI.
- `domain/settings.py` as a whole mixes two kinds of data. `Policy` (turns, attempts, retry delays,
  cost cap, concurrency, polling) is the rule set the domain and the use cases act on. `Repository`,
  `Validation` and `Hooks` are the settings of an adapter: the shell, its timeout and the output
  tail of `ShellValidator`, the `after_create` hook of `GitVcs`. The file says it has "no location,
  no file format", which holds, but nothing says whose settings the rest are. The architecture
  test lists `domain/launch.py` and `domain/settings.py` in `DOMAIN_MODULES` and checks only
  imports, so these modules pass.

The `domain/prompts.py` module and the protocol's wording are a separate decision (ADR 0020).

## Decision

- The agent's technology lives with the adapter: no flag, program name or command line is built in
  the domain or in a use case.
- The `InteractiveSession` port takes Samba's terms. A value `ExploreSession` in `app/ports.py`,
  beside the port, holds the topic (or none), the guide text (`EXPLORE_GUIDE`), the allowed and
  denied tools (`EXPLORE_ALLOW`, `EXPLORE_DENY`) and the working location. `TerminalSession` builds
  the `claude` argv from it, in the same way `build_argv` builds the headless one. `LaunchSpec` and
  `explore_launch` are removed, and `domain/launch.py` leaves the domain.
- `StartExplore` no longer takes a program and a model. It takes the guide and the tool lists
  (Samba's own) and the location, and builds the value. The `claude.command` and `claude.model`
  settings reach `TerminalSession` through its constructor, handed over by `bootstrap.py`.
- Settings that only one adapter reads are declared with that adapter, in its module, as a frozen
  dataclass. `ClaudeSettings` (`command`, `model`, `planning_model`, `permission_mode`, `args`,
  `isolate_user_config`, `turn_timeout_s`, `stall_timeout_s`) is read by two adapters,
  `ClaudeCliRunner` and `TerminalSession`, so it is declared in a new module,
  `adapters/claude_settings.py`, which both import. The validator's shell, timeout and tail lines
  go with `ShellValidator`, and the hook with `GitVcs`, each declared in that adapter's module.
  Which field goes where is settled by who reads it: a setting a use case reads (`base_branch`, the
  validation command it tells the agent about) stays a plain value handed to that use case.
- `Policy` stays in the domain. `domain/settings.py` keeps `Policy`, `ConfigError` and whatever the
  use cases read, and loses everything named for a technology.
- `adapters/workflow_file.py` keeps parsing `WORKFLOW.md` and keeps its one key layout (the file
  format of the config does not change). It builds each adapter's settings and the domain's
  `Policy`. `bootstrap.py` receives the loaded parts and hands each adapter its own.
- A new rule, enforced by the architecture test: an adapter imports no other adapter, except the
  module that declares the settings it consumes. `adapters/workflow_file.py`, which builds every
  settings type, may import all of them. Today no test forbids adapter-to-adapter imports, so
  this rule is new and is added with this decision.
- What the `PromptBuilder` needs from the agent settings is what the agent may do, not how the CLI
  is told. It needs the tools the agent may use and whether permissions are bypassed, to say so in
  the protocol prompt. A domain value `ToolAccess` (`allowed`, a tuple of rules, and `unrestricted`)
  carries that, one for work and one for planning. The loader builds both from `claude.allow`,
  `planning.allow` and `claude.permission_mode` (`unrestricted` is true for `bypassPermissions`),
  and `bootstrap.py` hands the same two values to the `PromptBuilder` and to `ClaudeCliRunner`,
  which turns them into `--allowedTools` and `--permission-mode`. `allowed_tools_note` takes a
  `ToolAccess` and no longer a mode string.
- The architecture test gains one check: no domain or use-case module contains, as a string
  token, a flag that `adapters/claude_cli.py` or `adapters/interactive_session.py` emits. The
  list is explicit: `-p`, `--output-format`, `--verbose`, `--resume`, `--session-id`,
  `--add-dir`, `--append-system-prompt`, `--json-schema`, `--permission-mode`, `--allowedTools`,
  `--disallowedTools`, `--model`, `--max-budget-usd`, `--setting-sources`, `--strict-mcp-config`
  and `--settings`. It is not "any `--` option": Samba's own options (`--all`, `--body`, `--yes`,
  `--no-merge` and others) appear in prompts and messages and are fine. The list is kept in step
  with the argv builders by a test that reads their flags. `domain/launch.py` is no longer in
  `DOMAIN_MODULES`.
- Considered and not chosen:
  - Leaving the argv in the domain because `explore_launch` is pure. Purity is not the criterion:
    principle 4 is about whose vocabulary it is, and the command line is the agent's.
  - Building the argv in `StartExplore`. It moves the leak from the domain to the use cases and
    keeps the port generic only in name.
  - Keeping one `AgentSettings` in the domain and renaming it (`AgentConfig`). The name was not the
    problem: the fields (`permission_mode`, `args`, `isolate_user_config`) are the CLI's.
  - Letting each adapter read `WORKFLOW.md` itself. It spreads parsing, validation and the unknown
    key warnings over five places and loses the single config error path.
  - Handing the adapters an untyped map of options. It removes the typed, validated settings that
    pyright checks.
  - Passing `permission_mode` through to the `PromptBuilder` as a string with the CLI's values. It
    keeps `bypassPermissions` in the use-case layer.

## Consequences

- The `explore` path and the headless path follow one rule: the use case speaks Samba's terms and
  the adapter builds the command line. Replacing `claude` with another agent touches adapters and
  the loader only.
- The rule strings themselves (`Bash(git add:*)`, `Edit(docs/adr/**)`) are still the agent's
  permission syntax, in `DEFAULT_ALLOW`, `EXPLORE_ALLOW` and `WORKFLOW.md`. This ADR moves the
  mechanism, not that vocabulary. Making the rules agent-neutral is a larger change with its own
  trade-offs and is not decided here.
- `FakeSession` in the tests records an `ExploreSession` instead of an argv, so component tests of
  `StartExplore` assert on terms instead of flags. The flags are asserted in an integration test of
  `TerminalSession`, as `test_claude_runner.py` does for the headless argv. The end-to-end
  `explore` tests drive the real command against the fake claude and do not change.
- Tests that build `AgentSettings` (`test_app_run_task.py`, `test_scenarios.py`,
  `test_claude_runner.py`) change to the new types. `WORKFLOW.md` and its behavior do not change.
- The spec changes: the `architecture` chapter (the `InteractiveSession` and `AgentRunner` rows, the
  settings paragraph, the architecture test list), `running-claude`, `workflow-config` (which
  adapter reads which key) and `cli` (explore), and the `CLAUDE.md` map.
- One refactor task, after ADR 0020 or independent of it: they touch `prompts.py` and
  `prompt_builder.py` in different places, but both change `bootstrap.py` and the tests that build a
  `PromptBuilder`, so they are best run one after the other.
- Depends on ADR 0018 (the port lives in `app/ports.py`) and applies ADR 0006 and ADR 0011 to the
  parts they did not reach. Supersedes nothing.
