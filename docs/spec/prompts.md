# Prompts

## Template rendering

`{{ name }}` substitution only. Unknown variables are an error (fails the attempt). Variables:

- `task.id`, `task.title`, `task.body` (file content without front matter), `task.path` (absolute
  path of the task file, in the running folder of the current stage: `work-running/` or
  `plan-running/`)
- `task.ref`: a short phrase that names the task inside a sentence, in the words of the task store
  (the markdown store says `your task file at <path>`; Task and workspace below)
- `workspace`, `branch`, `base_branch`
- `task_briefing`, `workspace_briefing`: what the task store and the VCS tell the agent about the
  task and the workspace (Task and workspace below). The adapters are asked once per run, when its
  prompts are built. `task_briefing` is the planning text, where the agent cannot edit, for a
  planning run.
- `attempt` (0 on first run, otherwise number of previous failures)
- `validate_command` (empty string if none)
- `questions`: the latest question round as pairs (`q1 (answered): text` then `Answer: ...`;
  dismissed ones say so), filled only for the first run after a `blocked` outcome whose questions
  are all closed; empty otherwise. A custom `prompts.resume` or `prompts.plan_revise` that does not
  mention `{{ questions }}` gets the block appended, so answers are never lost.

## Which prompt is sent

| Situation                                        | Prompt                                   | Session          |
|--------------------------------------------------|------------------------------------------|------------------|
| First run, no session                            | `WORKFLOW.md` body                       | new              |
| Later turn in same worker run                    | `continue`                               | resume           |
| Agent said DONE, validation failed               | `validate_failed` (+ output tail)        | resume           |
| New worker run, session exists (retry, rework, answered question) | `resume`                | resume           |
| Resume fails (session not found)                 | `WORKFLOW.md` body                       | new              |
| Giving up                                        | `give_up`                                | resume           |
| Planning run, no plan session (running-claude, Planning run) | `plan`                            | new (plan session) |
| Planning run, plan session exists (revision)     | `plan_revise`                            | resume (plan session) |

## Built-in defaults

- `continue`: "Continue working on the task. Re-read {{ task.ref }} if needed and keep your plan
  and log up to date."
- `validate_failed`: "You reported done, but `{{ validate_command }}` failed. Last lines of output
  are below. Fix the problem, then report done again.\n\n{output}"
- `resume`: "You are resuming work on this task. Re-read {{ task.ref }}, especially your feedback
  and anything the human added, then continue.\n\n{{ questions }}"
- `plan`: the `WORKFLOW.md` body rendered as usual (Template rendering above), followed by: "Do not
  implement anything yet. Produce a plan for this task." A configured `prompts.plan` replaces this
  default whole.
- `plan_revise`: "The human reviewed your plan and left feedback in {{ task.ref }} (see your
  feedback). Re-read it and return a revised plan." It ends with the same `{{ questions }}`. A
  configured `prompts.plan_revise` replaces it.
- `give_up`: "This task is being stopped after repeated failures. Do not try to fix it. In
  {{ task.ref }}, add a new section titled "Harness gaps" and write what was missing that would
  have let you succeed: tools, docs, test fixtures, permissions, unclear requirements. Be
  specific."

The built-in prompts name no file, folder, heading or branch: they say "your task", "your plan",
"your log" and "your feedback", and `{{ task.ref }}` where the sentence needs a place. A
`WORKFLOW.md` body or an override that uses `{{ task.path }}` or `{{ branch }}` ties itself to
the store and the VCS it was written for; that is the repository's choice (ADR 0020).

## What the WORKFLOW.md body should tell the agent

This is guidance for writing the template, not code. The protocol (prompts, Protocol prompt) is already injected, so
the body does not need to repeat the outcome format or the rules about the task. A good first prompt:

- States the task: title and body.
- Points to the repo's map (`CLAUDE.md`, `docs/`) rather than repeating it.
- Describes how this repo wants work done: commit granularity, testing expectations, what "done"
  means beyond `{{ validate_command }}`, when to ask instead of guess.
