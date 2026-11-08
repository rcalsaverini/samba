# Planning phase (v0.2)

Status: implemented. Details settled during implementation:

- `--exit-when-idle` also waits while `plan-todo/` is non-empty (`plan-review/` is the human's,
  like `work-review/`).
- On approval (`plan.accept`) Samba sets `plan_approved = true`, so a later stop or retry does
  not route the task to planning again.
- Headings `#` and `##` inside `plan`, `assumptions` and the question text are written as `###`, so they cannot be
  mistaken for task sections when the `## Plan` section is replaced.
- A configured `prompts.plan` replaces the default whole (the default is the `WORKFLOW.md` body
  rendered, then the sentence in planning, Prompts); `prompts.plan_revise` replaces the revise prompt.
- The planning variant of the execution protocol lives in `prompts.PLAN_PROTOCOL`; budget caps apply
  to planning like to execution (running-claude, Invocation).
- In `samba task list` the folder name is the STATE column (`plan-running` or `work-running` says
  which stage a running task is in).

## Goal

Let the human review a plan before any code is written, for the tasks where that is worth it.
Planning is **opt-in per task** (or per repo via `require_plan`). Tasks that skip it behave exactly
as in v0. A planning run can read the repository but cannot change anything; the plan comes back as
structured output and Samba writes it into the task file.

## States and flow

The planning stage is the three folders `plan-todo`, `plan-running` and `plan-review` of the layout
in layout and states, States (the same order is used by `STATES` and so by `task list` output). The stage is part of
the folder name, so no sidecar field says "which phase a running task is in".

```
plan-todo ──dispatch──> plan-running ──planned──> plan-review
                           │  ├──blocked──> question
                           │  ├──budget / gave up──> stuck
                           │  └──failure, attempts left──> plan-todo (retry)
plan-review ──human approves: move to work-todo──> work-todo ──> work-running ──> work-review ...
plan-review ──human adds ## Feedback, moves to plan-todo──> plan-todo   (revises the same plan)
```

- Reconcile, stop, shutdown and recovery work per running folder: on recovery or shutdown (the
  `recover` rows) a file in `plan-running/` goes back to `plan-todo/`, and a retry
  (`retry_plan`, `retry_work`) goes back to the todo folder of the same stage.
- Retries of a failed planning run go back to `plan-todo/` (same backoff and `max_attempts` as
  orchestrator, Failures and retries, and the give-up reflection turn is skipped for planning runs). Giving up goes to `stuck/`.

## Dispatch rules

Dispatch candidates come from both `plan-todo/` and `work-todo/`, in one list sorted as in orchestrator, Tick,
limited by the same `max_concurrent`. For each candidate, the stage is decided at dispatch and
stored as `last_stage`:

1. File in `plan-todo/` → `dispatch_plan` (claimed into `plan-running/`).
2. File in `work-todo/`, `planning.require_plan` is true and `plan_approved` is false →
   `route_to_plan` (the task moves to `plan-todo/`), then `dispatch_plan` in the same tick.
3. Otherwise → `dispatch_work` (v0 behavior, claimed into `work-running/`).

Nothing is inferred. Approval is the `plan.accept` row (`plan-review -> work-todo`): it sets
`plan_approved = true` and clears `session_id` (execution starts a fresh session, planning, Executing an approved plan). A move
by hand from `plan-review/` to `work-todo/` is observed as that event (states, States). A task whose plan was
rejected into `plan-todo/` and then moved by hand to `work-todo/` is an illegal move and goes
back to `plan-todo/`.

The attempt reset of orchestrator, Failures and retries (effect of `question.answer` and `task.retry`) also applies to planning.

## The planning run

Same machinery as running-claude (worktree, stream reading, timeouts, cost accounting, budget cap, denials
logged), with these differences:

- **Permissions:** always `--permission-mode dontAsk` and `--allowedTools <planning.allow>`
  (default `Read`, `Grep`, `Glob`), regardless of `claude.permission_mode` and `claude.allow`.
  Verified (implementation-notes, Verified Claude Code behavior): writes are denied, read-only shell commands still run. Do **not** use
  `--permission-mode plan`: it writes files into `~/.claude/plans/` and changes the model.
- **Model:** `--model <planning.model>` if set, else `claude.model`.
- **Session:** its own session id, stored in sidecar `plan_session_id` (separate from
  `session_id`). First planning run: new session with the `plan` prompt. Revision (sidecar has
  `plan_session_id`): `--resume` it with the `plan_revise` prompt. Missing session: start fresh
  with the `plan` prompt, as in running-claude, Invocation.
- **One invocation per dispatch** (no continue loop, no validation).
- **Outcome schema** (passed with `--json-schema`):

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

- **Protocol prompt:** a planning variant of prompts, Protocol prompt (Samba-owned, appended with
  `--append-system-prompt`): you are planning unattended under Samba; you cannot edit files and
  must not try; read whatever you need; return the plan in `plan` as Markdown with the sections
  *Approach*, *Steps* (checkboxes), *Files to change*, *Risks*, *How to verify*, and, if useful,
  *Suggested subtasks*; put non-blocking assumptions in `assumptions` (the human checks them in
  plan review, through `plan accept` or `plan reject`, not through `question`); use outcome
  `blocked` only when the plan cannot be written without answers, and then put the questions in
  the structured `questions` list, as the work agent does (states, Questions).
