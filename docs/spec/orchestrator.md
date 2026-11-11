# Orchestrator loop

Who owns what (ADR 0015; the `architecture` chapter, Orchestrator parts): `Startup`
(`app/startup.py`) owns the startup checks and the recovery, `Tick` (`app/tick.py`) the tick,
`RunTask` (`app/run_task.py`, with `PromptBuilder` and `Finisher`) the run of one task and the
retry, reflect or give-up decision, and `Guard` the external transition guards. `Workers`
(`entrypoints/workers.py`) owns the asyncio workers: spawn, what happens to a cancelled worker
and shutdown. The `Orchestrator` (`entrypoints/orchestrator.py`) only wires the parts and runs the
poll loop. The behavior below does not change.

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
   `done` (below, Dependencies, which also fires `dependency_discarded` and `dependency_cycle`) and
   tasks with `not_before` in the future, sort by `priority` (missing last), then `queued_at` (oldest
   first; set when the task entered its todo status, states, Task fields and how the markdown adapter stores them), then id. Both folders form one list, limited by the same `max_concurrent`. While
   `len(running) < max_concurrent`, decide the stage of each candidate (stored as `last_stage` by
   the dispatch row) and start a worker:
   1. File in `plan-todo/`: `dispatch_plan` (claimed into `plan-running/`).
   2. File in `work-todo/`, `planning.require_plan` is true and `plan_approved` is false:
      `route_to_plan` (the task moves to `plan-todo/`), then `dispatch_plan` in the same tick.
   3. Otherwise: `dispatch_work` (claimed into `work-running/`).

   Nothing is inferred: approval is the `plan.accept` row (states, States). A task whose plan was
   rejected into `plan-todo/` and then moved by hand to `work-todo/` is an illegal move and goes
   back to `plan-todo/`.

### Dependencies

A task with `depends_on` (task-files, Format) is dispatched only when the `deps_met` guard holds
(states, States). Evaluated in step 3:

- **Waiting:** while any id is in another folder (including `plan-todo/`, `work-todo/`, a review
  folder, `question/`, `stuck/`) the task is simply not a dispatch candidate. It does not count
  toward `max_concurrent`.
- **Unknown id** (no task file in any folder): treated as unmet, and a warning
  `event=unknown_dependency task=<id> dependency=<id>` goes to `samba.log` once per pair.
- **A dependency in `discarded/`:** the dependent task fires `dependency_discarded` and goes to
  `stuck/` with `blocked_cause = dependency_discarded` (its `## Log` names the ids). Sending it back
  by hand (`task.retry`) checks the dependencies again.
- **A dependency cycle** (a task that can reach itself through `depends_on` edges of tasks that are
  not `done`, a self-dependency included): every task in the cycle fires `dependency_cycle` and
  goes to `stuck/` with `blocked_cause = dependency_cycle`. A task that only depends on a cycle
  keeps waiting.
- **`--exit-when-idle`** (cli): a todo task held only by dependencies does not keep the run alive,
  and neither does one in `plan-review/` or `work-review/` (those are the human's). A dependency
  that is itself runnable in a todo folder does keep it alive.
- `samba task list` shows `waiting on <id>[, <id>...]` for a task held only by dependencies
  (observability).

## Worker (one per running task)

```
ensure_workspace(task)              # workspaces
for turn in 1..max_turns:
    if budget exceeded: -> stuck ("budget exceeded", blocked_cause budget)   # before every turn, the first included
    prompt = first_prompt or continuation prompt (prompts)
    result = agent.run(request)     # running-claude, resumes session if one exists; returns an AgentReport
    record usage/cost in sidecar; log any permission_denials
    if result.failure: -> failure path (below)      # a failure wins over the budget check
    if budget exceeded: -> stuck ("budget exceeded", blocked_cause budget)   # the log line carries the run summary
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

The rules of this loop (budget, retry delay, what happens after a turn) are pure domain code in
`domain/policy.py`; the loop itself is the use case `app/turn.py`, shared by work and planning
(architecture).

A task dispatched into `plan-running/` gets a planning worker instead: one invocation, no continue
loop and no validation (running-claude, Planning run). Its exits are `planned`, `plan_blocked`,
`budget` and the failure paths below, and each appends a `## Log` line including the run summary.

## Failures and retries

A failure is: Claude process exits non-zero, emits no `result` event, or emits one with
`is_error: true` (running-claude, Reading the stream), turn timeout, stall,
workspace hook failure, prompt render error, or `max_turns` exhausted.

On failure:

1. `attempts += 1`, store `last_error`.
2. If `attempts < max_attempts`: set
   `not_before = now + min(retry_base_s * 2^(attempts-1), max_retry_backoff_s)`, set
   `last_outcome = "retrying"`, move to the todo folder of the task's stage (`last_stage`:
   `plan-todo/` or `work-todo/`). Planning runs retry with the same backoff and `max_attempts`.
3. Else (**give up**): if `reflect_on_give_up` is true, a session exists and the task file is still
   in its running folder (work stage only; the reflection turn is skipped for planning runs), run
   one final short turn with the `give_up` prompt (prompts), ignoring its outcome. Then set
   `last_outcome = "failed"`, `blocked_cause = "gave_up"` and move to `stuck/` with `last_error`.

Moving a task from `question/` or `stuck/` to a todo folder by hand is the observed event
`question.answer` or `task.retry` (states, States), whose effect resets `attempts` to 0. Every move in this
section is a table row fired with `fire`.