- Keeps the spec step: edit the spec chapters listed in the plan's Spec changes section before
  reporting done, and propose an ADR for a real decision. The protocol prompt carries the generic
  rule and never names a path (it goes to every repo that uses Samba, and says "the project's
  spec"); only the body names where the spec lives, for example `docs/spec/` and its README.

## Task and workspace: who says what

The protocol is written in the vocabulary of the domain: "your task", "your plan", "your log",
"your feedback", "your workspace". Where those live and how to work with them depends on the
technology, so each adapter contributes its own words through the port it implements (ADR 0020;
architecture, Ports). `domain/prompts.py` keeps what Samba's logic depends on: the outcome schema
and what `done`, `blocked`, `continue` and `planned` mean, that questions go in the structured
answer, that the agent keeps a plan and a log as its memory, the denial rule, the spec step, the
ADR step and the approved-plan rule.

| Variable | Port call | Markdown store and git say |
|---|---|---|
| `task_briefing` | `Tasks.briefing(id, writable)` | the task file's absolute path; edit only this one among the files in the tasks folder; the plan is its `## Plan` section, the log its `## Log`, the human's feedback is in `## Feedback`; Samba owns `## Questions`. For a planning run (`writable` false): the path and that the agent cannot edit files |
| `task.ref` | `Tasks.reference(id)` | `your task file at <path>` |
| `task.path` | `Tasks.location(id)` | the absolute path, as before |
| `workspace_briefing` | `Vcs.briefing(task_id)` | work only inside the current directory, on the task's branch; commit there without asking and in small steps; never push, merge, rebase onto other branches or delete branches |
| `branch` | `Vcs.branch_name(task_id)` | the branch name, as before |

The wording of the markdown briefing lives in `adapters/markdown_tasks.py` (task-files, The agent's
briefing) and the git wording in `adapters/git_vcs.py`. A new store or VCS writes its own. A
component test pins the rendered protocol over the fakes; an integration test shows that with the
markdown store and git the agent reads the same text as before the move, except the listed
sentences.

## Protocol prompt (Samba-owned)

Rules that Samba's own logic depends on are not left to `WORKFLOW.md`. Samba appends them to
the system prompt of every run with `--append-system-prompt`. They cannot be overridden by the
workflow. Content (rendered with the same variables as prompts, Template rendering):

- You are running unattended under Samba. No human sees this conversation; the human reads your
  task and your work.
- `{{ task_briefing }}`: where your task is and how to edit it, from the task store.
- Keep your plan (checkbox steps) and your log (decisions, progress) up to date. They are your
  memory across sessions.
- `{{ workspace_briefing }}`: where your work lives and what you may and may not do with it, from
  the VCS. In git (Task and workspace below) it says: **you are authorized to commit your work
  without asking; commit in small steps.** The explicit authorization is required: Claude Code's
  built-in system prompt tells the agent to commit only when the user asks (verified in
  running-claude, Verified Claude Code behavior).
- These rules take precedence over any instruction to ask the user for confirmation before acting.
- If you need a decision from the human, report outcome `blocked` and put each question in
  `questions` of the final answer (`text` and `context`). Never record the questions yourself:
  Samba does (task-files, Write discipline). Do not guess on important ambiguity.
- The tools you may use (rendered from `claude.allow`). Run allowed shell commands as plain single
  commands, without pipes, `;`, `&&`, `||` or redirections: allow rules match the whole command
  line, so a combined command is denied. (Smoke test: the agent piped the allowed test command into
  `tail` and chained `git status`, and was denied.)
- If a tool call is denied, do not try to get around the denial. Note it in your log and, if it
  stops you, report `blocked`.
- After your work, the system runs `{{ validate_command }}` (if set). Run it yourself first when you
  can; if you cannot, still report `done` once the work is complete, because the system validates
  it. (Smoke test: without this, the agent reported `blocked` when it could not run the validator.)
- Spec step: before reporting `done`, make the edits to the project's spec that the task
  requires, in your workspace, and say in your log what changed in the spec (or why nothing
  did). The human reviews
  the spec diff next to the code diff at `work accept`.
- If the task made a real decision (a choice between alternatives with a lasting reason), also add
  a proposed ADR in `docs/adr/`: one decision per file, status `proposed`, in the format of
  the project's first ADR (`samba adr show 1`). Nothing checks this prose; the review does.
- Decisions that shape the architecture live in `docs/adr/`: before designing, run
  `samba adr list` and read the relevant ones with `samba adr show N` (ADR 0003; cli, `adr`).
  The default allow lists have these two commands, so they work without extra config.
- Your final answer is structured output (running-claude, Outcome): `outcome` is `done`, `blocked` or `continue`, and
  `summary` is one or two sentences.

### Planning variant

A planning run (running-claude, Planning run) gets a variant of the protocol prompt, also
Samba-owned and appended with `--append-system-prompt` (`prompts.PLAN_PROTOCOL` in code; the same
budget caps apply). Content: you are planning unattended under Samba; `{{ task_briefing }}` in its
planning form, which says it cannot edit files and must not try; read whatever you need; return
the plan in `plan` as Markdown with the sections
*Approach*, *Steps* (checkboxes), *Files to change*, *Spec changes* (the parts of the project's
spec the task will change with one line of intent each, or "none, because ..."), *Risks*, *How to verify*,
and, if useful, *Suggested subtasks*; put non-blocking assumptions in `assumptions` (the human checks them in
plan review, through `plan accept` or `plan reject`, not through `question`); use outcome
`blocked` only when the plan cannot be written without answers, and then put the questions in the
structured `questions` list, as the work agent does (states, Questions). It carries the same
ADR paragraph as the protocol prompt, and the default `planning.allow` has the two read commands
so the planner can follow it.

### Executing an approved plan

Execution after approval starts a **new** session (states, States: `plan.accept` clears
`session_id`). The plan must stand on its own; if a fresh session cannot follow it, the plan was
incomplete. When `plan_approved` is true, the execution protocol prompt gets one extra rule: "You
have an approved plan. Follow it. If you must deviate, record what and why in your log. Tick the
plan's checkboxes as you complete steps. Its "Spec changes" section lists the spec edits you
owe." Everything
else is as for any work run (continue loop, validation, `work-review`). Rework from `work-review/`
keeps `plan_approved = true` and resumes the execution session.

## Explore guide

`samba explore` appends this text (`EXPLORE_GUIDE` in `domain/prompts.py`, fixed, not configurable) to the
system prompt of the interactive session (cli, explore). It is not the headless protocol prompt.
Sections:

- **Role:** an interactive exploration with the human; the output is decisions as ADRs, not code.
- **Writing ADRs:** start with `samba adr list --all` and `samba adr show N`; one decision per ADR,
  split a draft that holds two; write `docs/adr/NNNN-short-title.md`, the number taken from the
  filename (the next free one); format of the project's first ADR (`samba adr show 1`),
  with `status: proposed`, `date` and `supersedes: []`, then Context, Decision and Consequences; never
  edit an accepted ADR, write a superseding one; never accept, reject or supersede.
- **Background research:** subagents inside the chat; `samba task new` only for work that must
  outlive the chat, read with `samba task show`, nothing merged, findings worth keeping go into an
  ADR; the commands the human keeps (plan, work, task discard, stop, retry, question answer, adr
  accept, reject, supersede) may not be run.
- **Reporting:** when a task is spawned, say which one and why; at the end of the session, list
  every spawned task again with its reason (ADR 0004).

## Where the agent's context comes from

| Layer | Owner | Delivered by |
|---|---|---|
| Protocol: outcome format, plan and log duties, task and workspace instructions | Samba | `--append-system-prompt` (prompts, Protocol prompt) and `--json-schema` (running-claude, Outcome), every run |
| Policy: how this repo wants tasks done | Repo, `WORKFLOW.md` body | First-turn prompt (prompts, Which prompt is sent) |
| Permissions: what the agent may run | Repo, `WORKFLOW.md` `claude.allow` | `--allowedTools` (workflow-config, Permissions) |
| Knowledge: architecture, conventions, how-to skills | Repo, `CLAUDE.md`, `docs/`, `.claude/skills/` | Loaded natively by Claude Code from the worktree |
| Personal config: `~/.claude/` | User | Mostly excluded when `isolate_user_config` is true (running-claude, User config isolation) |
| Org-managed plugins and policy | Administrator | Always loaded; cannot and should not be excluded |

Notes:

- The worktree is a checkout of the task branch, so the agent sees repo skills and rules as committed
  on `base_branch` (plus its own commits). Uncommitted edits in the main checkout are not visible.
- Samba ships no skills of its own in v0. Anything repo-specific belongs in the repo, versioned.

