# Samba

Samba is a small local orchestrator for Claude Code. You write tasks as markdown files in a git
repository; Samba creates a worktree and branch per task, runs Claude Code headless in it, runs
your validation command itself, and hands the task back to you only when validation passes. You
review the plan and the diff, then merge with one command. State lives in plain folders, so you
can also steer with an editor and a file browser.

## Quickstart

You need `git`, Python 3.11+, [`uv`](https://docs.astral.sh/uv/) and the Claude Code CLI
(`claude`, logged in). From a Samba checkout, run `uv run samba ...`; the examples below write
`samba`. Run them from the root of the repository you want to work on.

1. Add a `WORKFLOW.md` at the repo root (config in the front matter, the agent prompt below it):

   ```markdown
   ---
   validate:
     command: uv run pytest -q
   claude:
     allow:
       - Edit
       - Write
       - "Bash(uv run pytest:*)"
       - "Bash(git add:*)"
       - "Bash(git commit:*)"
   ---
   Task: {{ task.title }}

   {{ task.body }}
   ```

2. Create a task, start the loop, and review:

   ```
   $ samba task new "Add a health check endpoint" --body "GET /health returns 200 and a JSON body."
   $ samba run
   $ samba plan accept <id>
   $ samba work accept <id>
   ```

   `samba run` stays in the foreground; use another terminal for the rest. `samba task list`
   shows where each task is.

## Documentation

- [docs/manual.md](docs/manual.md): the user manual (setup, daily loop, troubleshooting).
- [SPEC.md](SPEC.md): the full specification of behavior.
