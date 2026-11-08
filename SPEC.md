# Symphony (local edition): Specification v0

Status: Draft v0. Derived from OpenAI's Symphony spec (Draft v1), trimmed for local, single-user
experimentation, and informed by OpenAI's "harness engineering" write-up.

## 1. What this is

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
- Reconcile before dispatch: if the human moves a task out of `running/`, its agent is stopped.
- Policy lives in the repo (`WORKFLOW.md`), versioned with the code.

Principles taken from harness engineering:

- **Mechanical validation over the agent's word.** The orchestrator, not the agent, decides whether
  work passes.
- **Durable plans in files.** The agent keeps its plan and decision log in the task file. That file,
  not the chat session, is the memory that survives restarts and compaction.
- **A map, not a manual.** `WORKFLOW.md` and the repo's `CLAUDE.md` stay short and point to docs.
- **Failures reveal missing capabilities.** When a task gives up, the agent writes down what was
  missing (tool, doc, fixture), so the human fixes the harness rather than retrying harder.

### 1.1 Non-goals (v0)

- Remote trackers (Jira, Linear, GitHub Issues). The task store sits behind a small interface (§4.4)
  so one can be added later.
- Multi-user use, web UI, HTTP API, remote/SSH workers.
- Live reload of `WORKFLOW.md`. Restart to apply changes.
- Sandboxing beyond what Claude Code's permission settings and git worktrees provide. This is meant
  for trusted, local repositories. A worktree is isolation for git state, not a security boundary.
- Merging. The agent never merges; tasks stop at `review/` with a branch for the human.

## 2. Layout

Symphony is run from the root of a target git repository:

```
<repo>/
  WORKFLOW.md                    # config (front matter) + first-turn prompt (body)
  CLAUDE.md                      # optional, the repo's own agent map; Claude Code loads it
  .symphony/                     # created by Symphony, added to .git/info/exclude
    tasks/
      plan/        <id>.md           # optional planning phase (§14)
      plan-review/ <id>.md
      todo/        <id>.md
      running/     <id>.md
      review/      <id>.md
      blocked/     <id>.md
      done/        <id>.md
    state/         <id>.json     # orchestrator-owned sidecar per task
    runs/          <id>/<n>.jsonl # raw Claude Code event stream per turn
    symphony.log

~/.symphony/workspaces/<repo-key>/
  <id>/                          # git worktree per task, branch symphony/<id>
```

On startup Symphony creates any missing folders and appends `.symphony/` to `.git/info/exclude`
(never edits the repo's `.gitignore`).

Worktrees live **outside** the repository on purpose. Claude Code loads `CLAUDE.md` files from its
working directory and every parent directory, so a worktree nested inside the main checkout would
also pick up the main checkout's `CLAUDE.md` (possibly a different version than the branch's).
`<repo-key>` is `<repo folder name>-<first 8 hex chars of sha256(absolute repo path)>`, so two repos
with the same folder name do not collide.

All paths are configurable (§6); these are the defaults.

## 3. Task files

### 3.1 Identity

- Task id = file name without `.md`.
- The id must match `[A-Za-z0-9._-]+`. Files with other names are skipped with a warning.
- The id is used for the workspace folder, the sidecar file, and the branch `symphony/<id>`.

### 3.2 Format

```markdown
---
priority: 2          # optional, integer, lower runs first; missing sorts last
---
# Add CSV export to the report page

Free-form description written by the human: goal, context, acceptance criteria.

## Feedback
(Written by the human when sending the task back for rework.)

## Plan
(Maintained by the agent: steps, with checkboxes.)

## Log
(Appended by the agent and by Symphony: decisions, progress, validation results.)

## Questions
(Written by the agent when it is blocked and needs the human.)
```

- Title = first `# ` heading, else the id.
- Front matter is optional and human-owned. Unknown keys are ignored.
- Ownership of sections is a convention stated in the prompt, not enforced by code.

### 3.3 Write discipline

- The agent may edit its own task file while it runs.
- Symphony writes to a task file **only when no agent process is running for it** (before dispatch
  and after the worker ends), using read-modify-write of the whole file, and only appends lines to
  `## Log` (creating the section if missing).
- Orchestrator bookkeeping goes to the sidecar (§4.2), not to the markdown.

## 4. Domain model

### 4.1 States

States are folders. Moving a file is a state transition.

| Folder     | Meaning                                         | Who moves files in       |
|------------|-------------------------------------------------|--------------------------|
| `plan`        | Ready to be planned (new, or plan revision, §14) | Human, or Symphony (retry) |
| `plan-review` | Plan written; waiting for the human (§14)      | Symphony                 |
| `todo`     | Ready to run (new, retry, or rework)            | Human, or Symphony (retry) |
| `running`  | Claimed; an agent is (or is about to be) running | Symphony only           |
| `review`   | Validation passed; branch ready for the human   | Symphony                 |
| `blocked`  | Needs the human: question, budget, gave up      | Symphony                 |
| `done`     | Terminal; human accepted or abandoned it         | Human                    |

