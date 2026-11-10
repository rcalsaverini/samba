# Samba

Samba is a small local orchestrator that runs [Claude Code](https://claude.com/claude-code)
headless on markdown task files. Each task gets its own git worktree and branch. You steer
everything by moving files between folders and running a few commands.

It is built for trusted, local repositories and a single user. There is no database, web UI or
remote tracker: the task folders are the source of truth.

## How it works

1. You write a task as a markdown file under `.samba/tasks/` in your repository.
2. Samba creates a worktree (`samba/<id>` branch) and runs Claude Code in it, turn after turn,
   until the agent says it is done.
3. Samba runs your validation command itself. The agent's word is not enough.
4. When validation passes, the task goes to review. You accept (merge) or reject it with feedback.

The folder a task sits in is its state: `plan-todo`, `plan-running`, `plan-review`, `work-todo`,
`work-running`, `work-review`, `question`, `stuck`, `done`, `discarded`. The agent keeps its plan
and log inside the task file, so progress survives restarts.

## Install

Requires Python 3.11+, git and the `claude` CLI.

```
uv sync
uv run samba --help
```

## Quick start

Run these from the root of the target git repository.

1. Add a `WORKFLOW.md` with the config (YAML front matter) and the prompt for the agent
   (body, with `{{ task.title }}` and `{{ task.body }}`). The one in this repo is a working example:

   ```markdown
   ---
   max_turns: 15
   validate:
     command: uv run pytest -q
   claude:
     model: sonnet
     allow:                        # replaces the default list, so keep edits and commits
       - Edit
       - Write
       - "Bash(uv run pytest:*)"   # lets the agent check its own work before handing it in
       - "Bash(git add:*)"
       - "Bash(git commit:*)"
   ---
   Task: {{ task.title }}

   {{ task.body }}
   ```

2. Create a task and start the orchestrator:

   ```
   samba task new "Add CSV export" --body "Export the report page as CSV."
   samba run
   ```

3. Follow along and review. New tasks are planned first: the plan waits in `plan-review` until
   you accept it (`samba task new --skip-plan` goes straight to work).

   ```
   samba task list
   samba task show <id>
   samba plan accept <id>      # once the task is in plan-review: the agent starts the work
   samba work accept <id>      # once the task is in work-review: merge the branch
   ```

## Commands

| Command | Purpose |
| --- | --- |
| `samba run` | run the orchestrator loop (`--exit-when-idle` to stop when nothing is left) |
| `samba task new\|list\|show\|retry\|stop\|discard` | create and manage tasks |
| `samba plan accept\|reject` | review a plan |
| `samba work accept\|reject` | review finished work; `accept` merges the branch |
| `samba question list\|show\|answer` | answer questions the agent asked |
| `samba adr list\|show\|accept\|reject\|supersede` | read and decide on the ADRs in `docs/adr/` |

Task ids can be abbreviated to any unique prefix.

## Docs

- [`docs/manual.md`](docs/manual.md): the user manual (setup, daily loop, questions, troubleshooting).
- [`docs/spec/`](docs/spec/README.md): the full specification and source of truth for behavior, one chapter per topic.
- [`CLAUDE.md`](CLAUDE.md): a map of the code, for agents and contributors.

## Development

```
uv run pyright
uv run pytest -q
```
