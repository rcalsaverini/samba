# `WORKFLOW.md`

Markdown with YAML front matter. The body is the first-turn prompt template.

## Config (all optional, defaults shown)

```yaml
---
samba_dir: .samba
workspaces_root: ~/.samba/workspaces   # per-repo subfolder <repo-key> is added (layout)
base_branch: main               # branch new worktrees start from
poll_interval_s: 10
max_concurrent: 2
shell: ["bash", "-c"]           # runs hooks and validate.command (workspaces, Validation)
max_turns: 10                   # Claude invocations per worker run (including validate retries)
max_attempts: 3                 # failed worker runs before giving up
retry_base_s: 10                # first retry delay, doubled per failure
max_retry_backoff_s: 300
max_cost_usd_per_task: null     # cumulative across all runs; null = no cap
reflect_on_give_up: true

hooks:
  after_create: null            # shell script, run once in a new worktree (e.g. "uv sync")
  timeout_s: 300

validate:
  command: null                 # e.g. "make check"; null = outcome done goes straight to work-review
  timeout_s: 900
  output_tail_lines: 200        # lines of output fed back to the agent on failure

claude:
  command: claude
  model: null                   # passed as --model when set
  permission_mode: dontAsk      # dontAsk | acceptEdits | bypassPermissions (workflow-config, Permissions)
  allow:                        # passed as --allowedTools (workflow-config, Permissions)
    - "Edit"
    - "Write"
    - "Bash(git add:*)"
    - "Bash(git commit:*)"
    - "Bash(git status:*)"
    - "Bash(git diff:*)"
    - "Bash(git log:*)"
  args: []                      # extra raw CLI args, appended last
  isolate_user_config: true     # load only the repo's config, not ~/.claude (running-claude, User config isolation)
  turn_timeout_s: 3600
  stall_timeout_s: 300

prompts:                        # override the built-in continuation prompts (prompts)
  continue: null
  validate_failed: null
  resume: null
  give_up: null
  plan: null                    # planning prompts (planning, Prompts)
  plan_revise: null

planning:                       # optional planning phase (planning, Config)
  require_plan: false
  model: null
  allow: ["Read", "Grep", "Glob"]
---
```

Validation on startup: YAML must be a map; integers positive; `claude.command` non-empty;
`base_branch` exists; `workspaces_root` is outside the repo. Unknown keys are ignored with a
warning.

## Permissions

Headless runs cannot answer permission prompts. With `permission_mode: dontAsk`, any tool call not
allowed is denied; the run continues, the agent is told it was denied, and the denial is listed in
the `result` event's `permission_denials` (verified, implementation-notes, Verified Claude Code behavior). Samba appends each denial to the
task's `## Log` so the human can widen `allow` or treat it as a harness gap.

**The allow list lives in `WORKFLOW.md`, not in the repo's `.claude/settings.json`.** Claude Code
ignores `permissions.allow` from a project's settings when the folder has not been trusted
interactively, and every new worktree path is untrusted. Allow rules passed on the command line
(`--allowedTools`, `--settings`) are honored (verified). Samba therefore passes `claude.allow` as
`--allowedTools`. The repo's `.claude/settings.json` still applies for everything else Claude Code
loads from it, minus the ignored allow rules.

Typical setups:

- Default: `dontAsk` plus `claude.allow` listing edits, git commit, and the project's test/lint
  commands (`Bash(make:*)`, `Bash(uv run pytest:*)`).
- High trust, for throwaway repos: `permission_mode: bypassPermissions`.