Transitions:

```
todo ──dispatch──> running ──DONE + validate ok──> review ──human──> done
                     │  ├──BLOCKED / budget / gave up──> blocked ──human answers──> todo
                     │  └──failure, attempts left──> todo (with retry delay)
                     └──human moves it elsewhere──> agent stopped
review / blocked ──human adds Feedback──> todo   (resumes the same session)
plan ──> running (phase plan) ──> plan-review ──human approves──> todo   (planning flow: §14.2)
```

A task file deleted by the human is treated like `done`.

### 4.2 Sidecar state (`state/<id>.json`)

Owned by Symphony. Fields:

- `session_id` (string or null): Claude Code session UUID, generated by Symphony and written here
  before launch (§9.1), used for `--resume`.
- `attempts` (int): failed attempts so far (reset to 0 when the task reaches `review`).
- `not_before` (ISO timestamp or null): retry delay; the task is not dispatched before this.
- `last_error` (string or null)
- `last_outcome` (`done` | `blocked` | `failed` | `validate_failed` | `retrying` | `planned` |
  `approved` | null)
- `phase`, `plan_session_id`, `plan_approved` (planning, §14.8)
- `turns_total` (int)
- `cost_usd_total` (float), `input_tokens_total`, `output_tokens_total` (ints)
- `branch` (string), `workspace` (absolute path)
- `updated_at` (ISO timestamp)

If the sidecar is missing or unreadable it is recreated empty (attempts 0, no session).

### 4.3 In-memory orchestrator state

- `running`: map `id -> {process handle, started_at, last_event_at, turn}`
- Everything else is derived from folders and sidecars on each tick.

### 4.4 Task store interface

The rest of the system only uses these operations, so another tracker can replace the folder store
later:

- `list(state) -> [Task]`
- `read(id) -> Task` (state, title, body, front matter)
- `move(id, to_state)`
- `append_log(id, line)`

## 5. Orchestrator loop

### 5.1 Startup

1. Load and validate `WORKFLOW.md` (§6). Fail fast on errors.
2. Check `git` and the Claude command are on `PATH`, and the cwd is a git repo root.
3. Create folders, update `.git/info/exclude`.
4. **Recover:** every file in `running/` has no live agent (we just started). Move each back to
   `todo/` without incrementing `attempts`; its session will be resumed.
5. Start ticking every `poll_interval_s`.

### 5.2 Tick

1. **Reconcile** each live agent:
   - Task file no longer in `running/` (human moved or deleted it): kill the agent process. If the
     new state is `done` or the file is gone, remove the worktree (keep the branch).
   - (Stalls are detected by the Claude runner itself while reading the stream, §9.2.)
2. **Clean up** worktrees whose task is in `done/` or no longer exists: remove the worktree (keep
   the branch).
3. **Dispatch:** list `todo/`, drop tasks with `not_before` in the future, sort by `priority`
   (missing last), then file mtime (oldest first), then id. While
   `len(running) < max_concurrent`: move the task to `running/` and start a worker.

### 5.3 Worker (one per running task)

```
ensure_workspace(task)              # §7
for turn in 1..max_turns:
    prompt = first_prompt or continuation prompt (§8)
    result = run_claude(prompt)     # §9, resumes session if one exists
    record usage/cost in sidecar; log any permission_denials
    if budget exceeded: -> blocked ("budget exceeded")
    match structured outcome in result (§9.3):
      done:
        v = run_validate()          # §7.3
        if v.ok: -> review
        else: next prompt = validate_failed(v.output_tail); continue
      blocked: -> blocked
      continue / missing: next prompt = continue; continue
max_turns reached -> failure ("max_turns exhausted")
```

Every exit path appends one line to the task's `## Log`, for example:
`- 2026-11-06 21:40 symphony: validate passed after 4 turns ($0.83), moved to review`.

### 5.4 Failures and retries

A failure is: Claude process exits non-zero, emits no `result` event, or emits one with
`is_error: true` (§9.2), turn timeout, stall,
workspace hook failure, prompt render error, or `max_turns` exhausted.

On failure:

1. `attempts += 1`, store `last_error`.
2. If `attempts < max_attempts`: set
   `not_before = now + min(retry_base_s * 2^(attempts-1), max_retry_backoff_s)`, set
   `last_outcome = "retrying"`, move to `todo/`.
3. Else (**give up**): if `reflect_on_give_up` is true and a session exists, run one final short turn
   with the `give_up` prompt (§8), ignoring its outcome. Then move to `blocked/` with
   `last_error`.

Moving a task from `blocked/` to `todo/` by hand resets `attempts` to 0 (Symphony detects this at
dispatch because `last_outcome` is `blocked` or `failed`, not `retrying`).

