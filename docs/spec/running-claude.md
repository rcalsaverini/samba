# Running Claude Code

## Invocation

```
<claude.command> -p <prompt> \
  --output-format stream-json --verbose \
  (--session-id <new uuid> | --resume <session_id>) \
  --add-dir <abs tasks dir> \
  --append-system-prompt <rendered protocol prompt (prompts, Protocol prompt)> \
  --json-schema <outcome schema (running-claude, Outcome)> \
  --permission-mode <claude.permission_mode> \
  --allowedTools <claude.allow...> \
  [--model <claude.model>] \
  [--max-budget-usd <remaining task budget>] \
  [--setting-sources project,local --strict-mcp-config \
   --settings '{"claudeMdExcludes": [<ancestor CLAUDE.md paths>]}']   # when isolate_user_config (running-claude, User config isolation)
  <claude.args...>
```

- cwd = workspace. stdin = `/dev/null` (otherwise Claude waits 3 s for piped stdin and warns).
- `--verbose` is mandatory with `-p` and `stream-json` (the CLI errors without it).
- **Session ids are chosen by Samba.** For a new session, Samba generates a UUID, writes it to
  the sidecar, then passes `--session-id`. Later runs pass `--resume <id>`. A UUID is never reused
  with `--session-id` (the CLI rejects an id already in use). Resume works from any cwd.
- If `--resume` fails because the session is gone (`result.subtype == "error_during_execution"`,
  stderr "No conversation found with session ID"), Samba starts a new session with the first
  prompt (prompts, Which prompt is sent). This does not count as a failed attempt.
- `--add-dir` gives the agent read and write access to the tasks folder. Without it, reading the task
  file is denied.
- `--max-budget-usd` is set to `max_cost_usd_per_task - cost_usd_total` when a task cap is set. The cap applies to planning runs too.
- The prompt is passed as an argument.

## Reading the stream

- stdout: one JSON object per line. Each line updates `last_event_at` and is appended verbatim to
  `runs/<id>/<n>.jsonl`. Lines that are not JSON are logged and skipped.
- Event order: optional `system` hook events, then `system`/`init`, then `assistant`/`user` messages,
  then one `result`. Do not assume `init` is the first line.
- `init` lists what was loaded (`skills`, `plugins`, `mcp_servers`, `tools`, `permissionMode`).
  Samba logs these on the first run of each `samba run`, so leaks are visible.
- `result` fields used: `is_error`, `subtype`, `result` (text), `structured_output`,
  `total_cost_usd` (for this invocation only, not cumulative over a resumed session),
  `usage.input_tokens`, `usage.output_tokens`, `num_turns`, `terminal_reason`,
  `permission_denials`.
- **Success = exit code 0 and `is_error == false`.** `subtype` is not reliable: an expired login
  produced `subtype: "success"` with `is_error: true` and exit code 1.
- stderr: appended to `samba.log` as diagnostics, never parsed except for the resume case above.
- Turn timeout (`claude.turn_timeout_s` since launch) and stall (no stdout line for
  `claude.stall_timeout_s`) kill the process group and count as a failure (orchestrator, Failures and retries).

## Outcome (structured output)

Every run passes `--json-schema` with:

```json
{"type": "object",
 "properties": {"outcome": {"type": "string", "enum": ["done", "blocked", "continue"]},
                "summary": {"type": "string"},
                "questions": {"type": "array", "minItems": 1,
                              "items": {"type": "object",
                                        "properties": {"text": {"type": "string"},
                                                       "context": {"type": "string"}},
                                        "required": ["text", "context"]}}},
 "required": ["outcome", "summary"]}
```

Claude Code returns the parsed object in `result.structured_output` (verified). Samba reads
`outcome` from there:

- `done`: work complete, ready for validation.
- `blocked`: needs the human; the questions are in `questions` (states, Questions).
- `continue`: more work left.

If `structured_output` is missing or invalid, treat as `continue` and log a warning. `summary` is
written into the task's `## Log` line for that run.

## Planning run

Same machinery as the rest of this chapter (worktree, stream reading, timeouts, cost accounting,
budget cap, denials logged), with these differences:

- **Permissions:** always `--permission-mode dontAsk` and `--allowedTools <planning.allow>`
  (default `Read`, `Grep`, `Glob`), regardless of `claude.permission_mode` and `claude.allow`.
  Verified (below, Verified Claude Code behavior): writes are denied, read-only shell commands
  still run. Do **not** use `--permission-mode plan`: it writes files into `~/.claude/plans/` and
  changes the model.
