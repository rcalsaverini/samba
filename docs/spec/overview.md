# Samba: Specification

Status: Draft v0. Derived from OpenAI's Symphony spec (Draft v1), trimmed for local, single-user
experimentation, and informed by OpenAI's "harness engineering" write-up.

## What this is

A small, long-running local process that:

1. Watches a folder of task files (markdown) inside a target git repository.
2. For each task ready to run, creates an isolated `git worktree` and runs Claude Code headless in it.
3. Keeps the agent going across turns until it says it is done, then **runs a validation command
   itself** and only hands the task to the human when validation passes.
4. Moves the task file between state folders so the human can see and steer everything with a file
   browser and an editor.

Principles carried over from the original spec:

- The task store is the source of truth. Restart recovery comes from the task folders, the worktrees
  and a few small JSON sidecar files. No database.
- One isolated workspace per task, preserved across runs.
- Reconcile before dispatch: if the human moves a task out of its running folder
  (`plan-running/` or `work-running/`), its agent is stopped.
- Policy lives in the repo (`WORKFLOW.md`), versioned with the code.

Principles taken from harness engineering:

- **Mechanical validation over the agent's word.** The orchestrator, not the agent, decides whether
  work passes.
- **Durable plans in files.** The agent keeps its plan and decision log in the task file. That file,
  not the chat session, is the memory that survives restarts and compaction.
- **A map, not a manual.** `WORKFLOW.md` and the repo's `CLAUDE.md` stay short and point to docs.
- **Failures reveal missing capabilities.** When a task gives up, the agent writes down what was
  missing (tool, doc, fixture), so the human fixes the harness rather than retrying harder.

### Non-goals (v0)

Ideas not built yet are in backlog.

- Remote trackers (Jira, Linear, GitHub Issues). The task store sits behind a small interface (states, The Tasks port)
  so one can be added later.
- Multi-user use, web UI, HTTP API, remote/SSH workers.
- Live reload of `WORKFLOW.md`. Restart to apply changes.
- Sandboxing beyond what Claude Code's permission settings and git worktrees provide. This is meant
  for trusted, local repositories. A worktree is isolation for git state, not a security boundary.
- Merging. The agent never merges; tasks stop at `work-review/` with a branch for the human.

