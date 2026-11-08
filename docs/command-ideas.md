# Symphony command ideas

Status: exploration, for human sign-off. No code, tests or SPEC changed by this document. Proposed
SPEC wording is included where useful; follow-up tasks edit `SPEC.md`.

Criteria used throughout: barebones generic scope, black-box testable (files and fake `claude`
calls only), portable to the expected Rust rewrite, small.

Note on sources: facts about the code and SPEC were checked against the repo on 2026-11-06. The
FSM library facts (section 4) are **unverified, from memory**: WebSearch was denied in the session
that wrote this. Re-check versions and maintenance status before relying on them.

## 1. Context: today's CLI

Three commands (SPEC §11): `run`, `status`, `new "Title" [--priority N] [--plan]`. Everything else
the human does is a file operation: `mv` between state folders, editing `## Feedback`, `git diff`,
`git merge`, `git worktree remove`, reading `runs/` and `symphony.log`.

Manual work, by how often it happens:

| Manual step today | Frequency | Pain |
|---|---|---|
| Approve a plan: `mv plan-review/x.md todo/` | every planned task | must remember the folder names; no check |
| Accept work: `git merge symphony/x` in the main checkout, then `mv review/x.md done/` | every task | two steps, order matters, easy to forget the move (worktree stays) |
| Reject with feedback: edit `## Feedback`, then `mv` to `plan/` or `todo/` | common | right folder depends on the state; section may be missing |
| Answer a question: edit the file, `mv blocked/x.md todo/` | common | which folder: `todo` or `plan` depends on the phase |
| Retry a gave-up task | occasional | same `mv`, but the cause is unclear from the folder alone |
| Find a task and its state | constant | `status` prints everything, no filter, no prefix match |
| See what the agent did: `git diff main...symphony/x`, find the worktree path | every review | branch and path are conventions the human must know |
| Read why it failed: `runs/<id>/*.jsonl`, `validate-N.log` | on failures | paths and raw JSONL |
| Remove branches and sidecars of finished tasks | occasional | nothing deletes branches (SPEC §7.4) |
| Check setup (git, claude login, WORKFLOW.md valid, validate command works) | once per repo | failures show up only at `run` |

## 2. Artifact inventory (drives the nouns)

Every thing Symphony creates or owns, verified against `tasks.py`, `orchestrator.py`, `workspace.py`
and SPEC §2, §4, §14:

| Artifact | Where | Writer | Lifecycle | Human verbs today |
|---|---|---|---|---|
| **Task** | `tasks/<state>/<id>.md`: front matter (`priority`), `# Title`, body | human (`new`), Symphony moves it | until `done` or deleted | create, edit, prioritize, list (`status`), discard (move to `done`/delete) |
| **Plan** | `## Plan` section; sidecar `plan_session_id`, `plan_approved`, `last_outcome=planned` | agent (via Symphony, replaced whole on each revision) | exists once planning ran; approved by the move `plan-review` to `todo` | read, approve, reject |
| **Feedback** | `## Feedback` section | human | attached to a plan or to finished work, consumed by the next run | add |
| **Question** | `## Questions` section; task sits in `blocked/` | agent | until the human answers and moves it | read, answer |
| **Work** | branch `symphony/<id>` plus worktree `~/.symphony/workspaces/<key>/<id>`; in state `review` it passed validation | agent commits | worktree removed when the task reaches `done` or is deleted; branch is never deleted | diff, merge, reject, remove branch |
| **Run** | `runs/<id>/<n>.jsonl`, `validate-<n>.log` | Symphony | append only, never cleaned | read |
| **Sidecar** | `state/<id>.json`: attempts, `not_before`, `last_error`, `last_outcome`, `phase`, session ids, cost, branch, workspace | Symphony only | lives forever | read (via `status`), implicit resets |
| **Log** | task `## Log` section; `symphony.log` | Symphony (and agent) | append only | read |
| **Session** | Claude session ids inside the sidecar | Symphony | `session_id` cleared on plan approval | none |

### 2.1 Finding: three review artifacts

The human's decisions are made on three things the agent produced that wait for a verdict:

