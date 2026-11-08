# Task files

## Identity

- Task id = file name without `.md`.
- The id must match `[A-Za-z0-9._-]+`. Files with other names are skipped with a warning.
- The id is used for the workspace folder, the sidecar file, and the branch `samba/<id>`.

## Format

```markdown
---
priority: 2          # optional, integer, lower runs first; missing sorts last
depends_on: [other-task-id]   # optional, list of task ids that must be `done` first (orchestrator, Dependencies)
---
# Add CSV export to the report page

Free-form description written by the human: goal, context, acceptance criteria.

## Feedback
(Written by the human when sending the task back for rework.)

## Plan
(Maintained by the agent: steps, with checkboxes. After a planning run, written by Samba.)

## Assumptions
(Written by Samba from a planning run: the planner's non-blocking assumptions.)

## Log
(Appended by the agent and by Samba: decisions, progress, validation results.)

## Questions
(Rendered by Samba from the question records (states, Questions). Nobody edits it.)
```

- Title = first `# ` heading, else the id.
- Front matter is optional and human-owned. Unknown keys are ignored. A `depends_on` that is not a
  list of strings is ignored like an unknown key.
- Ownership of sections is a convention stated in the prompt, not enforced by code.
- `## Questions` is the exception: it is a rendered view of the question records in the sidecar
  (states, Questions). Samba regenerates the whole section each time the records change; neither the agent
  nor the human edits it (an edit is overwritten). The agent reports questions in its outcome
  (running-claude, Outcome). Each question renders as `### qN (round R, STATUS)`, its text, `Context: ...` and, once
  answered, `Answer: ...`. Without records the section is not created. Old free-text
  `## Questions` sections are not migrated: such a task has no records, and the human moves it out
  of `question/` by hand.

## Write discipline

- The agent may edit its own task file while it runs.
- Samba writes to a task file **only when no agent process is running for it** (before dispatch
  and after the worker ends), using read-modify-write of the whole file, and only appends lines to
  `## Log` (creating the section if missing).
- Orchestrator bookkeeping goes to the sidecar (states, Sidecar state), not to the markdown.
- A command (cli) may also write a task file, only to append feedback to `## Feedback` of a task in
  a review folder, or to rewrite `## Questions` and append to `## Log` of a task in `question/`
  (`question answer`), where no agent runs. The exception is `task stop` and
  `task discard` on a running task: `fire` moves the file first, so the command writes its `## Log`
  line to the new path (`stuck/` or `discarded/`), which the agent does not hold, and the
  orchestrator's next tick cancels the worker. A read-modify-write race with an agent that has
  already rewritten its file is accepted.
- **Writing a planning result** (no agent runs at that point, running-claude, Planning run): Samba
  replaces the whole `## Plan` section with `## Plan` followed by the `plan` text (creating it if
  missing, before `## Log` if present, else at the end; it is never duplicated). A non-empty
  `assumptions` replaces the `## Assumptions` section the same way. With outcome `blocked` it
  records the questions and renders `## Questions` (states, Questions). It appends a `## Log` line
  including the run `summary`. Headings `#` and `##` inside `plan`, `assumptions` and the question
  text are written as `###`, so they cannot be mistaken for task sections when the `## Plan`
  section is replaced.
- **Repo lock.** `.samba/lock` is an advisory `flock`. Every state-changing command holds it for
  its whole resolve, check, write, `fire` sequence (blocking up to about 10 s, then exit 1). The
  orchestrator takes it non-blocking at the start of each tick and **skips the whole tick** when it
  is held. Without it a tick could see a command's file already renamed but its sidecar `state`
  not yet saved, and apply the move a second time as an observed hand move (or dispatch the task
  before the command saved its effects). A skipped tick only delays the next one. Hand moves with
  `mv` take no lock and are observed as before. Workers fire events only on running tasks, which
  commands never touch; an orchestrator step that fires events on other tasks must take the lock.

