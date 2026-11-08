# Later (explicitly out of v0)

- Reviewer pass: a second Claude run with a review prompt before moving to `work-review/`.
- Gardening: scheduled tasks that drop cleanup tickets into `work-todo/` (stale docs, drift, tech debt).
- Other task stores behind states, Task store interface (GitHub Issues, Jira, Linear).
- PR creation on `work-review` and feeding PR comments or CI results back as `## Feedback`.
- Claude Agent SDK runner, if in-process permission callbacks become useful.
- Live reload of `WORKFLOW.md`.
- Automatic subtask creation from a plan, with dependency tracking ("blocked by").
- Plans committed into the repo (for example `docs/exec-plans/`) instead of only the task file.

