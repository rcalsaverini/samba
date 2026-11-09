# Samba user manual

How to set Samba up in a repository and run tasks through it day to day. This manual explains
what to do; for the exact rules (every state, event, flag and exit code) it links to
the [specification](spec/README.md) by chapter.

## 1. What Samba is

Samba is a local orchestrator for Claude Code. You write tasks as markdown files. For each task,
Samba creates a git worktree and branch, runs Claude Code headless in it, and, when the agent says
it is done, runs your validation command itself. Only work that passes validation reaches you.
You review, then merge.

The mental model:

- One task is one markdown file, one worktree and one branch (`samba/<id>`).
- The folder a task file sits in is its complete state. Moving the file is a state change.
- You are the reviewer. The agent never merges; tasks stop in `work-review` with a branch for you.
- Everything lives in plain files, so you can steer with an editor and a file browser as well as
  with commands.

Details: spec chapters overview, layout, states.

## 2. Prerequisites

- `git`, and a repository with at least one commit on its base branch (default `main`).
- Python 3.11 or newer and [`uv`](https://docs.astral.sh/uv/).
- The Claude Code CLI installed, on your `PATH` as `claude`, and logged in. Samba checks
  `claude auth status` at startup and refuses to start when you are logged out.

Samba installs a `samba` command (`pyproject.toml`, `[project.scripts]`). From a Samba checkout
you can run it as `uv run samba ...`. Run every command from the root of the repository you want
to work on, or pass `--repo PATH`. The examples below write `samba` for either form.

```
$ samba --help
$ samba task --help
```

Every command is `samba run` or `samba <noun> <verb>`. There are no top-level shortcuts such as
`samba new` or `samba status`. Spec chapter cli.

## 3. Setting up a repository

Samba reads one file from the root of the target repo: `WORKFLOW.md`. The front matter (YAML) is
configuration, the body is the prompt sent to the agent on its first turn. Every key is optional.
The spec chapter workflow-config has the full list with defaults.

A small, realistic example:

```markdown
---
max_concurrent: 1
max_turns: 15
max_cost_usd_per_task: 5.0
hooks:
  after_create: uv sync -q
validate:
  command: uv run pyright && uv run pytest -q
  timeout_s: 600
claude:
  model: sonnet
  allow:
    - Edit
    - Write
    - "Bash(uv run pyright:*)"
    - "Bash(uv run pytest:*)"
    - "Bash(git add:*)"
    - "Bash(git commit:*)"
    - "Bash(git status:*)"
    - "Bash(git diff:*)"
    - "Bash(git log:*)"
---
Task: {{ task.title }}

{{ task.body }}

Start by reading CLAUDE.md. Write tests first, then the implementation.
```

The settings that matter most:

- **`validate.command`**: the mechanical check. When the agent reports done, Samba runs this in
  the worktree. Only exit code 0 moves the task to review; on failure the agent gets the tail of
  the output and tries again. `work accept` runs the same command again on the merged result.
  It runs in a non-login `bash -c` that inherits Samba's environment, so pin your tools
  (`uv run pytest`, `make check`, `./scripts/check`) instead of relying on `PATH`. Allow the
  agent to run the exact same command. Spec chapter workspaces, Validation.
- **`claude.allow`**: the tools the agent may use. Headless runs cannot answer permission
  prompts, so anything not allowed is denied. The list lives in `WORKFLOW.md` and not in
  `.claude/settings.json` because Claude Code ignores project allow rules in folders it has not
  seen, and every worktree is new. Allow commands as plain single commands: a rule matches the
  whole command line, so a pipe, `;` or `&&` is denied. Optionally `claude.permission_mode`
  (`dontAsk` by default; `bypassPermissions` only for throwaway repos). Spec chapter workflow-config, Permissions.
- **`max_cost_usd_per_task`**, **`max_turns`**, **`max_attempts`**: the budgets, see section 11.
- **`hooks.after_create`**: a shell script run once in each new worktree (for example
  `uv sync -q`). If it fails, the attempt fails. Spec chapter workspaces, Creation.
- **`planning.require_plan`**: when `true`, every task is planned and reviewed before any code is
  written, even if it was created with `--skip-plan` or by hand. Spec chapters states (Planning stage), running-claude (Planning run).
- **`base_branch`** (default `main`) and **`workspaces_root`** (default `~/.samba/workspaces`,
  must be outside the repo).
- The body: state the task with `{{ task.title }}` and `{{ task.body }}`, point to the repo's own
  `CLAUDE.md` and docs, and say how your repo wants work done (commit size, tests, when to ask).
  You do not need to explain the outcome format or the task-file rules: Samba injects those
  itself. Spec chapter prompts, What the WORKFLOW.md body should tell the agent.

`WORKFLOW.md` is read once at startup. After editing it, stop `samba run` (Ctrl-C) and start it
again.

On first start Samba creates `.samba/` in the repo and adds it to `.git/info/exclude` (it never
touches your `.gitignore`). `.samba/` holds the task folders, the sidecar state, the run logs and
`samba.log`. Spec chapter layout.

## 4. Writing a good task

Create tasks with `samba task new`:

```
$ samba task new "Add CSV export to the report page" --body "Add a CSV button to the report page. Reuse the existing export helper. Acceptance: a test downloads the file and checks the header row. Do not change the PDF export."
$ samba task new "Wire the export button" --depends-on add-csv-export-to-the-report-page --priority 1 --skip-plan
```

It prints the path of the new file. On a terminal, any field you did not give as a flag is
prompted (title, description, dependencies, plan first or not). With no terminal and no title it
is a usage error. Spec chapter cli.

A task file is markdown with optional front matter:

```markdown
---
priority: 2
depends_on: [add-csv-export-to-the-report-page]
---
# Wire the export button

Goal, context, acceptance criteria, what not to touch.
```

Tips for the text:

- **Title**: the first `# ` heading. The file name (minus `.md`) is the task id, and `task new`
  derives it from the title. Ids may contain only letters, digits, `.`, `_` and `-`.
- **Body**: write the goal, the context the agent cannot guess, acceptance criteria it can check
  (ideally ones your validate command exercises), and what not to do. If you would ask a
  colleague a question first, answer it in the body.
- **`priority`**: an integer, lower runs first; a task without one runs last. `task new` writes 3
  unless you pass `--priority`.
- **`depends_on`**: ids of tasks that must be `done` (merged) first. The dependent task waits in
  its todo folder, and its worktree branches from a base branch that already has the
  dependency's work. A dependency that was discarded sends the dependent task to `stuck`. Spec
  chapter orchestrator, Dependencies.
- **Plan first or not**: by default a task starts in `plan-todo`: the agent reads the repo,
  cannot change anything, and returns a plan you approve or reject before any code is written.
  `--skip-plan` creates the task in `work-todo` and goes straight to work (unless
  `planning.require_plan` is set). Use planning for anything non-trivial, where a wrong approach
  would be expensive to find in review. Spec chapters states (Planning stage), running-claude (Planning run).

You can also create the file by hand in `.samba/tasks/plan-todo/` or `.samba/tasks/work-todo/`.

## 5. The lifecycle

The folders under `.samba/tasks/` are the states:

```
                   task new
                      |
                      v
 +---------------> plan-todo ---- orchestrator dispatch ---> plan-running
 |  plan reject        ^                                       |    |    |
 |                     | retry (attempts left)                 |    |    '-- budget or give up --> stuck
 |                     '---------------------------------------'    '-- agent asks --> question
 |                                                                |
 '--------------------------- plan-review <---- plan written -----'
                                  |
                                  | plan accept
                                  v
 task new --skip-plan ---------> work-todo ---- orchestrator dispatch ---> work-running
                                  ^  ^                                       |    |    |
                  work reject     |  '-- retry (attempts left) --------------'    |    '-- agent asks --> question
                  question answer |                                               '-- budget, give up, task stop --> stuck
                  task retry      |
                                  |                  validate passes
                              work-review <---------------------------- work-running
                                  |
                                  | work accept (merges the branch)
                                  v
                                 done

 question --question answer (all answered)--> plan-todo or work-todo
 stuck    --task retry-----------------------> plan-todo or work-todo
 any folder except done and discarded --task discard--> discarded
 running folder --task stop--> stuck
```

In words:

| Folder | What it means | What you do |
|---|---|---|
| `plan-todo` | queued for planning | nothing; `samba run` picks it up |
| `plan-running` | a planner is running | nothing |
| `plan-review` | a plan is written | `samba plan accept` or `samba plan reject` |
| `work-todo` | queued for work (new, approved, retried, reworked) | nothing |
| `work-running` | an agent is running | nothing |
| `work-review` | validation passed, branch ready | `samba work accept` or `samba work reject` |
| `question` | the agent asked something | `samba question answer` |
| `stuck` | budget, gave up, stopped or dependency problem | fix the cause, then `samba task retry` |
| `done` | accepted and merged (terminal) | none |
| `discarded` | abandoned (terminal) | none |

`question` and `stuck` hold tasks from either stage. Samba remembers which stage a task came from
and why it stopped (the `blocked_cause`, section 7) and sends it back to the right todo folder.
The full table of events, guards and effects is in the spec chapter states.

Moving files by hand is observed: if you drag a task between folders while it is a legal move
(for example `plan-review` to `work-todo`, which is the same as `plan accept`), Samba applies
the same event the command would. Nothing outside Samba happens on a hand move: dragging a task
to `done` never merges. An illegal move, such as `work-todo` to `done`, is moved back and a line
is added to the task's `## Log`. Prefer the commands: they check the state, write feedback and
tell you what is legal when you are wrong.

`samba dev transitions` prints the transition table as Markdown. It is a developer command for
people working on Samba itself, not part of the daily loop; you can ignore it.

## 6. The daily loop

1. Create a task: `samba task new "..." --body "..."` (section 4).
2. Start the orchestrator in a terminal and leave it running:

   ```
   $ samba run
   ```

   It runs in the foreground, dispatching ready tasks up to `max_concurrent` at a time. Ctrl-C
   stops all agents and moves their tasks back to their todo folder without counting a failure.
   `samba run --exit-when-idle` exits once nothing is running and nothing runnable is queued,
   which suits one-off batches. Tasks held only by dependencies do not keep it alive.

3. Check progress from another terminal:

   ```
   $ samba task list
   $ samba task list plan-review work-review
   $ samba task list q stuck
   ```

   State arguments are exact names or unique prefixes (`work` matches all three work folders).

4. **Review the plan.** A task in `plan-review` has a `## Plan` section (and maybe
   `## Assumptions`) in its file. The plan has a "Spec changes" section: the parts of
   your project's spec the task will change, or "none, because ...". Check that it is right, since the work
   agent owes exactly those edits. Then:

   ```
   $ samba plan accept <id>
   $ samba plan reject <id> --feedback "Do not touch the PDF export; split step 3."
   $ samba plan reject <id> --edit
   ```

   `reject` writes your feedback under `## Feedback` as a new round and the planner revises the
   same plan. `--edit` opens `$EDITOR` (else `$VISUAL`, else `vi`). Accepting starts work in a
   fresh session that follows the approved plan.

5. **Review the work.** A task in `work-review` passed your validate command. Read its `## Log`,
   then inspect the diff (section 10). Then either:

   ```
   $ samba work reject <id> --feedback "The export ignores the date filter."
   $ samba work reject <id> --edit
   $ samba work reject <id> --feedback "Start over with a simpler approach." --fresh
   ```

   The diff includes the spec edits the agent made on the branch, which you review next to the
   code. If the task made a real decision, it also contains a new ADR in `docs/adr/` with status
   `proposed`. To accept it, change its status to `accepted` in a follow-up commit of your own.

   Rework resumes the agent's session, so it remembers its earlier turns; `--fresh` clears the
   session so it starts a new conversation (the feedback is still in the task file).

6. **Accept the work.** `samba work accept <id>` merges the branch into your main checkout:

   ```
   $ samba work accept <id> --dry-run
   $ samba work accept <id>
   ```

   What it does (spec chapter cli):

   - Preflight, changing nothing if it fails: the task is in `work-review`, your main checkout
     is on `base_branch` with no uncommitted changes to tracked files, and branch `samba/<id>`
     exists.
   - Asks `Merge samba/<id> into main (N commits)? [y/N]` on a terminal. Use `--yes` to skip it;
     without a terminal and without `--yes` it refuses.
   - Runs `git merge --no-ff --no-commit`, then your `validate.command` on the merged result, and
     commits only if it passes. This catches a branch that passes alone but breaks after a base
     branch that moved on. On a conflict or failed validation the merge is aborted and the task
     stays in `work-review`.
   - Moves the task to `done`. The worktree is removed; the branch is kept.

   `--dry-run` prints what would happen and changes nothing. `--no-validate` skips the validate
   step. `--no-merge` marks the task done without merging, for when you already merged by hand.
   Commands that take `--repo PATH` work from any directory.

All commands accept a unique prefix of a task id, so `samba plan accept add-csv` works when only
one task starts that way.

## 7. Questions and stuck tasks

### Questions

When the agent (or planner) cannot continue without a decision, the task goes to `question`.
Each question has an id such as `q1`; its full name is `<task>/<qid>`.

```
$ samba question list
$ samba question show <id>
$ samba question show <id>/q1
$ samba question answer <id>/q1 "Use the existing helper."
$ samba question answer <id> --edit
```

- `question list` shows every open question of every task, with the full name ready to paste.
- `question show` prints the text, the context and the answer. Without `/qid` it shows the whole
  latest round.
- `question answer` records one answer at a time. The task moves back to its todo folder only
  when no question of the latest round is still open, then the agent resumes and sees the
  questions and your answers. You may leave out `/qid` only when exactly one question is open.
  Answers cannot be empty; `--edit` opens `$EDITOR` with the question as comment lines.

If you move a task out of `question/` by hand instead, its open questions are marked dismissed
and the agent is told so. Spec chapters states (Questions), cli.

### Stuck tasks

A task in `stuck` needs a human decision. `samba task list` shows the cause in parentheses
(`stuck (budget)`) and `samba task show <id>` prints it as `blocked_cause`. Fix the cause first,
then send the task back:

```
$ samba task show <id>
$ samba task retry <id>
```

`task retry` resets the attempt counter and moves the task to the todo folder of the stage it
was in. It never edits your config; for some causes it prints a hint on stderr.

| `blocked_cause` | What happened | Fix first |
|---|---|---|
| `budget` | `max_cost_usd_per_task` was reached (cumulative across runs) | raise `max_cost_usd_per_task`, `max_turns` or `max_attempts` in `WORKFLOW.md` and restart `samba run`; or split the task. Retrying without a higher cap sends it straight back to `stuck`. |
| `gave_up` | `max_attempts` failures in a row | read `last_error` in `task show`, the task's `## Log` and its `## Harness gaps` section (the agent writes what was missing). Fix the missing tool, doc, permission or fixture, then retry. |
| `stopped` | you ran `task stop` | nothing to fix; `task retry` resumes it |
| `dependency_discarded` | a task in `depends_on` was discarded | edit `depends_on` in the task file (or discard the task), then retry |
| `dependency_cycle` | tasks depend on each other | edit `depends_on` to break the cycle, then retry |

The `blocked_cause` list is open: newer versions may add values. `question` also appears as a
cause for tasks in the `question` folder.

## 8. Stopping and discarding

- **Stop a running task**: `samba task stop <id>`. The task moves to `stuck` with cause
  `stopped`, with no attempt counted, and is not dispatched again. If `samba run` is active, its
  next tick kills the agent. `samba task retry <id>` sends it back to its todo folder.
- **Discard a task**: `samba task discard <id>` abandons it from any state except `done` and
  `discarded`. It asks `Discard task <id>? [y/N]` on a terminal; `--yes` skips the prompt, and
  without a terminal and without `--yes` it refuses.
- **Stop everything**: Ctrl-C on `samba run`.

A discarded task keeps its file in `discarded/` and its branch; the worktree is removed. Samba
never deletes branches or task files. Spec chapters orchestrator (Tick), cli.

## 9. Reading state

```
$ samba task list
$ samba task show <id>
```

`task list` prints one row per task with the columns ID, STATE, ATTEMPTS, TURNS, COST, LAST and
ERROR. STATE is the folder name; `question` and `stuck` add the cause, as in `stuck (budget)`.
LAST is the last run's outcome, or `(retry in 45s)` while the task waits out a retry delay, or
`waiting on other-task` when a todo task is held only by dependencies.

For example, with one planned task and one that depends on it:

```
$ samba task list
ID                                 STATE      ATTEMPTS  TURNS  COST   LAST                                          ERROR
add-csv-export-to-the-report-page  plan-todo  0         0      $0.00  -
wire-the-export-button             work-todo  0         0      $0.00  waiting on add-csv-export-to-the-report-page
```

`task show <id>` prints the details as `key: value` lines: title, state, cause, priority,
attempts, turns, cost, last outcome, the full last error, `depends_on` with each dependency's
state, open question count, branch, worktree path, session ids, and `events:` (the commands that
are legal for the task right now). Neither command needs `samba run` and neither changes
anything.

```
$ samba task show wire
id: wire-the-export-button
title: Wire the export button
state: work-todo
blocked_cause: -
priority: 1
attempts: 0
turns: 0
cost: $0.00
last_outcome: -
last_error: -
depends_on:
  add-csv-export-to-the-report-page (plan-todo)
dependency_status: waiting on add-csv-export-to-the-report-page
open_questions: 0
branch: -
worktree: -
session_id: -
plan_session_id: -
events:
  task.discard -> discarded
```

Where to look when you want more:

- The task's own `## Log` section: one line per run and per state change, written by Samba and
  the agent, including permission denials and validation failures.
- `.samba/samba.log`: one `key=value` line per event, always with `task=<id>`.
- `.samba/runs/<id>/<n>.jsonl`: the raw Claude Code event stream of turn `n`.
- `.samba/runs/<id>/validate-<n>.log`: the output of the validate command after turn `n`.
- `.samba/runs/<id>/accept-validate.log`: validation output from `work accept`.

Spec chapter observability.

## 10. Worktrees and branches

Each task works in its own git worktree, outside your repo:

- Worktree: `~/.samba/workspaces/<repo-key>/<id>`, where `<repo-key>` is the repo folder name
  plus 8 characters of a hash of its path. `samba task show <id>` prints the exact path.
- Branch: `samba/<id>`, started from `base_branch`.

The worktree stays while the task is alive and is removed when it reaches `done` or `discarded`.
Branches are never deleted by Samba; remove old ones yourself with `git branch -d` once you no
longer need them.

Inspect a task's work from your main checkout:

```
$ git log --oneline main..samba/<id>
$ git diff main...samba/<id>
$ git diff --stat main...samba/<id>
```

The three-dot form shows exactly what the branch adds since it left `main`. While the task is
still in `work-review` you can also open the worktree path in an editor, or run your tests there:

```
$ cd ~/.samba/workspaces/<repo-key>/<id>
$ uv run pytest -q
```

Do not commit in a worktree while an agent is running in it. Spec chapters layout, workspaces.

## 11. Costs and budgets

Three settings in `WORKFLOW.md` bound a task; all are checked per task:

- **`max_cost_usd_per_task`**: a cap in dollars, cumulative over every run of the task
  (planning included). Samba passes the remaining amount to Claude Code as `--max-budget-usd`.
  When it is exceeded the task goes to `stuck` with cause `budget`. Default: no cap.
- **`max_turns`** (default 10): Claude invocations per worker run, counting validation retries.
  Running out counts as a failure.
- **`max_attempts`** (default 3): failed worker runs before the task gives up and goes to
  `stuck` with cause `gave_up`. Failures are retried with a growing delay.

`max_concurrent` (default 2) limits how many agents run at once, which also limits how fast you
spend. See the cost of a task in `COST` in `samba task list` or `cost` in `samba task show`.
Planning and work runs both count. Spec chapters orchestrator (Worker, Failures and retries), workflow-config (Config).

## 12. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `samba run` exits at startup mentioning old folders and an `mv` recipe | Your repo has task files in the pre-rename folders (`plan`, `todo`, `running`, `review`, `blocked`). Samba never migrates them. Run the printed `mv` commands (for example `mv .samba/tasks/todo/*.md .samba/tasks/work-todo/`), then start again. Spec chapter orchestrator, Startup. |
| Samba refuses to start and mentions logged out | Claude Code is not logged in. Run `claude` and log in. An expired login mid-run shows up as a failed attempt with exit code 1 (Claude reports `is_error` even though it says "success"); log in and `task retry`. Spec chapter running-claude, Reading the stream. |
| The task moved to `question` with a strange question mentioning denied tools | The agent hit a permission denial and could not continue. The `## Log` lists each denied command. Add it to `claude.allow` (as a plain command, no pipes or `&&`), restart `samba run`, and answer the question. Spec chapters states (Questions), workflow-config (Permissions). |
| Validation passes for the agent but fails in Samba | Samba runs `validate.command` in a non-login `bash -c`, so tools can resolve differently than in the agent's shell. Pin them: `uv run pytest`, `make check`, a script. Read `.samba/runs/<id>/validate-<n>.log`. Spec chapter workspaces, Validation. |
| I moved a file and it jumped back, with `illegal move` in its `## Log` | That move is not in the transition table (for example `work-todo` to `done`, or `plan-todo` to `work-todo` after a rejected plan). Use the command, or `samba task show <id>` and read its `events:` list. Spec chapter states. |
| A command says `<id> is in <state>; <event> not allowed. Legal events: ...` | The task is in the wrong folder for that command. Nothing changed. Use one of the listed events. |
| A command fails with a lock message after waiting about 10 seconds | Another command or an orchestrator tick holds `.samba/lock`. Note that `work accept` holds it while validation runs. Wait and retry. Spec chapter task-files, Write discipline. |
| `work accept` refuses before doing anything | Preflight failed: the main checkout is not on `base_branch`, has uncommitted changes to tracked files, or branch `samba/<id>` is missing. Fix that and retry. Spec chapter cli. |
| `work accept` fails with conflicts or `validation failed after merge` | The merge was aborted and the task is still in `work-review`. The `## Log` line names the conflicting files or the last output lines; the full output is in `.samba/runs/<id>/accept-validate.log`. Rebase or merge `main` into the branch (or reject with feedback), then accept again. |
| `work accept` or `task discard` exits 2 | No terminal and no `--yes`. Add `--yes`. |
| Task in `stuck (budget)` | Cap reached. See the table in section 7. |
| Task in `stuck (gave_up)` | Read `task show` `last_error` and `## Harness gaps`. A worktree `after_create` failure (for example `uv sync` failing) is one common cause: run the hook command by hand in a fresh checkout to see the error. |
| A task never starts | Run `samba task list`: `waiting on <id>` means unmet `depends_on` (all must be `done`; an unknown id never unblocks); `(retry in Ns)` means a retry delay; `max_concurrent` agents may already be running. Also check that `samba run` is actually running and that the file name matches `[A-Za-z0-9._-]+` (other names are skipped with a warning in `.samba/samba.log`). |
| My personal Claude rules or plugins affect the agent | Keep `claude.isolate_user_config: true` (the default); it loads only the repo's config and excludes your `~/.claude` files. Spec chapter running-claude, User config isolation. |
| Changes to `WORKFLOW.md` have no effect | It is read at startup only. Restart `samba run`. |

For anything else, start with the task's `## Log`, then `.samba/samba.log`, then the raw stream
in `.samba/runs/<id>/`.