- **Writing the result** (no agent running at that point, per task-files, Write discipline):
  - Replace the whole `## Plan` section of the task file with `## Plan` followed by `plan`
    (create it if missing, before `## Log` if present, else at the end). Never duplicate it.
  - If `assumptions` is non-empty, replace the `## Assumptions` section the same way.
  - With outcome `blocked`, record the questions and render `## Questions` as in states, Questions.
  - Append a `## Log` line as in orchestrator, Worker, including `summary`.
- **Transitions:** `planned` → `plan-review/`, `last_outcome = "planned"`. `blocked` →
  `question/`, `last_outcome = "blocked"`, `blocked_cause = "question"`, `last_stage` stays
  `plan`. Budget exceeded → `stuck/` (cause `budget`). Missing or invalid structured output, or no `plan` text with outcome
  `planned` → a failure (orchestrator, Failures and retries).

## Prompts

Added to prompts, Built-in defaults defaults and overridable in `prompts:` like the others:

- `plan`: the `WORKFLOW.md` body rendered as usual (prompts, Template rendering), followed by: "Do not implement anything
  yet. Produce a plan for this task."
- `plan_revise`: "The human reviewed your plan and left feedback in your task file at
  {{ task.path }} (see `## Feedback`). Re-read it and return a revised plan."

## Executing an approved plan

- Execution after approval starts a **new** session (planning, Dispatch rules rule 2). The plan must stand on its own;
  if a fresh session cannot follow it, the plan was incomplete.
- When `plan_approved` is true, the execution protocol prompt (prompts, Protocol prompt) gets one extra rule: "An
  approved plan is in the `## Plan` section of your task file. Follow it. If you must deviate,
  record what and why in `## Log`. Tick the plan's checkboxes as you complete steps."
- Everything else is v0 behavior (continue loop, validation, `work-review`).
- Rework from `work-review/` (move to `work-todo/`) keeps `plan_approved = true` and resumes the execution
  session, as in v0.

## Config

Added to workflow-config, Config:

```yaml
planning:
  require_plan: false         # true: work-todo/ tasks are planned (and reviewed) before execution
  model: null                 # defaults to claude.model
  allow: ["Read", "Grep", "Glob"]
```

## Sidecar and status

- Planning sidecar fields: `plan_session_id` (string or null), `plan_approved` (bool, default
  false), plus `last_stage` and `blocked_cause` (states, Sidecar state). The former `phase` field is gone: the
  running folder says which stage a task is in. Old sidecars load with defaults and their `phase`
  is ignored.
- `samba task list` shows the folder name as the state of each task (observability).
- `samba task new` creates the task in `plan-todo/`; `--skip-plan` uses `work-todo/` instead.

## Fake claude additions

`tests/fake_claude.py` step fields: `plan` (string, put in `structured_output.plan`),
`assumptions` (string, planning runs). For work and planning runs `questions` is a list of
`{text, context}` put in `structured_output.questions`. For planning runs the fake emits `outcome` as given (`planned` or
`blocked`). Keep it standard-library only.

## Black-box tests to add

All in the style of `tests/test_blackbox.py` (CLI subprocess, assert on files and recorded calls):

1. A task in `plan-todo/` ends in `plan-review/` with the plan text under `## Plan`; the call used
   `--permission-mode dontAsk`, `--allowedTools` exactly `planning.allow`, a schema whose outcome
   enum is `["planned", "blocked"]`, and no execution-only flags' values (no `Edit` in the allow
   list); no commits were added to `samba/<id>`.
2. Approval: moving it to `work-todo/` runs execution with a **new** `--session-id` (not the plan
   session), the system prompt mentions the approved plan, and it ends in `work-review/`.
3. Rejection: adding `## Feedback` and moving it to `plan-todo/` resumes `plan_session_id` with the
   revise prompt; afterwards the task file has exactly one `## Plan` section, containing the
   revised plan.
4. `planning.require_plan: true`: a task in `work-todo/` goes to `plan-review/` first, then
   executes after approval.
5. Default config: a task in `work-todo/` executes directly (no planning call).
6. Planner `blocked` with `questions`: task in `question/` with `last_stage: "plan"`, open
   question records with `stage: "plan"`, `## Questions` renders them; answering them with
   `question answer` (or moving the task back to `plan-todo/`) replans with attempts reset. A plan
   with `assumptions` renders `## Assumptions` and no `## Questions`.
7. Planner failure then success: retried from `plan-todo/`, ends in `plan-review/`; with
   `max_attempts: 1` it ends in `stuck/` and no give-up reflection call is made.
8. `planning.model` is passed as `--model` for planning and `claude.model` for execution.
9. Recovery: a task in `plan-running/` at startup is re-planned from `plan-todo/`, not executed.
10. Moving a task out of `plan-running/` to `discarded/` (or `plan-todo/`) during planning stops
    the planner (as in v0); any other target is an illegal move (states, States).
11. `samba task new` creates the file in `plan-todo/` (`--skip-plan`: `work-todo/`).

Layout tests (`tests/test_layout.py`): question versus stuck routing and `blocked_cause`,
`done` versus `discarded` (worktree removed, branch kept), `last_stage` routing of retries,
shutdown and recovery, the old-folder startup refusal, and loading an old sidecar.

Transition tests (`tests/test_transitions.py`): one parametrized test per table row, a test that
every row of `samba dev transitions` has a scenario, the states chapter table drift check, and illegal hand
moves. Dependency tests: `tests/test_dependencies.py` (dependencies).

All existing tests must keep passing; `uv run pyright` must stay at 0 errors. Tests that moved a
running task to `done` by hand now move it to `discarded` (the only legal target besides the todo
folder, states, States).

