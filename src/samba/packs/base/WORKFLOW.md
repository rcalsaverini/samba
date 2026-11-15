---
max_turns: 15
claude:
  model: sonnet
  # No allow list: Samba's defaults apply (edits and git commits). To let agents read the ADRs,
  # add "Bash(samba adr list:*)" and "Bash(samba adr show:*)" under allow.
@@VALIDATE@@
---
Task: {{ task.title }}

{{ task.body }}

Start by reading CLAUDE.md and docs/spec/README.md, and the chapters of the spec that the task
touches. Write the tests for the new behavior first, then the implementation. Keep existing tests
passing.

Updating the spec is a step of every task: change the chapters of docs/spec/ that your change
makes wrong, in the same change, and log what you changed in the `## Log` of your task file.

If the task made a real decision (a choice between alternatives with a lasting reason), propose
an ADR in docs/adr/ with status proposed, one decision per file, in the format of
docs/adr/0000-record-architecture-decisions.md.

Before designing, run `samba adr list` and read the relevant ADRs with `samba adr show N`.