| Artifact waiting | State | Verdicts available |
|---|---|---|
| **Plan** | `plan-review` | accept (to `todo`), reject with feedback (to `plan`) |
| **Work** (branch and diff) | `review` | accept (merge, then `done`), reject with feedback (to `todo`) |
| **Question** (or gave-up report) | `blocked` | answer (to `todo` or `plan`), retry, discard |

Accept and reject are the same pattern on the first two. Blocked is different: it holds several
causes with different verdicts (section 3).

### 2.2 Candidate nouns, tested

| Noun | Real object? | Clash with state folders? | Makes dangerous verbs self-describing? | Verdict |
|---|---|---|---|---|
| `task` | yes, the file | no | n/a (create, edit, list, show, prio, discard, stop) | keep |
| `plan` | yes, `## Plan` section and plan session | partial: folders `plan` (to be planned) and `plan-review` | `plan accept` can never merge, which is good | keep, but document that `plan accept` acts on a task in `plan-review`, not `plan/` |
| `review` | state name, not an object | clash: `review` is a folder and the verb target | `review accept` reads as "accept the review", and it merges | acceptable, but `work` is the real object |
| `work` | yes, branch plus worktree | no | `work accept` merges: the noun says what is merged | **preferred**: noun is the artifact, state names stay state names |
| `branch` | yes, but too git specific | no | `branch accept` is odd | reject |
| `question` | yes, `## Questions` | no | `question answer` is natural | keep |
| `blocker`, `blocked` | state name | clash with folder | weak | reject |

Proposed noun set: **`task`, `plan`, `work`, `question`**. A decision for the human: `work` versus
`review`. This document uses `work`; swapping is a rename in the catalogue only.

### 2.3 Where `answer | retry | discard` live

