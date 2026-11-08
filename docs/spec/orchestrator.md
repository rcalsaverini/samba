# Orchestrator loop

## Startup

1. Load and validate `WORKFLOW.md` (workflow-config). Fail fast on errors.
2. Check `git` and the Claude command are on `PATH`, and the cwd is a git repo root.
3. **Refuse the old layout:** if any of the old folders `plan/`, `todo/`, `running/`, `review/` or
   `blocked/` under `tasks/` still holds `*.md` files, exit non-zero before touching anything
   (no folder created, no file moved, no agent started). The message names the folders and prints
   an `mv` recipe, for example `mv .samba/tasks/todo/*.md .samba/tasks/work-todo/`
   (`plan` to `plan-todo`, `todo` to `work-todo`, `running` to the matching todo folder,
   `review` to `work-review`, `blocked` to `question` or `stuck`). Samba never migrates
   automatically. Empty old folders do not block.
4. Create folders, update `.git/info/exclude`.
5. **Recover:** every file in `plan-running/` and `work-running/` has no live agent (we just
   started). Fire `recover` for each (states, States): back to the todo folder of its own stage
   (`plan-todo/`, `work-todo/`) without incrementing `attempts`; its session will be resumed.
6. Start ticking every `poll_interval_s`.

## Tick

0. **Observe hand moves** (states, States): interpret every task file found in a folder other than its
   sidecar `state`, and move illegal moves back.
1. **Reconcile** each live agent:
   - Task file no longer in the running folder it was dispatched into (a legal hand move, or the
     file was deleted): kill the agent process. If the new state is `done` or `discarded`, or the file is gone,
     remove the worktree (keep the branch).
   - (Stalls are detected by the Claude runner itself while reading the stream, running-claude, Reading the stream.)
2. **Clean up** worktrees whose task is in `done/` or `discarded/` or no longer exists: remove the
   worktree (keep the branch). `done` means accepted and `discarded` means abandoned; the worktree
   and branch contract is the same for both.
3. **Dispatch:** list `plan-todo/` and `work-todo/`, drop tasks whose dependencies are not all
   `done` (dependencies, which also fires `dependency_discarded` and `dependency_cycle`) and tasks with
   `not_before` in the future, sort by `priority` (missing last), then file mtime (oldest first),
   then id. While `len(running) < max_concurrent`: fire `route_to_plan` if the task needs a plan
   first (planning, Dispatch rules), then `dispatch_plan` (from `plan-todo/`) or `dispatch_work` (from `work-todo/`),
   and start a worker.

## Worker (one per running task, work stage)

```
ensure_workspace(task)              # workspaces
for turn in 1..max_turns:
    prompt = first_prompt or continuation prompt (prompts)
    result = run_claude(prompt)     # running-claude, resumes session if one exists
    record usage/cost in sidecar; log any permission_denials
    if budget exceeded: -> stuck ("budget exceeded", blocked_cause budget)
    match structured outcome in result (running-claude, Outcome):
      done:
        v = run_validate()          # workspaces, Validation
        if v.ok: -> work-review
        else: next prompt = validate_failed(v.output_tail); continue
      blocked: -> question (blocked_cause question)
      continue / missing: next prompt = continue; continue
max_turns reached -> failure ("max_turns exhausted")
```

Every exit path appends one line to the task's `## Log`, for example:
`- 2026-11-06 21:40 samba: validate passed after 4 turns ($0.83), moved to work-review`.

## Failures and retries

A failure is: Claude process exits non-zero, emits no `result` event, or emits one with
`is_error: true` (running-claude, Reading the stream), turn timeout, stall,
workspace hook failure, prompt render error, or `max_turns` exhausted.

On failure:

1. `attempts += 1`, store `last_error`.
2. If `attempts < max_attempts`: set
   `not_before = now + min(retry_base_s * 2^(attempts-1), max_retry_backoff_s)`, set
   `last_outcome = "retrying"`, move to the todo folder of the task's stage (`last_stage`:
   `plan-todo/` or `work-todo/`).
3. Else (**give up**): if `reflect_on_give_up` is true and a session exists (work stage only), run
   one final short turn with the `give_up` prompt (prompts), ignoring its outcome. Then set
   `last_outcome = "failed"`, `blocked_cause = "gave_up"` and move to `stuck/` with `last_error`.

Moving a task from `question/` or `stuck/` to a todo folder by hand is the observed event
`question.answer` or `task.retry` (states, States), whose effect resets `attempts` to 0. Every move in this
section is a table row fired with `fire`.

