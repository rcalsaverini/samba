# Layout

Samba is run from the root of a target git repository:

```
<repo>/
  WORKFLOW.md                    # config (front matter) + first-turn prompt (body)
  CLAUDE.md                      # optional, the repo's own agent map; Claude Code loads it
  .samba/                     # created by Samba, added to .git/info/exclude
    tasks/
      plan-todo/     <id>.md         # planning stage (planning): ready to be planned
      plan-running/  <id>.md
      plan-review/   <id>.md
      work-todo/     <id>.md         # work stage: ready to run
      work-running/  <id>.md
      work-review/   <id>.md
      question/      <id>.md         # needs an answer from the human
      stuck/         <id>.md         # needs a decision from the human
      done/          <id>.md         # accepted (merged)
      discarded/     <id>.md         # abandoned
    state/         <id>.json     # orchestrator-owned sidecar per task
    runs/          <id>/<n>.jsonl # raw Claude Code event stream per turn
    samba.log

~/.samba/workspaces/<repo-key>/
  <id>/                          # git worktree per task, branch samba/<id>
```

On startup Samba creates any missing folders and appends `.samba/` to `.git/info/exclude`
(never edits the repo's `.gitignore`). The folder name is the complete state of a task (states, States).
Earlier versions used the folders `plan`, `todo`, `running`, `review` and `blocked`; startup refuses
to run while any of them still holds task files (orchestrator, Startup).

Worktrees live **outside** the repository on purpose. Claude Code loads `CLAUDE.md` files from its
working directory and every parent directory, so a worktree nested inside the main checkout would
also pick up the main checkout's `CLAUDE.md` (possibly a different version than the branch's).
`<repo-key>` is `<repo folder name>-<first 8 hex chars of sha256(absolute repo path)>`, so two repos
with the same folder name do not collide.

All paths are configurable (workflow-config); these are the defaults.