- **Model:** `--model <planning.model>` if set, else `claude.model`.
- **Session:** its own session id, stored in sidecar `plan_session_id` (separate from
  `session_id`). First planning run: new session with the `plan` prompt. Revision (sidecar has
  `plan_session_id`): `--resume` it with the `plan_revise` prompt. Missing session: start fresh
  with the `plan` prompt, as in Invocation above.
- **One invocation per dispatch** (no continue loop, no validation).
- **Outcome schema** (passed with `--json-schema`, instead of the work schema above):

  ```json
  {"type": "object",
   "properties": {"outcome": {"type": "string", "enum": ["planned", "blocked"]},
                  "plan": {"type": "string"},
                  "assumptions": {"type": "string"},
                  "questions": {"type": "array", "minItems": 1,
                                "items": {"type": "object",
                                          "properties": {"text": {"type": "string"},
                                                         "context": {"type": "string"}},
                                          "required": ["text", "context"]}},
                  "summary": {"type": "string"}},
   "required": ["outcome", "plan", "summary"]}
  ```

- **Protocol prompt:** the planning variant (prompts, Protocol prompt).
- **Writing the result** follows task-files, Write discipline (the plan and assumptions sections,
  `## Questions`, and the `## Log` line with `summary`).
- **Transitions:** `planned` goes to `plan-review/` with `last_outcome = "planned"`. `blocked` goes
  to `question/` with `last_outcome = "blocked"`, `blocked_cause = "question"`, and `last_stage`
  stays `plan`; the questions are recorded as in states, Questions. Budget exceeded goes to
  `stuck/` (cause `budget`). Missing or invalid structured output, or no `plan` text with outcome
  `planned`, is a failure (orchestrator, Failures and retries).

## User config isolation

Headless Claude Code normally loads the user's own config as well as the repo's. On the test machine
a default run loaded the user `CLAUDE.md`, 50 skills, 12 plugins, user hooks, and 37 MCP servers
including claude.ai connectors (Gmail, Drive, Calendar and more). Besides conflicting rules, that
gives an unattended agent access to the user's accounts.

When `claude.isolate_user_config` is true, Samba adds
`--setting-sources project,local --strict-mcp-config` and
`--settings '{"claudeMdExcludes": [...]}'`, where the list holds `CLAUDE.md`, `CLAUDE.local.md`,
`.claude/CLAUDE.md` and `.claude/CLAUDE.local.md` for **every ancestor directory of the worktree**
(not the worktree itself, so the repo's own files still load).

The exclude list is needed because Claude Code also loads memory files from each ancestor of its
working directory, and `--setting-sources` does not cover that route. Worktrees live under
`~/.samba/workspaces/` by default, so the home directory is an ancestor and the user's
`~/.claude/CLAUDE.md` is found there as an ancestor's `.claude/CLAUDE.md`. Found in use: personal
rules ("ask before committing", "no Co-Authored-By") appeared in a planner's output. Do not use a
broad pattern such as `$HOME/**`: it would also exclude the repo's own `CLAUDE.md`.

Verified effect (Claude Code 2.1.220):

| Source | Default | Isolated |
|---|---|---|
| User `~/.claude/CLAUDE.md` | loaded | **not loaded** (needs the ancestor excludes when the worktree is under `$HOME`) |
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

## Verified Claude Code behavior (2.1.220, 2026-11-06)

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
- Isolation results: see User config isolation above.
- Ancestor memory files (2026-11-07): run from a folder under `$HOME` with
  `--setting-sources project,local --strict-mcp-config`, the agent still saw a rule that exists
  only in `~/.claude/CLAUDE.md`; run from a folder under `/tmp`, it did not. Adding
  `--settings '{"claudeMdExcludes": [<each ancestor's CLAUDE.md, CLAUDE.local.md,
  .claude/CLAUDE.md>]}'` removed the user rule while the folder's own `CLAUDE.md` still loaded.
  `claudeMdExcludes` accepts absolute paths and globs.
- Read-only planning (Planning run above): `--permission-mode plan` runs headless without hanging, but its Write
  tool still succeeds by redirecting to `~/.claude/plans/<name>.md` (a file in the user's home), and
  it switched to a different model than `--model` asked for (17x the cost in the test).
  `dontAsk` with `--allowedTools Read Grep Glob` denies writes, still auto-allows read-only shell
  commands (`git log`, `git status`, `ls`), honors `--model`, and returns structured output.

