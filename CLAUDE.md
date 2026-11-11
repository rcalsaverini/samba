# Samba

Local orchestrator that runs Claude Code headless on markdown task files, one git worktree per task.

## Map

- `docs/spec/`: the specification, the source of truth for behavior. Start at `docs/spec/README.md`,
  the index: one line per chapter saying when to read it. Chapters are named by topic (`overview`,
  `layout`, `task-files`, `states`, `orchestrator`, `workflow-config`, `workspaces`, `prompts`,
  `running-claude`, `observability`, `cli`, `architecture`, `implementation-notes`, `backlog`) and are referenced by name, not by number. Read the chapters relevant to your task
  before changing code, and update the spec in the same change when behavior changes.
- `README.md`: entry point with a short quickstart; links to the manual and the spec.
- `docs/manual.md`: the user manual (setup, daily loop, troubleshooting), for people using Samba.
  `tests/test_manual.py` fails when a CLI subcommand is not mentioned in it, so update it when
  you add, rename or remove a command.
- `src/samba/`
  - `cli.py`: `run` and `<noun> <verb>` commands, no aliases: `task new|list|show|retry|stop|discard`,
    `plan`/`work` review commands (including `work accept`), `question list|show|answer`
    (answers are recorded per question, `cmd_question_answer`), `adr list|show|accept|reject|supersede`
    (`cmd_adr`, needs no WORKFLOW.md), `dev transitions`.
  - `adr.py`: ADR files under `docs/adr/`: front matter parsing, summary line, status edits.
  - `merge.py`: git steps of `work accept`: preflight, `--no-commit` merge, validate, commit/abort.
  - `views.py`: read-only shared helpers: table printer, state-prefix matcher, task id resolver
    (`resolve_task_id`, reused by every command taking an id), `task show` renderer.
  - `config.py`: loads and validates `WORKFLOW.md` (front matter + prompt body).
  - `domain/`: the pure core, no I/O (`architecture` chapter). `states.py` (`State`, causes),
    `questions.py` (question records and helpers), `task.py` (the `Task` aggregate),
    `task_id.py` (`TaskId`, slug, prefix resolution),
    `transitions.py` (the transition table as plain data, effects, `find_row`, `human_row`,
    `human_events`, the markdown renderer; `samba dev transitions` prints it and the states chapter
    embeds the output), `deps.py` (`depends_on` evaluation over a snapshot,
    `docs/spec/orchestrator.md`, Dependencies).
  - `domain/policy.py`: `Budget`, `RetryPolicy`, `should_reflect` and `decide_after_turn` (one
    action after a turn: fail, finish, run validation, record questions, continue).
  - `app/turn.py`: `TurnFlow`, the turn loop shared by planning and work, over the `AgentRunner`
    port; the orchestrator fires the transition for what it returns.
  - `app/change_state.py`: `ChangeState` (the command pattern of plan/work reject, task
    retry/stop/discard, plan accept) and `check_legal`, the single legality check;
    `app/answer_question.py`: `AnswerQuestion`; `app/accept_work.py`: `AcceptWork` (`work accept`, over the
    `Merger` port); `app/create_task.py`: `CreateTask` (`task new`); `app/resolve.py`:
    `resolve_task_id`, `resolve_deps`, `ResolveError`; `app/confirm.py`: the confirmation policy over the
    `Terminal` port; `app/results.py`: `Refused` and message helpers. Use cases never print: the
    CLI prints their results and maps `kind` to the exit code.
  - `adapters/git_merger.py` (`GitMerger`, the `Merger` port over `merge.py`),
    `adapters/terminal.py` (`StdTerminal`, the `Terminal` port: tty, prompts, `$EDITOR`),
    `adapters/repo_lock.py` (`FileRepoLock`, the `RepoLock` port over `lock.py`).
  - `adapters/markdown_tasks.py`: `MarkdownTasks`, the `Tasks` port over the task folders, the
    sidecar JSON and the `## Log`/`## Questions` sections (stale-save merge, hand-move detection).
  - `orchestrator.py`: poll loop, dispatch, workers, retries, transitions.
  - `app/machine.py`: `Machine.fire` and `observe`, the only path that moves a task
    (`docs/spec/states.md`): loads the `Task`, applies the domain row, saves.
  - `lock.py`: `repo_lock`, the `.samba/lock` flock shared by commands and orchestrator ticks.
  - `adapters/claude_cli.py`: `ClaudeCliRunner`, the only reader of Claude's stream-json: builds
    the argv, runs `claude`, maps the output into an `AgentReport`. `domain/agent.py`:
    `AgentRequest`, `AgentReport`, `Readiness`. `logfmt.py`: the `kv` log line format.
  - `ports.py`: the ports (Protocols `Clock`, `IdGenerator`, `AgentRunner`, `Tasks`); `adapters/system.py`: the system
    clock and uuid generator. The layers and the dependency rule are in the `architecture` chapter.
  - `workspace.py`: git worktrees outside the repo; `proc.py`: subprocess helpers (process groups).
  - `prompts.py`: built-in prompts, the protocol prompt, the outcome schema.
  - `template.py`: strict `{{ name }}` rendering.
- `tests/`
  - `test_blackbox.py`: the main suite. It runs the `samba` CLI as a subprocess and asserts only
    on files and on calls recorded by the fake. **It must never import the `samba` package**:
    the suite is meant to be reused unchanged against a future rewrite in another language.
  - `conftest.py`: the `Sandbox` fixture (temp git repo, WORKFLOW.md, tasks, helpers).
  - `test_manual.py`: drift check for `docs/manual.md`. Runs the CLI's `--help` and reads files,
    never imports `samba`.
  - `test_scenarios.py` and `scenarios/*.json`: the scenario runner and its data (ADR 0012,
    `architecture` chapter, Scenarios). Imports the domain only, never an adapter.
  - `test_architecture.py`: guards the dependency rule. Reads sources with `ast`, never imports
    `samba`; append moved domain modules to its `DOMAIN_MODULES`.
  - `fake_claude.py`: scripted fake of the `claude` CLI. Standard library only.
  - `fake_agent.py`: in-memory fake `AgentRunner` (scripted reports), tested in `test_agent_port.py`.

## Checks

Run these as separate, plain commands (no pipes or `&&`):

- `uv run pyright` (strict mode, must report 0 errors)
- `uv run pytest -q` (about 25 seconds)

## Conventions

- Python 3.11+, fully typed; no `Any` leaking into public signatures, use `cast` at JSON/YAML
  boundaries.
- New behavior gets a black-box test first, in the style of the existing ones.
- Prose in docs and prompts: no em-dashes.