## 6. `WORKFLOW.md`

Markdown with YAML front matter. The body is the first-turn prompt template.

### 6.1 Config (all optional, defaults shown)

```yaml
---
symphony_dir: .symphony
workspaces_root: ~/.symphony/workspaces   # per-repo subfolder <repo-key> is added (§2)
base_branch: main               # branch new worktrees start from
poll_interval_s: 10
max_concurrent: 2
shell: ["bash", "-c"]           # runs hooks and validate.command (§7.3)
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
  command: null                 # e.g. "make check"; null = outcome done goes straight to review
  timeout_s: 900
  output_tail_lines: 200        # lines of output fed back to the agent on failure

claude:
  command: claude
  model: null                   # passed as --model when set
  permission_mode: dontAsk      # dontAsk | acceptEdits | bypassPermissions (§6.2)
  allow:                        # passed as --allowedTools (§6.2)
    - "Edit"
    - "Write"
    - "Bash(git add:*)"
    - "Bash(git commit:*)"
    - "Bash(git status:*)"
    - "Bash(git diff:*)"
    - "Bash(git log:*)"
  args: []                      # extra raw CLI args, appended last
  isolate_user_config: true     # load only the repo's config, not ~/.claude (§9.4)
  turn_timeout_s: 3600
  stall_timeout_s: 300

prompts:                        # override the built-in continuation prompts (§8)
  continue: null
  validate_failed: null
  resume: null
  give_up: null
  plan: null                    # planning prompts (§14.5)
  plan_revise: null

planning:                       # optional planning phase (§14.7)
  require_plan: false
  model: null
  allow: ["Read", "Grep", "Glob"]
---
```

Validation on startup: YAML must be a map; integers positive; `claude.command` non-empty;
`base_branch` exists; `workspaces_root` is outside the repo. Unknown keys are ignored with a
warning.

### 6.2 Permissions

Headless runs cannot answer permission prompts. With `permission_mode: dontAsk`, any tool call not
allowed is denied; the run continues, the agent is told it was denied, and the denial is listed in
the `result` event's `permission_denials` (verified, §12.1). Symphony appends each denial to the
task's `## Log` so the human can widen `allow` or treat it as a harness gap.

**The allow list lives in `WORKFLOW.md`, not in the repo's `.claude/settings.json`.** Claude Code
ignores `permissions.allow` from a project's settings when the folder has not been trusted
interactively, and every new worktree path is untrusted. Allow rules passed on the command line
(`--allowedTools`, `--settings`) are honored (verified). Symphony therefore passes `claude.allow` as
`--allowedTools`. The repo's `.claude/settings.json` still applies for everything else Claude Code
loads from it, minus the ignored allow rules.

Typical setups:

- Default: `dontAsk` plus `claude.allow` listing edits, git commit, and the project's test/lint
  commands (`Bash(make:*)`, `Bash(uv run pytest:*)`).
- High trust, for throwaway repos: `permission_mode: bypassPermissions`.

## 7. Workspaces

### 7.1 Creation

If `workspaces/<id>` does not exist:

1. If branch `symphony/<id>` exists (task reworked after its worktree was removed):
   `git worktree add <path> symphony/<id>`.
2. Else: `git worktree add -b symphony/<id> <path> <base_branch>`.
3. Run `hooks.after_create` with cwd = worktree. Failure or timeout: remove the worktree, fail the
   attempt.

If it exists, reuse it as is (no reset).

### 7.2 Safety invariants

- The workspace path, resolved to absolute, must be inside `<workspaces_root>/<repo-key>/`.
- `<workspaces_root>` must not be inside the repository (checked at startup, see §2 for why).
- Claude and all hooks run with cwd = workspace path.
- The id regex (§3.1) prevents path tricks in names.

### 7.3 Validation