`blocked` is a state, not an artifact, so it should not be a noun ("perhaps neither `blocked` nor
`task`"). The code shows the causes (`orchestrator.py`):

| Cause | Sidecar today | Human verdict |
|---|---|---|
| Agent asked a question | `last_outcome="blocked"`, `## Questions` filled | `question answer` |
| Planner asked a question | same, `phase="plan"` | `question answer` (goes back to `plan`) |
| Budget exceeded | `last_outcome="blocked"` (same as a question), Log line "budget exceeded" | raise the cap, then retry |
| Gave up after `max_attempts` | `last_outcome="failed"`, `last_error` set, `## Harness gaps` written | fix the harness, then retry, or discard |
| Not yet distinguished | budget versus question share `last_outcome="blocked"` | needs a cause field (section 3) |

So the placement is: **`question answer`** for agent questions (it is the only verb that needs
text), and the generic task verbs **`task retry`** and **`task discard`** for gave-up, budget, and
anything else. `retry` applies to any state in `blocked` (and `review` as "send back without
feedback"); it is not specific to `blocked`. `question answer` is sugar for "append answer to the
task (as `## Feedback`) and retry", so `answer` and `retry` share one transition.

`list` and `show` are queries over the Task noun: canonical form `symphony task list [STATE]` and
`symphony task show <id>`, with top-level `list` and `show` as short aliases (a Rust rewrite can
keep both). Decision for the human: only the short forms, or both.

## 3. Critique of the current state model

### 3.1 What exists (from the code, not only the SPEC diagram)

Complete transition list. "who" is human (H) or Symphony (S).

| # | From | To | Who | Trigger | Side effects in sidecar |
|---|---|---|---|---|---|
| 1 | (none) | `todo` or `plan` | H | `new` (`--plan`) | none |
| 2 | `todo`/`plan` | `running` | S | dispatch | `phase` set; `attempts=0` if `last_outcome` in blocked/failed; `last_outcome=approved`, `plan_approved`, `session_id=None` if it was `planned` |
| 3 | `running` | `plan-review` | S | planner outcome `planned` | `last_outcome=planned`, `attempts=0` |
| 4 | `running` | `review` | S | done and validation ok | `last_outcome=done`, `attempts=0` |
| 5 | `running` | `blocked` | S | outcome blocked, budget exceeded | `last_outcome=blocked` |
| 6 | `running` | `blocked` | S | give up after `max_attempts` | `last_outcome=failed` |
| 7 | `running` | `todo`/`plan` (origin) | S | failure with attempts left | `last_outcome=retrying`, `not_before` |
| 8 | `running` | `todo`/`plan` (origin) | S | startup recovery, shutdown | none |
| 9 | `running` | any | H | move, agent is killed (reconcile) | none |
| 10 | `plan-review` | `todo` | H | approve | detected at next dispatch via `last_outcome==planned` |
| 11 | `plan-review` | `plan` | H | reject (after writing `## Feedback`) | none |
| 12 | `review` | `todo` | H | rework (after `## Feedback`) | none |
| 13 | `blocked` | `todo`/`plan` | H | answer or retry | `attempts` reset at dispatch if `last_outcome` blocked/failed |
| 14 | `review` | `done` | H | accept (merge is manual, outside Symphony) | worktree removed by the tick |
| 15 | any | `done` | H | abandon | worktree removed by the tick |
| 16 | any | (deleted) | H | file deleted, same as `done` | |

Observations:

1. **Two axes in one folder name.** The state is really stage (plan or execute) crossed with status
   (queued, running, awaiting human, finished): `plan`=plan/queued, `plan-review`=plan/awaiting
   human, `todo`=execute/queued, `review`=execute/awaiting human. `running` is shared and needs
   sidecar `phase` to say which stage. The folders are a good human interface, but the model is
   implicit.
2. **Implicit events.** Rows 10 and 13 are human moves whose meaning is inferred later from sidecar
   side effects at dispatch (`last_outcome==planned` means approved; `blocked`/`failed` means
   reset attempts). An explicit command can do these effects at the moment of the event, which
   removes the inference and makes the table testable. Row 12 versus row 13 differ only in cause.
3. **`blocked` conflates causes** (question, planner question, budget, gave up). `last_outcome` splits
   gave-up (`failed`) from the rest, but not question from budget. The dispatch attempt reset
   treats them all the same, which is right, but a human reading `status` cannot tell "answer me"
   from "raise the budget".
4. **`done` conflates accepted and abandoned.** Both clean the worktree. The distinction matters for
   `work accept` (merge) versus `task discard` (nothing merged), and for any later `clean` that
   might delete branches: merged branches are safe to delete, abandoned ones are not.
5. **Missing or implicit states:** "approved but not yet dispatched" is only visible as `todo` with
   `last_outcome==planned`; "retry waiting" is `todo` with a future `not_before` (shown by `status`
   only); no paused or held state (a human who wants to park a task has no way except leaving it
   in `blocked` or removing it).
6. **Rework loops are one pattern:** reject-with-feedback from `plan-review` (to `plan`) and from
   `review` (to `todo`) are the same event on different artifacts.

### 3.2 Options

| Option | Change | Cost | Benefit |
|---|---|---|---|
| A. Keep folders, make events explicit | Declarative transition table in code; commands perform side effects at event time; add sidecar `blocked_cause` and `resolution` (`accepted` or `discarded`) set when entering `blocked` and `done` | small: sidecar fields only, no folder rename, existing black-box tests unchanged | fixes observations 2, 3, 4; `status` gains a cause column |
| B. Stage x status folders (revised, see 3.3) | one folder per (stage, status) pair, `running` split by stage, `blocked` split by verdict needed, `done` split by resolution | mechanical but wide: `STATES`, `orchestrator.py` folder literals, SPEC §2, §4.1, §14, the folder names in `test_blackbox.py` (a rename pass), and a one-time `mv` of the human's existing task files. Not a rewrite of logic | removes the `phase` inference and most sidecar tricks; folder name says what the human must do |
| C. Add only `discarded` and `approved` (and maybe `paused`) | three more folders on top of today's layout | medium, about the same touch points as B for less gain | fixes `done` and approval, leaves the shared `running` and the `blocked` mix |

Revision after human feedback (round 2): the first version of this document recommended A and
priced B as "large" because of user-visible layout, test assertions and muscle memory. That
weighed the cost wrongly. There is one user, the project is pre-release, and the test change is a
mechanical rename. The honest cost of B is a day-sized refactor, paid once, and it is cheapest now
and most expensive after the Rust rewrite or a second user. The right question is which model is
saner, and the SPEC should follow it.

### 3.3 Recommendation

**Option B, with restraint. Option A's explicit table and sidecar cause field come with it.**
My answer to "if there is a better model, go with it": yes. The cost argument I made does not
hold for a single-user, pre-release tool, and the defects in 3.1 trace to one cause: the folder
set does not carry the information the machine needs, so the code infers it from sidecar side
effects. Fix the model, and the code gets simpler, not more complex.

The principle: **a folder name is a complete state, and tells the human what is expected of them.**
Stage (plan or work) and status (todo, running, review) become visible and orthogonal in the name,
and a state that needs a different human verdict gets its own folder.

Proposed layout (ten folders; the stage prefix matches the nouns `plan` and `work`):

| Folder | Meaning | Human verdict expected |
|---|---|---|
| `plan-todo` | queued for planning | none (maybe edit) |
| `plan-running` | planner running | none |
| `plan-review` | plan written | `plan accept` or `plan reject` |
| `work-todo` | queued for execution (new, approved, rework, retry) | none |
| `work-running` | executor running | none |
| `work-review` | validation passed, branch ready | `work accept` or `work reject` |
| `question` | agent (or planner) asked something | `question answer` |
| `stuck` | gave up or budget exceeded; `blocked_cause` says which | `task retry` or `task discard` |
| `done` | accepted (merged); terminal | none |
| `discarded` | abandoned; terminal | none |

What this removes or fixes:

- `phase` stops being sidecar state: the folder is the phase. Recovery and shutdown return
  `plan-running` to `plan-todo` and `work-running` to `work-todo` with no lookup. `running` is no
  longer shared (observation 1).
- Approval is the table row `plan-review -> work-todo`; its effects (`plan_approved`, clear
  `session_id`) belong to that row, not to a dispatch-time guess on `last_outcome`. The `planned`
  and `approved` values of `last_outcome` become unnecessary (observation 2).
- `question` and `stuck` separate "answer me" from "fix the harness or raise the budget"
  (observation 3). Attempts reset is an effect of the retry and answer rows.
- `done` and `discarded` separate merged from abandoned, so `clean` and `work accept` have a clear
  contract (observation 4). A discarded task keeps its branch until `clean`.
- `require_plan` becomes a rule on `new`, plus a table row `work-todo -> plan-todo` for a
  hand-created task with no approved plan, instead of a dispatch branch (observation 5).
- Retry waiting stays `work-todo` or `plan-todo` with a future `not_before`; no extra folder.

Where I hold back, deliberately:

- No `paused` and no `approved` folder: `work-todo` with `plan_approved` already means approved and
  queued. Add `paused` when real use asks.
- No nested directories (`plan/review/`): flat names list well with `ls` and the one-level
  `TaskStore`.
- `todo`, `review` and `blocked` are renamed, not kept, because a bare `review` would be ambiguous
  between plan and work once the pairs exist.

Hand moves in the file browser stay supported, through the same table. The sidecar records the last
known `state`; on each tick a file found in a different folder is looked up as
`(last state, folder)`. A row that exists is an observed event and its effects are applied; a pair
not in the table is logged as an illegal move and the file is moved back. This replaces the ad hoc
inference with one rule and keeps SPEC §1's "steer with a file browser" principle.

Cost of the change, now:

- `tasks.py`: `State`, `STATES`. `orchestrator.py`: folder literals in dispatch, recovery,
  reconcile, cleanup; remove the `phase` and `last_outcome` inference.
- SPEC §2, §4.1, §4.2, §5.1, §5.4, §10, §11, §14.2, §14.3, §14.8, updated in the same task.
- `tests/test_blackbox.py` and `conftest.py`: a rename pass for folder names, plus the new
  parametrized per-row test. The fake claude is unaffected.
- The human's own repos: task files in old folders. A startup message listing old folders that
  still hold files (a `mv` recipe in the task Log) is enough for one user.
- The Rust rewrite inherits the clean layout instead of a legacy one: the strongest argument for
  doing this before the rewrite.

Sidecar: add `blocked_cause` (`question | budget | gave_up`, set when entering `question` or
`stuck`) and `state` (last known folder, for observed hand moves); remove `phase`; drop the
`planned` and `approved` values of `last_outcome`. No `resolution` field is needed, the folder is
the resolution. Old sidecars load with defaults (SPEC §4.2).

Smaller fallback, if the human prefers: Option A (keep folders, add `blocked_cause` and
`resolution`, explicit table). Its table and fields are a subset of B's, so B can be layered on
later, but given the cost argument above I would not choose it.

### 3.4 Proposed transition table (layout B)

Event names are the commands. "S" is Symphony, "H" is human (command or observed hand move).

| Event | From | To | Who | Effects |
|---|---|---|---|---|
| `new` | none | `work-todo` (`plan-todo` with `--plan` or `require_plan`) | H | create file |
| `dispatch_plan` | `plan-todo` | `plan-running` | S | claim; `not_before=None` |
| `dispatch_work` | `work-todo` | `work-running` | S | claim; `not_before=None` |
| `route_to_plan` | `work-todo` | `plan-todo` | S | only if `require_plan` and not `plan_approved` |
| `planned` | `plan-running` | `plan-review` | S | `attempts=0` |
| `plan_blocked` | `plan-running` | `question` | S | `blocked_cause=question` |
| `done` | `work-running` | `work-review` | S | `attempts=0`; validation passed |
| `work_blocked` | `work-running` | `question` | S | `blocked_cause=question` |
| `budget` | `plan-running` or `work-running` | `stuck` | S | `blocked_cause=budget` |
| `give_up` | `plan-running` or `work-running` | `stuck` | S | `blocked_cause=gave_up` |
| `retry_plan` | `plan-running` | `plan-todo` | S | `attempts+=1`, `not_before` |
| `retry_work` | `work-running` | `work-todo` | S | `attempts+=1`, `not_before` |
| `recover` | `plan-running` or `work-running` | the matching `-todo` | S | none (startup, shutdown) |
| `plan.accept` | `plan-review` | `work-todo` | H | `plan_approved=True`, clear `session_id` |
| `plan.reject` | `plan-review` | `plan-todo` | H | append feedback |
| `work.accept` | `work-review` | `done` | H | merge (unless `--no-merge`) |
| `work.reject` | `work-review` | `work-todo` | H | append feedback |
| `question.answer` | `question` | `plan-todo` or `work-todo` (by which run asked; sidecar `last_stage`) | H | append answer, `attempts=0` |
| `task.retry` | `stuck` (also `work-review`) | `plan-todo` or `work-todo` (by `last_stage`) | H | `attempts=0` |
| `task.stop` | `plan-running` or `work-running` | the matching `-todo` | H | agent killed |
| `task.discard` | any non-terminal | `discarded` | H | worktree removed by the tick |

`last_stage` (`plan | work`) replaces `phase` as the one remembered fact, needed only because
`question` and `stuck` do not encode the stage; it is set at dispatch. If this is felt to be
residual state, the alternative is `question` and `stuck` per stage (four folders), which I do not
recommend.

## 4. Build or buy: the state machine

### 4.1 Candidates (unverified, from memory, re-check before use)

| | `transitions` (pytransitions) | `python-statemachine` | `automat` | `sismic` | plain table |
|---|---|---|---|---|---|
| Model | flat and hierarchical FSM, callbacks | declarative class-based FSM, guards, actions, diagrams | typed-ish FSM for protocol code (Twisted) | full statecharts (YAML, Python) | `dict[(State, Event)] -> Transition` |
| License | MIT | MIT | MIT | LGPL | n/a |
| Maintenance | active as far as I recall | active as far as I recall | maintained by Twisted people | slower, research flavour | ours |
| Dependencies | `six` historically, light | none, light | `attrs` | `pyyaml`, `behave`, `sortedcontainers` | none |
| Pyright strict | weak: dynamic attribute magic, stubs partial | better, but still dynamic bound methods | decent | weak | full |
| Async | extension (`AsyncMachine`) | yes | no | no | n/a |
| Guards and effects | yes | yes | output functions | yes | rows carry them |
| Diagram export | via graphviz extra | yes | graphviz helper | PlantUML | print the table as markdown |
| Reuse in Rust rewrite | no | no | no | partly (statechart YAML, but needs an interpreter) | **yes: the table is data** |

### 4.2 Why libraries fit poorly here

- Libraries own a current-state attribute in memory. Here the state is the filesystem and every
  transition is an atomic `os.rename` (SPEC §12) by two actors (the human with `mv`, Symphony). We
  would have to rebuild the machine from the folder on every command and then write the state back,
  which makes the library a validator of `(src, event) -> dst` and nothing else.
- Dependencies: SPEC §12 says standard library plus PyYAML. A library breaks that for a 16-row
  table.
- Strict pyright with `Literal` state types is straightforward with a dataclass table and awkward
  with dynamic method generation.
- A Rust rewrite cannot reuse a Python library, but can reuse a data table.
- The machine is small and flat: 7 states, about 16 transitions, no hierarchy, no parallel regions,
  no timers beyond `not_before`.

### 4.3 Proposal: own a small declarative table, no library

```python
@dataclass(frozen=True)
class Transition:
    src: State
    event: str            # e.g. "plan.accept", "work.reject", "dispatch", "give_up"
    actor: Literal["human", "symphony"]
    dst: State
    guard: str | None     # e.g. "no uncommitted merge conflict" (documented, checked by caller)
    effects: tuple[str, ...]   # sidecar changes, e.g. ("attempts=0", "last_outcome=approved")
```

- One `TRANSITIONS: tuple[Transition, ...]` in `tasks.py`; `TaskStore.move` refuses a `(src, dst)`
  pair not in the table (hand moves in the file browser are still observed, not prevented).
- The orchestrator and the CLI commands call `fire(task_id, event)`, which finds the row, performs
  the rename and the effects, appends the `## Log` line. Illegal event: exit 1 listing the legal
  events for the current state (this is also `symphony next <id>`).
- The same table is rendered into SPEC §4.1 as markdown. One parametrized black-box test builds a
  task in `src`, runs the command for `event`, and asserts the folder, the Log line and the sidecar
  effects; a second test asserts every row has been exercised. A Rust rewrite reuses the markdown
  table and the same test.
- Deliberately not done: hierarchical states, a generic effect DSL (effects are named and
  implemented by hand), timers.

### 4.4 What would flip the decision

Adopt a library if any of these become true: guards or effects multiply to the point the table
needs conditional dst; states become hierarchical (for example a per-subtask machine for the later
"subtasks with dependencies" item); we need timers or concurrent regions; the library is verified
healthy, typed for pyright strict, and zero-dependency, and persistence can be bolted on cleanly.
Until then the table costs a few dozen lines.

## 5. Grammar, naming, confirmation

### 5.1 Grammar

`symphony <noun> <verb> <id>` for transitions and artifact actions. Flat verbs where the artifact is
the task itself, or the verb is a query.

```
symphony plan accept|reject <id>        # plan-review -> work-todo | plan-todo
symphony work accept|reject <id>        # work-review -> done (merge) | work-todo
symphony question answer <id> "text"    # question -> plan-todo | work-todo (reads text or $EDITOR)
symphony task retry|discard|stop <id>   # retry: stuck -> *-todo; discard: any -> discarded; stop: *-running -> *-todo
symphony task list [STATE] | show <id> | prio <id> N   # queries and edits on the task
symphony list | show | new | edit | feedback | status | run   # flat forms
```

### 5.2 Conventions for every transition command

- `<id>` accepts a unique prefix (shared resolver with `list`); ambiguous or unknown: exit 2.
- `--repo PATH` like today.
- Prints the new path of the task file; appends a `## Log` line (`human: ...`).
- Wrong state: exit 1 and print the legal events for the current state; no change.
- Usage errors: exit 2 (argparse default).
- `reject` takes `--feedback TEXT` (short) or opens `$EDITOR` for `--long`; it reuses the single
  `feedback` primitive (adds or extends `## Feedback`) then fires the event.
- `edit <id>` opens `$EDITOR` on the task file; `new` stays as is (and `task new` as alias).

### 5.3 Confirmation policy (decided by the human)

| Class | Commands | Behaviour |
|---|---|---|
| Safe (read only) | `list`, `show`, `next`, `status`, `logs`, `diff`, `path`, `doctor` | none |
| State-changing | `plan accept|reject`, `work reject`, `question answer`, `task retry|stop|prio`, `feedback`, `edit`, `new` | no prompt; recoverable by `mv` |
| Dangerous | `work accept` (merges into the main checkout), `task discard`, `clean` (deletes branches, worktrees, sidecars), future `pr` | prompt `[y/N]` on a TTY; no TTY and no `--yes`: exit 2 without acting; `--yes` skips the prompt |

Tests pass `--yes`. `--dry-run` for the dangerous class is optional: it prints what would be merged
or deleted and exits 0. Recommended for `clean` and `work accept`, cheap with the explicit table.

## 6. Command catalogue

Size: S under 1 hour of agent time, M a few hours, L more. Danger: safe, change, danger.
Testability is black-box in all cases unless noted.

### 6.1 Queries

| Command | Replaces | Usage | State touched | SPEC | Size | Danger |
|---|---|---|---|---|---|---|
| `list [STATE...]` | scanning `status` | `symphony list plan-review`, prefix filters, `--json` optional | none | §10, §11 | S | safe |
| `show <id>` | opening the file, the sidecar and git by hand | task text, state, cause, attempts, cost, branch, workspace path, next legal commands | none | §10, §11 | S | safe |
| `next <id>` or `next` | remembering what is legal | legal events for the task; without id, tasks awaiting the human | none | §4.1, §11 | S | safe |
| `logs <id> [--run N]` | reading JSONL | pretty-print the last run's assistant messages and the validation log | none | §9.2, §10 | M | safe |
| `diff <id>` | `git diff base...symphony/<id>` | wraps git, uses sidecar `branch` | none | §7, §11 | S | safe |
| `path <id> [--workspace]` | finding the file or worktree | prints a path, for `cd $(symphony path -w x)` | none | §2, §11 | S | safe |
| `doctor` | discovering setup errors at `run` | git, login, `WORKFLOW.md`, base branch, validate command dry run | none | §5.1, §11 | M | safe |

### 6.2 Edits

| Command | Replaces | Usage | Touches | Size | Danger |
|---|---|---|---|---|---|
| `feedback <id> "text"` (`--long` opens `$EDITOR`) | editing `## Feedback` | adds to the section, does not move | `## Feedback` | S | change |
| `edit <id>` | finding the file | `$EDITOR` on the task file | the file | S | change |
| `task prio <id> N` | editing front matter | rewrites `priority` | front matter | S | change |
| `init` | hand-writing `WORKFLOW.md` | writes a commented template, never overwrites | `WORKFLOW.md` | S | change |

### 6.3 Transitions

| Command | Replaces | Event row (section 3.1, today's layout; section 3.4 has the new names) | Effects | Size | Danger |
|---|---|---|---|---|---|
| `plan accept <id>` | `mv plan-review todo` | 10 | `last_outcome=approved`, `plan_approved`, clear `session_id` (explicit) | S | change |
| `plan reject <id> --feedback` | feedback plus `mv` to `plan` | 11 | adds feedback, moves | S | change |
| `work accept <id> [--no-merge]` | `git merge`, `mv`, remove worktree | 14 | preflight (clean main checkout, branch exists, base branch checked out), merge, `resolution=merged`, move to `done` | M | danger |
| `work reject <id> --feedback` | feedback plus `mv` to `todo` | 12 | adds feedback, moves | S | change |
| `question answer <id> "text"` | edit plus `mv` | 13 | adds answer as feedback, resets attempts, moves to `plan` or `todo` by `phase` | S | change |
| `task retry <id>` | `mv` | 13 | resets attempts | S | change |
| `task stop <id>` | `mv running todo` | 9 | agent is killed by reconcile | S | change |
| `task discard <id>` | `mv done` or `rm` | 15 | `resolution=discarded` | S | danger |

### 6.4 Hygiene and later

| Command | Purpose | Notes | Size | Danger |
|---|---|---|---|---|
| `clean [--merged] [--older N]` | delete branches, sidecars and `runs/` of finished tasks | uses `resolution`; `--dry-run` | M | danger |
| `pr <id>` | push branch and open a PR, feed comments back as feedback | SPEC §13; needs `gh`; scope carefully | L | danger |
| `subtasks <id>` | create tasks from the plan's *Suggested subtasks* | SPEC §13; emits `symphony new` lines first, no dependencies | M | change |
| `watch` | live `status` | defer: `watch symphony status` works | S | safe |

## 7. Mapping to the three blocked sibling tasks

| Task | Becomes | Re-plan prompt should reference |
|---|---|---|
| `new-command-for-approving-tasks` | splits into `plan accept` (pure move, explicit effects) and `work accept` (merge, preflight, `--no-merge`, confirmation) | sections 2.2, 3.3, 4.3, 5.3 of this doc; SPEC §4.1, §11, §14.3 |
| `add-a-feedback-command-for-plans-reviews` | stays, as the `feedback` primitive; `plan reject` and `work reject` reuse it | sections 5.1, 5.2; `replace_section` in `tasks.py` |
| `add-a-command-to-list-tasks` | stays, becomes `list` (and `task list`) with the shared `resolve_state` and prefix resolver; `status` helpers (`_print_table`) shared | sections 2.3, 5.2 |

Order: transition table first (Phase 1), then `list` and `feedback`, then the accept commands.

## 8. Roadmap

Phase 0: sign-off on this document (decisions listed in section 9).

Phase 1, explicit machine. SPEC §4.1, §4.2.
- `symphony new "Redesign the state model: stage x status folders (plan-todo, plan-running, plan-review, work-todo, work-running, work-review, question, stuck, done, discarded), explicit transition table in tasks.py, blocked_cause and last_stage in the sidecar, observed hand moves, SPEC and black-box test rename, one parametrized test per table row" --plan` (the largest task; consider splitting into the table and the rename)

Phase 2, read commands and the feedback primitive. SPEC §11.
- `symphony new "Add list command with state filter, id prefix resolver and shared table printer" --plan`
- `symphony new "Add feedback command that appends to ## Feedback (short text or EDITOR)" --plan`
- `symphony new "Add show and next commands (task details, legal events)" --plan`

Phase 3, artifact groups with confirmation. SPEC §4.1, §11, §14.2.
- `symphony new "Add plan accept and plan reject commands" --plan`
- `symphony new "Add work accept (merge with preflight, --no-merge) and work reject, with the confirmation policy and --yes" --plan`
- `symphony new "Add question answer and task retry, stop, discard" --plan`

Phase 4, convenience. SPEC §11, §10.
- `symphony new "Add edit, path, diff and logs commands"`
- `symphony new "Add doctor and init commands"`
- `symphony new "Add clean command (dry run, merged only)" --plan`
- `symphony new "Add pr and subtasks commands" --plan`

## 9. Open questions (need human sign-off)

1. Noun for finished work: `work` (recommended) or `review`?
2. `task list` and `task show` canonical with short aliases, or short forms only?
3. Accept option B (ten stage x status folders, section 3.3) with the transition table of 3.4, and
   the spec changing to match? Sub-questions: the folder names; whether `question` and `stuck`
   should stay stage-free with `last_stage` in the sidecar; and whether illegal hand moves are
   moved back (recommended) or only logged.
4. Own transition table, no library (section 4.3)? Library facts in section 4 need a web re-check
   by someone with search access if the decision is contested.
5. `question answer`: append the answer as `## Feedback` (recommended, reuses the primitive) or
   add a separate `## Answers` section?
6. Does `work accept` merge with a merge commit, fast-forward only, or squash? Needs a `WORKFLOW.md`
   option (`merge_strategy`) or one fixed choice.
7. Should hand moves in the file browser stay fully supported (this doc assumes yes: commands are
   sugar over the folder model)?