`validate.command` (and hooks) run via `shell` (default `bash -c`, a non-login shell that inherits
Symphony's environment) with cwd = workspace, after the agent reports done.

The agent's Bash tool runs with the user's interactive shell environment, which can resolve tools
differently (found in the smoke test: the agent's `python3` had pytest, while a `bash -lc` login
shell found a different `python3` without it, plus a profile script error). So validation commands
should pin their tools rather than rely on `PATH` (`uv run pytest`, `make check`, `./scripts/check`),
and the agent should be allowed to run the exact same command. Exit code
0 = pass. Output (stdout+stderr combined) is saved to `runs/<id>/validate-<n>.log`; the last
`output_tail_lines` lines are fed back on failure. A timeout counts as a validation failure, not a
worker failure.

### 7.4 Removal

`git worktree remove --force <path>` when the task reaches `done/` or is deleted. The branch is kept.
Symphony never deletes branches.

## 8. Prompts

### 8.1 Template rendering

`{{ name }}` substitution only. Unknown variables are an error (fails the attempt). Variables:

- `task.id`, `task.title`, `task.body` (file content without front matter), `task.path` (absolute
  path of the task file, in `running/`)
- `workspace`, `branch`, `base_branch`
- `attempt` (0 on first run, otherwise number of previous failures)
- `validate_command` (empty string if none)

### 8.2 Which prompt is sent

| Situation                                        | Prompt                                   | Session          |
|--------------------------------------------------|------------------------------------------|------------------|
| First run, no session                            | `WORKFLOW.md` body                       | new              |
| Later turn in same worker run                    | `continue`                               | resume           |
| Agent said DONE, validation failed               | `validate_failed` (+ output tail)        | resume           |
| New worker run, session exists (retry, rework, answered question) | `resume`                | resume           |
| Resume fails (session not found)                 | `WORKFLOW.md` body                       | new              |
| Giving up                                        | `give_up`                                | resume           |
| Planning run, no plan session (§14.4)            | `plan`                                   | new (plan session) |
| Planning run, plan session exists (revision)     | `plan_revise`                            | resume (plan session) |

### 8.3 Built-in defaults

- `continue`: "Continue working on the task. Re-read your task file at {{ task.path }} if needed and
  keep `## Plan` and `## Log` up to date."
- `validate_failed`: "You reported done, but `{{ validate_command }}` failed. Last lines of output
  are below. Fix the problem, then report done again.\n\n{output}"
- `resume`: "You are resuming work on this task. Re-read your task file at {{ task.path }}, especially
  `## Feedback`, `## Questions` and anything the human added, then continue."
- `give_up`: "This task is being stopped after repeated failures. Do not try to fix it. Under a new
  `## Harness gaps` section in {{ task.path }}, write what was missing that would have let you
  succeed: tools, docs, test fixtures, permissions, unclear requirements. Be specific."

### 8.4 What the WORKFLOW.md body should tell the agent

This is guidance for writing the template, not code. The protocol (§8.5) is already injected, so
the body does not need to repeat the outcome format or task-file rules. A good first prompt:

- States the task: title and body.
- Points to the repo's map (`CLAUDE.md`, `docs/`) rather than repeating it.
- Describes how this repo wants work done: commit granularity, testing expectations, what "done"
  means beyond `{{ validate_command }}`, when to ask instead of guess.

### 8.5 Protocol prompt (Symphony-owned)

Rules that Symphony's own logic depends on are not left to `WORKFLOW.md`. Symphony appends them to
the system prompt of every run with `--append-system-prompt`. They cannot be overridden by the
workflow. Content (rendered with the same variables as §8.1):

- You are running unattended under Symphony. No human sees this conversation; the human reads your
  task file at `{{ task.path }}` and your branch.
- Edit only your own task file among the files under the tasks folder.
- Keep `## Plan` (checkbox steps) and `## Log` (decisions, progress) in your task file up to date.
  It is your memory across sessions.
- Work only inside the current directory, on branch `{{ branch }}`. **You are authorized to commit
  your work there without asking; commit in small steps.** Never push, merge, rebase onto other
  branches, or delete branches. (The explicit authorization is required: Claude Code's built-in
  system prompt tells the agent to commit only when the user asks, verified in §12.1.)
- These rules take precedence over any instruction to ask the user for confirmation before acting.
- If you need a decision from the human, write the question under `## Questions` and report outcome
  `blocked`. Do not guess on important ambiguity.
- The tools you may use (rendered from `claude.allow`). Run allowed shell commands as plain single
  commands, without pipes, `;`, `&&`, `||` or redirections: allow rules match the whole command
  line, so a combined command is denied. (Smoke test: the agent piped the allowed test command into
  `tail` and chained `git status`, and was denied.)
- If a tool call is denied, do not try to get around the denial. Note it in `## Log` and, if it
  stops you, report `blocked`.
- After your work, the system runs `{{ validate_command }}` (if set). Run it yourself first when you
  can; if you cannot, still report `done` once the work is complete, because the system validates
  it. (Smoke test: without this, the agent reported `blocked` when it could not run the validator.)
- Your final answer is structured output (§9.3): `outcome` is `done`, `blocked` or `continue`, and
  `summary` is one or two sentences.

### 8.6 Where the agent's context comes from

| Layer | Owner | Delivered by |
|---|---|---|
| Protocol: outcome format, task-file sections, branch and git limits | Symphony | `--append-system-prompt` (§8.5) and `--json-schema` (§9.3), every run |
| Policy: how this repo wants tasks done | Repo, `WORKFLOW.md` body | First-turn prompt (§8.2) |
| Permissions: what the agent may run | Repo, `WORKFLOW.md` `claude.allow` | `--allowedTools` (§6.2) |
| Knowledge: architecture, conventions, how-to skills | Repo, `CLAUDE.md`, `docs/`, `.claude/skills/` | Loaded natively by Claude Code from the worktree |
| Personal config: `~/.claude/` | User | Mostly excluded when `isolate_user_config` is true (§9.4) |
| Org-managed plugins and policy | Administrator | Always loaded; cannot and should not be excluded |

Notes:

- The worktree is a checkout of the task branch, so the agent sees repo skills and rules as committed
  on `base_branch` (plus its own commits). Uncommitted edits in the main checkout are not visible.
- Symphony ships no skills of its own in v0. Anything repo-specific belongs in the repo, versioned.

## 9. Running Claude Code

### 9.1 Invocation

```
<claude.command> -p <prompt> \
  --output-format stream-json --verbose \
  (--session-id <new uuid> | --resume <session_id>) \
  --add-dir <abs tasks dir> \
  --append-system-prompt <rendered protocol prompt (§8.5)> \
  --json-schema <outcome schema (§9.3)> \
  --permission-mode <claude.permission_mode> \
  --allowedTools <claude.allow...> \
  [--model <claude.model>] \
  [--max-budget-usd <remaining task budget>] \
  [--setting-sources project,local --strict-mcp-config]   # when isolate_user_config (§9.4)
  <claude.args...>
```

- cwd = workspace. stdin = `/dev/null` (otherwise Claude waits 3 s for piped stdin and warns).
- `--verbose` is mandatory with `-p` and `stream-json` (the CLI errors without it).
- **Session ids are chosen by Symphony.** For a new session, Symphony generates a UUID, writes it to
  the sidecar, then passes `--session-id`. Later runs pass `--resume <id>`. A UUID is never reused
  with `--session-id` (the CLI rejects an id already in use). Resume works from any cwd.
- If `--resume` fails because the session is gone (`result.subtype == "error_during_execution"`,
  stderr "No conversation found with session ID"), Symphony starts a new session with the first
  prompt (§8.2). This does not count as a failed attempt.
- `--add-dir` gives the agent read and write access to the tasks folder. Without it, reading the task
  file is denied.
- `--max-budget-usd` is set to `max_cost_usd_per_task - cost_usd_total` when a task cap is set.
- The prompt is passed as an argument.

### 9.2 Reading the stream

- stdout: one JSON object per line. Each line updates `last_event_at` and is appended verbatim to
  `runs/<id>/<n>.jsonl`. Lines that are not JSON are logged and skipped.
- Event order: optional `system` hook events, then `system`/`init`, then `assistant`/`user` messages,
  then one `result`. Do not assume `init` is the first line.
- `init` lists what was loaded (`skills`, `plugins`, `mcp_servers`, `tools`, `permissionMode`).
  Symphony logs these on the first run of each `symphony run`, so leaks are visible.
- `result` fields used: `is_error`, `subtype`, `result` (text), `structured_output`,
  `total_cost_usd` (for this invocation only, not cumulative over a resumed session),
  `usage.input_tokens`, `usage.output_tokens`, `num_turns`, `terminal_reason`,
  `permission_denials`.
- **Success = exit code 0 and `is_error == false`.** `subtype` is not reliable: an expired login
  produced `subtype: "success"` with `is_error: true` and exit code 1.
- stderr: appended to `symphony.log` as diagnostics, never parsed except for the resume case above.
- Turn timeout (`claude.turn_timeout_s` since launch) and stall (no stdout line for
  `claude.stall_timeout_s`) kill the process group and count as a failure (§5.4).

### 9.3 Outcome (structured output)

Every run passes `--json-schema` with:

```json
{"type": "object",
 "properties": {"outcome": {"type": "string", "enum": ["done", "blocked", "continue"]},
                "summary": {"type": "string"}},
 "required": ["outcome", "summary"]}
```

Claude Code returns the parsed object in `result.structured_output` (verified). Symphony reads
`outcome` from there:

- `done`: work complete, ready for validation.
- `blocked`: needs the human; questions are in the task file.
- `continue`: more work left.

If `structured_output` is missing or invalid, treat as `continue` and log a warning. `summary` is
written into the task's `## Log` line for that run.

### 9.4 User config isolation

Headless Claude Code normally loads the user's own config as well as the repo's. On the test machine
a default run loaded the user `CLAUDE.md`, 50 skills, 12 plugins, user hooks, and 37 MCP servers
including claude.ai connectors (Gmail, Drive, Calendar and more). Besides conflicting rules, that
gives an unattended agent access to the user's accounts.

When `claude.isolate_user_config` is true, Symphony adds
`--setting-sources project,local --strict-mcp-config`. Verified effect (Claude Code 2.1.220):

| Source | Default | Isolated |
|---|---|---|
| User `~/.claude/CLAUDE.md` | loaded | **not loaded** |
| Repo `CLAUDE.md` | loaded | loaded |
| User skills and user-installed plugins | loaded | **not loaded** |
| Repo `.claude/skills/` | loaded | loaded |
| MCP servers (user config and claude.ai connectors) | loaded | **none** |
| Built-in skills (`code-review`, `simplify`, ...) | loaded | loaded (harmless) |
| Org-managed plugins (policy) | loaded | loaded (by design) |

Rejected alternatives:

- `--bare`: skips repo `CLAUDE.md` discovery and requires `ANTHROPIC_API_KEY` (no subscription
  login).
- `--safe-mode`: disables the repo's `CLAUDE.md` and skills too.
- `--disable-slash-commands`: removes all skills, including the repo's.
- `CLAUDE_CONFIG_DIR` pointing at an empty folder: logged out, would need a separate login.

If a repo needs MCP servers, a later version can pass them explicitly with `--mcp-config`.

## 10. Observability

- `symphony.log`: one line per event, `key=value` style, always with `task=<id>`. Logs dispatch,
  turn start/end, outcome, validation result, state moves, failures, cost.
- `runs/`: raw event streams and validation outputs for debugging.
- Task `## Log`: the human-readable summary, one line per worker exit.
- `symphony status`: prints a table from folders and sidecars: id, state, attempts, turns, cost,
  last outcome, last error, and for running tasks the phase (shown as `running (plan)` or
  `running (execute)`).

## 11. CLI

```
symphony run      [--repo PATH] [--exit-when-idle]
                  # start the loop (foreground; Ctrl-C stops agents and exits).
                  # --exit-when-idle: exit once nothing is running and todo/ is empty.
symphony status   [--repo PATH]
symphony new "Title" [--priority N] [--plan]  # create todo/<slug>.md (plan/<slug>.md with --plan)
```

On Ctrl-C: kill all agent processes, move their tasks back to `todo/` (no attempt increment), exit.

## 12. Implementation notes

- Python 3.11+, standard library plus PyYAML, managed with `uv`. Single package, `asyncio` for
  subprocesses. Child processes start in their own session (`start_new_session=True`) and are
  killed with `os.killpg` (SIGTERM, then SIGKILL after 5 s).
- One event loop owns all state changes; workers report back through it.
- Moves are `os.rename` within the same filesystem (atomic).
- The validate command for Symphony's own code: `uv run pyright` (strict) and `uv run pytest`.
- A Rust rewrite is expected later. To keep the tests reusable, the main suite is **black-box**:
  it builds a temporary git repo, writes `WORKFLOW.md` and task files, runs the `symphony` CLI as a
  subprocess with `--exit-when-idle`, and asserts only on files (task folders, sidecars, task `## Log`,
  branches, worktrees) and on the calls recorded by a fake `claude`. Nothing in it imports the
  Python package. Unit tests of Python internals are kept few.
- The fake `claude` (`tests/fake_claude.py`) follows a per-task script of steps (outcome, cost, file
  writes, commits, exit code, `is_error`, missing result, hang, malformed lines, permission denials,
  missing session on resume) and records each invocation's argv for assertions.
- Symphony checks `claude auth status` at startup and refuses to start when logged out.

### 12.1 Verified Claude Code behavior (2.1.220, 2026-11-06)

Tested with throwaway repos and `--model haiku`:

- `-p --output-format stream-json` errors without `--verbose`.
- `--session-id <uuid>` sets the id; reusing an id errors ("already in use"); `--resume <id>` from a
  new process (and a different cwd) keeps conversation memory; unknown id gives exit 1,
  `subtype: error_during_execution`, stderr "No conversation found".
- `result.total_cost_usd` is per invocation.
- An auth failure gives exit 1, `is_error: true`, but `subtype: "success"`.
- `--add-dir <dir>` allows reading and editing files there; without it reads are denied.
- `--append-system-prompt` and the repo `CLAUDE.md` both apply in `-p` mode.
- Claude Code's built-in prompt makes the agent treat commits as needing the user's request, even
  with user config isolated; the protocol prompt must authorize commits explicitly.
- `--permission-mode dontAsk`: disallowed calls are denied, the run continues and exits 0, denials
  are listed in `result.permission_denials`, and the agent does not try to work around them.
- `permissions.allow` in the repo's `.claude/settings.json` is ignored in untrusted folders (stderr
  warning); `--allowedTools` and `--settings` allow rules are honored.
- `--json-schema` returns the parsed object in `result.structured_output`.
- Isolation results: see §9.4.
- Read-only planning (§14.4): `--permission-mode plan` runs headless without hanging, but its Write
  tool still succeeds by redirecting to `~/.claude/plans/<name>.md` (a file in the user's home), and
  it switched to a different model than `--model` asked for (17x the cost in the test).
  `dontAsk` with `--allowedTools Read Grep Glob` denies writes, still auto-allows read-only shell
  commands (`git log`, `git status`, `ls`), honors `--model`, and returns structured output.

## 13. Later (explicitly out of v0)

- Reviewer pass: a second Claude run with a review prompt before moving to `review/`.
- Gardening: scheduled tasks that drop cleanup tickets into `todo/` (stale docs, drift, tech debt).
- Other task stores behind §4.4 (GitHub Issues, Jira, Linear).
- PR creation on `review` and feeding PR comments or CI results back as `## Feedback`.
- Claude Agent SDK runner, if in-process permission callbacks become useful.
- Live reload of `WORKFLOW.md`.
- Automatic subtask creation from a plan, with dependency tracking ("blocked by").
- Plans committed into the repo (for example `docs/exec-plans/`) instead of only the task file.

## 14. Planning phase (v0.2)

Status: implemented. Details settled during implementation:

- `--exit-when-idle` also waits while `plan/` is non-empty (`plan-review/` is the human's, like
  `review/`).
- On approval (rule 2) Symphony sets `last_outcome = "approved"` so a later stop or retry does not
  clear the execution session again.
- Headings `#` and `##` inside `plan` and `questions` are written as `###`, so they cannot be
  mistaken for task sections when the `## Plan` section is replaced.
- A configured `prompts.plan` replaces the default whole (the default is the `WORKFLOW.md` body
  rendered, then the sentence in §14.5); `prompts.plan_revise` replaces the revise prompt.
- The planning variant of the execution protocol lives in `prompts.PLAN_PROTOCOL`; budget caps apply
  to planning like to execution (§9.1).
- In `symphony status` the running phase appears in the STATE column.

### 14.1 Goal

Let the human review a plan before any code is written, for the tasks where that is worth it.
Planning is **opt-in per task** (or per repo via `require_plan`). Tasks that skip it behave exactly
as in v0. A planning run can read the repository but cannot change anything; the plan comes back as
structured output and Symphony writes it into the task file.

### 14.2 States and flow

Two new state folders, added to §2 layout, §4.1 and to `STATES` (order matters for `status`
output): `plan`, `plan-review`, `todo`, `running`, `review`, `blocked`, `done`.

| Folder        | Meaning                                         | Who moves files in |
|---------------|-------------------------------------------------|--------------------|
| `plan`        | Ready to be planned (new, or plan revision)     | Human              |
| `plan-review` | Plan written; waiting for the human             | Symphony           |

```
plan ──dispatch──> running (phase plan) ──planned──> plan-review
                         │  ├──blocked──> blocked
                         │  └──failure──> plan (retry) / blocked (gave up)
plan-review ──human approves: move to todo──> todo ──> running (phase execute) ──> review ...
plan-review ──human adds ## Feedback, moves to plan──> plan   (revises the same plan)
```

- `running/` is shared by both phases. The sidecar field `phase` (`"plan"` or `"execute"`) says
  which one a running task is in. Reconcile, stop, shutdown and recovery work unchanged: on
  recovery or shutdown a running task goes back to the folder it was dispatched from (`plan/` when
  `phase == "plan"`, else `todo/`).
- Retries of a failed planning run go back to `plan/` (same backoff and `max_attempts` as §5.4,
  and the give-up reflection turn is skipped for planning runs).

### 14.3 Dispatch rules

Dispatch candidates come from both `plan/` and `todo/`, in one list sorted as in §5.2, limited by
the same `max_concurrent`. For each candidate, the phase is decided at dispatch:

1. File in `plan/` → phase `plan`.
2. File in `todo/` and sidecar `last_outcome == "planned"` → the human approved the plan: set
   `plan_approved = true`, clear `session_id` (execution starts a fresh session, §14.6), phase
   `execute`.
3. File in `todo/`, `planning.require_plan` is true, and `plan_approved` is false → phase `plan`.
4. Otherwise → phase `execute` (v0 behavior).

The attempt reset rule of §5.4 also applies to planning (`last_outcome` of `blocked` or `failed`).

### 14.4 The planning run

Same machinery as §9 (worktree, stream reading, timeouts, cost accounting, budget cap, denials
logged), with these differences:

- **Permissions:** always `--permission-mode dontAsk` and `--allowedTools <planning.allow>`
  (default `Read`, `Grep`, `Glob`), regardless of `claude.permission_mode` and `claude.allow`.
  Verified (§12.1): writes are denied, read-only shell commands still run. Do **not** use
  `--permission-mode plan`: it writes files into `~/.claude/plans/` and changes the model.
- **Model:** `--model <planning.model>` if set, else `claude.model`.
- **Session:** its own session id, stored in sidecar `plan_session_id` (separate from
  `session_id`). First planning run: new session with the `plan` prompt. Revision (sidecar has
  `plan_session_id`): `--resume` it with the `plan_revise` prompt. Missing session: start fresh
  with the `plan` prompt, as in §9.1.
- **One invocation per dispatch** (no continue loop, no validation).
- **Outcome schema** (passed with `--json-schema`):

  ```json
  {"type": "object",
   "properties": {"outcome": {"type": "string", "enum": ["planned", "blocked"]},
                  "plan": {"type": "string"},
                  "questions": {"type": "string"},
                  "summary": {"type": "string"}},
   "required": ["outcome", "plan", "summary"]}
  ```

- **Protocol prompt:** a planning variant of §8.5 (Symphony-owned, appended with
  `--append-system-prompt`): you are planning unattended under Symphony; you cannot edit files and
  must not try; read whatever you need; return the plan in `plan` as Markdown with the sections
  *Approach*, *Steps* (checkboxes), *Files to change*, *Risks*, *How to verify*, and, if useful,
  *Suggested subtasks*; put questions for the human in `questions` and use outcome `blocked` only
  when the plan cannot be written without the answers.
- **Writing the result** (no agent running at that point, per §3.3):
  - Replace the whole `## Plan` section of the task file with `## Plan` followed by `plan`
    (create it if missing, before `## Log` if present, else at the end). Never duplicate it.
  - If `questions` is non-empty, replace the `## Questions` section the same way.
  - Append a `## Log` line as in §5.3, including `summary`.
- **Transitions:** `planned` → `plan-review/`, `last_outcome = "planned"`. `blocked` → `blocked/`,
  `last_outcome = "blocked"`. Missing or invalid structured output, or no `plan` text with outcome
  `planned` → a failure (§5.4).

### 14.5 Prompts

Added to §8.3 defaults and overridable in `prompts:` like the others:

- `plan`: the `WORKFLOW.md` body rendered as usual (§8.1), followed by: "Do not implement anything
  yet. Produce a plan for this task."
- `plan_revise`: "The human reviewed your plan and left feedback in your task file at
  {{ task.path }} (see `## Feedback`). Re-read it and return a revised plan."

### 14.6 Executing an approved plan

- Execution after approval starts a **new** session (§14.3 rule 2). The plan must stand on its own;
  if a fresh session cannot follow it, the plan was incomplete.
- When `plan_approved` is true, the execution protocol prompt (§8.5) gets one extra rule: "An
  approved plan is in the `## Plan` section of your task file. Follow it. If you must deviate,
  record what and why in `## Log`. Tick the plan's checkboxes as you complete steps."
- Everything else is v0 behavior (continue loop, validation, review).
- Rework from `review/` (move to `todo/`) keeps `plan_approved = true` and resumes the execution
  session, as in v0.

### 14.7 Config

Added to §6.1:

```yaml
planning:
  require_plan: false         # true: todo/ tasks are planned (and reviewed) before execution
  model: null                 # defaults to claude.model
  allow: ["Read", "Grep", "Glob"]
```

### 14.8 Sidecar and status

- New sidecar fields: `phase` (`"plan" | "execute" | null`), `plan_session_id` (string or null),
  `plan_approved` (bool, default false). Old sidecars without them load with defaults.
- `symphony status` shows the two new states; for running tasks it shows the phase.
- `symphony new --plan` creates the task in `plan/` instead of `todo/`.

### 14.9 Fake claude additions

`tests/fake_claude.py` step fields: `plan` (string, put in `structured_output.plan`),
`questions` (string). For planning runs the fake emits `outcome` as given (`planned` or
`blocked`). Keep it standard-library only.

### 14.10 Black-box tests to add

All in the style of `tests/test_blackbox.py` (CLI subprocess, assert on files and recorded calls):

1. A task in `plan/` ends in `plan-review/` with the plan text under `## Plan`; the call used
   `--permission-mode dontAsk`, `--allowedTools` exactly `planning.allow`, a schema whose outcome
   enum is `["planned", "blocked"]`, and no execution-only flags' values (no `Edit` in the allow
   list); no commits were added to `symphony/<id>`.
2. Approval: moving it to `todo/` runs execution with a **new** `--session-id` (not the plan
   session), the system prompt mentions the approved plan, and it ends in `review/`.
3. Rejection: adding `## Feedback` and moving it to `plan/` resumes `plan_session_id` with the
   revise prompt; afterwards the task file has exactly one `## Plan` section, containing the
   revised plan.
4. `planning.require_plan: true`: a task in `todo/` goes to `plan-review/` first, then executes
   after approval.
5. Default config: a task in `todo/` executes directly (no planning call).
6. Planner `blocked` with `questions`: task in `blocked/`, `## Questions` contains them; moving it
   back to `plan/` replans with attempts reset.
7. Planner failure then success: retried from `plan/`, ends in `plan-review/`; with
   `max_attempts: 1` it ends in `blocked/` and no give-up reflection call is made.
8. `planning.model` is passed as `--model` for planning and `claude.model` for execution.
9. Recovery: a task in `running/` with sidecar `phase: "plan"` at startup is re-planned from
   `plan/`, not executed.
10. Moving a task out of `running/` during planning stops the planner (as in v0).
11. `symphony new --plan` creates the file in `plan/`.

All existing tests must keep passing unchanged; `uv run pyright` must stay at 0 errors.
