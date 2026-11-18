---
priority: 3
depends_on: ["extract-retry-budget-and-turn-decision-policy-into-the-domai"]
---
# Make the task a domain aggregate behind a Tasks port

Part 5 of 7 of the refactor that ADR 0011 starts. Read docs/adr/0011 and 0012 first, and 0005, 0009 and 0010 for context. Follow them; do not re-decide them. ADR 0005's last bullet (the store sits behind a small interface) is what this task makes true.

Behavior does not change. The black-box suite must pass unchanged; if you must change a black-box test, say why in your log. Keep pyright strict at 0 errors. Layout: pure `src/samba/domain/`, use cases in `src/samba/app/`, ports in `src/samba/ports.py`, adapters in `src/samba/adapters/`.

The test of this task: replacing the markdown folders with a database or a remote tracker would change only an adapter. The domain and the use cases must know no path, folder, sidecar, file mtime or front matter.

Scope:
- A `Task` aggregate in the domain: id, title, body, priority, depends_on, status, the counters (attempts, turns, cost, tokens), session ids, plan approval, the plan and assumptions, feedback rounds, log entries, a queued-at value (replacing the file mtime used for dispatch order), and the questions. Closed types for the status, the stage, `blocked_cause` and `last_outcome` where the values are known. `Question` becomes a small frozen value object, replacing `dict[str, object]` and the `qstr`/`qint` helpers. A `TaskId` value with its rules (valid characters, slug, unique-prefix resolution as a pure function over known ids).
- The transition effects work on the aggregate, not on a sidecar with `setattr`.
- A `Tasks` port: get, list by status, create, and save of the whole aggregate. Log lines, the plan, feedback and questions are fields of the aggregate, not section editing.
- `adapters/markdown_tasks.py` keeps everything about folders, sidecar JSON, markdown sections, front matter and hand-move detection (it reports observed moves to the core as events). The front matter parser moves out of `config.py` into the adapter.
- Decide in the plan how the adapter avoids a stale whole-record save overwriting a human command (the worker keeps a copy for minutes while commands write the same record). Record the choice in the log and in the spec. Do not widen the scope beyond that.
- The plan may split this task. If it is too big for one run, say so in "Suggested subtasks" instead of trying.

Done when:
- `git grep -n "Path\|mtime\|sidecar" src/samba/domain src/samba/app` finds nothing (words in comments excepted).
- The domain and app modules are in `tests/test_architecture.py`, and the spec step is done (the task-files and states chapters describe the store as an adapter of the Tasks port).
- pyright and the tests pass.

## Plan
### Approach

Make `Task` the one record the core talks to, behind a `Tasks` port. The markdown folders, the sidecar JSON, the `## Log`/`## Plan`/`## Questions`/`## Feedback` sections, front matter and hand-move detection all move into `adapters/markdown_tasks.py`. Behavior does not change: the black-box suite passes unchanged. The one expected test-data change is the scenario JSON key `sidecar` -> `task`; say so in the log.

### Domain (`src/samba/domain/`, pure)
- `task.py`
  - `Task` is a mutable `@dataclass(eq=False)` with these fields:
    - `id: TaskId`, `title`, `body`, `priority: int | None`, `depends_on: tuple[TaskId, ...]`, `status: State`
    - counters `attempts`, `turns_total`, `cost_usd_total`, `input_tokens_total`, `output_tokens_total`
    - `session_id`, `plan_session_id`, `plan_approved`
    - `last_stage: Stage | None`, `blocked_cause: BlockedCause | None`, `last_outcome: LastOutcome | None`
    - `last_error`, `not_before`, `first_dispatched_at`, `queued_at: float | None`
    - `branch` and `workspace` as opaque `str | None`
    - `plan: str`, `assumptions: str`
    - `feedback: tuple[FeedbackRound, ...]`
    - `log: tuple[str, ...]`
    - `questions: tuple[Question, ...]`
  - Methods:
    - `Task.new(id, title, body, priority, depends_on, status, clock)`
    - `add_log(line)`
    - `add_feedback(text) -> int` (round number = highest existing + 1)
    - `add_questions(stage, items, clock)`
    - `answer_question(qid, text, clock)`
    - `dismiss_open(clock)`
  - `FeedbackRound(number, text)` is a frozen dataclass.
  - `ObservedMove(task_id, src, dst)` is a frozen dataclass: a hand move the store noticed.
- `task_id.py`: `TaskId(str)` with `ID_RE` validation (`[A-Za-z0-9._-]+`, not `.` or `..`), `TaskId.slug(title)` (the old `slugify`), and a pure `resolve(known: Iterable[TaskId], text)` (exact id, else unique prefix). It raises `UnknownTask` / `AmbiguousTask(candidates)`.
- `states.py`: keep `State` (this is the "status") and `Stage`. Add `BlockedCause = Literal[...]` (the six causes) and `LastOutcome = Literal["done","blocked","failed","retrying","planned"]`. Keep the `CAUSE_*` constants typed as `BlockedCause`.
- `questions.py`: `Question` becomes `@dataclass(frozen=True)` with `id, round, stage, status, text, context, asked_at, answer, answered_at`. Delete `qint` and `qstr`. The helpers (`latest_round`, `round_questions`, `open_questions`, `add_questions`, `dismiss_open`, `round_pairs`) work on `tuple[Question, ...]` and return new tuples. Answering uses `dataclasses.replace`. `render_questions` (markdown) moves to the adapter.
- `transitions.py`:
  - `Effect = Callable[[Task, Ctx, Clock], None]`. `_set` uses explicit typed lambdas or small functions, not `setattr`.
  - `apply_row(row, task, ctx, clock)` sets `task.status = row.dst`, sets `queued_at = clock.time()` when the destination is a todo state, and returns whether the questions changed (`before is not after` is enough with tuples).
  - `entry_line`, `log_line`, `find_row`, `human_row` and `human_events` take a `Task`. `stage_guard_ok` reads `task.last_stage`.
  - The table, its rows and the rendered markdown do not change.
- `deps.py`: add `deps_snapshot(task, get: Callable[[TaskId], Task | None]) -> dict[TaskId, TaskRef]`, which is today's `TaskStore.deps_snapshot` made pure.
- Delete `domain/sidecar.py`.

### Port (`ports.py`)
`Tasks` Protocol, in the domain's vocabulary:
- `get(id) -> Task | None`
- `list(status) -> list[Task]`
- `ids(status | None = None) -> list[TaskId]` (cheap, no parsing)
- `create(task) -> None` (raises `TaskExists` when the id is taken)
- `save(task) -> bool`: saves the whole aggregate. It returns False, and writes nothing, when the aggregate changes `status` and the stored status is no longer the one it was loaded with. This is the old `move()` compare-and-move.
- `observe_moves() -> list[ObservedMove]`, `accept_move(move)`, `revert_move(move) -> bool`: hand-move reporting.
- `rejected_names(status) -> list[str]`: records the store skipped as invalid.
- `location(id) -> str`: opaque "where the agent finds its task", for the prompt variable `task.path`.
- `prepare() -> None`: makes the store ready and raises `StoreError(message)` if it cannot be used (this carries the legacy-folder refusal text).

### Adapter (`adapters/markdown_tasks.py`)
- It takes over `tasks.py` entirely, including the `SidecarStore` JSON mapping (lenient coercion replaces `qstr`/`qint`).
- Section editing stays here (`replace_section`, `append_to_log_section`, `append_to_feedback_section`, `_demote`) and so does `render_questions`.
- `split_front_matter` moves here from `config.py`, raising its own error. `config.py` keeps its own YAML front-matter use for `WORKFLOW.md`: the adapter gets its own small copy with a local error type and `config.py` is untouched.
- It owns the hand-move bookkeeping (the recorded last-known folder), the `SAMBA_DEBUG_FIRE_DELAY` sleep and `updated_at`. Its constructor takes a `Clock`.

### Stale-save decision: three-way merge against a load-time snapshot, held by the adapter
The risk: the worker holds a `Task` for minutes while commands, such as `task stop`, `question answer` or `work reject`, write the same record. The agent also edits its own file's body, plan and log while it runs.

- On `get` and `list`, the adapter keeps a deep-copied snapshot of what it returned. It stores the snapshots in a `WeakKeyDictionary` keyed by the object, so identity is the key and there is no version field in the domain.
- On `save(task)`:
  1. Re-read the current stored record.
  2. Diff the aggregate against its snapshot, field by field.
  3. Write only the fields the aggregate changed. Fields it did not touch keep the stored (current) value. If both sides changed a scalar, the aggregate wins.
  4. Merge by structure for the list fields:
     - `log` and `feedback` are append-only. Only entries beyond the snapshot's are appended to the current section, so the agent's own lines are kept.
     - `questions` merge by id. For a question both sides changed, the stored version wins, so a human answer is not lost.
  5. `status` is the exception: it is written only if the aggregate changed it. The adapter then checks stored status == snapshot status. If not, `save` returns False and writes nothing. If so, it renames atomically.
  6. The recorded last-known folder changes only on a status-changing save, on first sight, or in `accept_move`. A stale counter save never resets it, so a hand move is not missed.
  7. Rewrite the `.md` only when a markdown-owned field changed (`body`, `plan`, `assumptions`, `log`, `feedback`, `questions`, `status`). Counter-only saves touch only the sidecar JSON. This keeps the rule that Samba writes the task file only when no agent runs.
  8. After a successful save, refresh the aggregate in place from the merged result and renew its snapshot. The worker's copy then picks up what a human changed, such as answered questions.
- Rejected alternative: a `version` plus a conflict-and-retry loop. It would push retry logic into every use case and make the worker re-apply increments. The merge keeps the use cases simple, and a database adapter can use its own row versioning behind the same port.
- Record this in the task `## Log` and in the spec, in `states.md` (replacing "Task store interface") and in the `task-files.md` Write discipline.

### Use cases
- `app/machine.py` (moved from `samba/transitions.py`)
  - `Machine(tasks: Tasks, clock, guard)`.
  - `fire(task_id, event, *, task=None, message="", **ctx) -> bool`:
    1. Load the fresh task. Its `status` picks the row with `find_row`.
    2. Apply the effects to `task` if given (the worker's copy), else to the fresh one.
    3. Append the entry line with `add_log`.
    4. Call `tasks.save`. A False result means the move was lost, so return False.
  - `observe(move, task) -> str` applies the human row, saves, calls `accept_move`, and returns the log line to defer. The `kv` logging stays.
- `app/turn.py`: `TurnFlow.run(task, setup, validate, on_turn)` and `invoke(task, ...)` take a `Task`. They mutate it and call `self.tasks.save(task)` after each turn. `_plan_sections` sets `task.plan` and `task.assumptions`, `_ask` calls `task.add_questions`, and the denial lines go through `task.add_log`. `TurnStore` is deleted. `TurnFlow` takes `tasks: Tasks`.
- `orchestrator.py`:
  - Takes a `Tasks` (default `MarkdownTasks`) and drops `SidecarStore`, `_TurnStore` and every `side`.
  - Dispatch sorts on `(priority is None, priority or 0, queued_at, id)`.
  - `observe` uses `tasks.observe_moves()` and `revert_move`. `pending_notes` stays: lines are applied through `get`, `add_log`, `save` when the worker ends.
  - `path(...)` becomes `tasks.location(id)`, and legacy and invalid names go through `prepare()` and `rejected_names`.
- `cli.py`, `views.py`:
  - `resolve_task_id` becomes a thin wrapper over `TaskId.resolve`, converting its errors to `ResolveError`.
  - `task new` builds `Task.new(...)` and calls `tasks.create`. The unique-slug loop uses `tasks.get`. The CLI no longer writes front matter, because the adapter does.
  - `question answer`, the feedback commands and `work accept` use `get`, `add_feedback`, `answer_question` and `save` under the repo lock.
  - `task show` and `task list` read the aggregate.
  - `views.py` still reads `time.time` today and keeps doing so, as the architecture chapter notes.

### Steps

Tests first at each stage, in the style of the existing ones.

- [ ] Read ADRs 0005, 0009, 0010, 0011 and 0012 and the spec chapters `architecture`, `task-files`, `states`, `orchestrator`, `implementation-notes`.
- [ ] Check what `tests/fake_claude.py` can do (slow turns, editing its own task file). Write the new black-box tests first:
  - the agent edits its file's body or log during a run, and the worker's later saves keep that edit;
  - `task stop` during a run, and the worker's later counter saves do not revert `blocked_cause=stopped`;
  - `task new` from a title writes the same file as before (front matter plus `# title`).
  Expect these to already pass, since the behavior is unchanged. If one fails against `main`, it is a latent bug: report it in the log and do not widen the scope.
- [ ] (5a) Domain types: `task.py`, `task_id.py`, closed types in `states.py`, the frozen `Question`. Pure unit tests with scenario-style data for the `TaskId` rules (valid chars, slug, unique-prefix resolution, ambiguity) and the `Question` helpers.
- [ ] (5a) Add `Tasks` to `ports.py`, with `tests/fake_tasks.py` (in-memory) and a contract test file `tests/test_tasks_port.py` parametrized over the fake and `MarkdownTasks`. It covers `create`, `get`, `list`, status-change `save` returning False on a lost race, and the merge rules: a stale counter save keeps a human's `blocked_cause`, log and feedback appends merge, concurrent question answers merge, the agent's body edit survives, and `state` is not reset by a stale save. This test file may import adapters; the black-box and scenario runners may not.
- [ ] (5a) Write `adapters/markdown_tasks.py` next to the old `tasks.py`, not yet used.
- [ ] (5b) Move effects and row helpers onto `Task`. Migrate the scenario JSON and runner (`sidecar` -> `task`). Replace `MemoryStore` with `FakeTasks`. Move `Machine` to `app/machine.py`. Convert `TurnFlow` and the orchestrator. Delete `domain/sidecar.py`.
- [ ] (5c) Convert `cli.py` and `views.py`. Delete `tasks.py`. Make the adapter the only holder of `split_front_matter`.
- [ ] (5c) Update `tests/test_architecture.py`:
  - append `domain/task.py` and `domain/task_id.py` to `DOMAIN_MODULES`, and remove `domain/sidecar.py`;
  - append `app/machine.py` to `APP_MODULES`;
  - add a check that `domain/` and `app/` code, with comments stripped, matches none of `Path`, `mtime`, `sidecar`, `front matter`;
  - keep the no-direct-clock check over the new modules;
  - assert that `samba.tasks` no longer exists and that `orchestrator.py` and `cli.py` import `samba.adapters.markdown_tasks` and not folder helpers.
- [ ] (5c) Spec step:
  - `architecture.md`: the Ports table gets `Tasks` and `MarkdownTasks`; "Where each concern lives" drops the task-store line; the scenario table says `task` instead of `sidecar`; the architecture-test section is updated.
  - `task-files.md`: Identity, Write discipline and the section mapping are described as the markdown adapter of the `Tasks` port, plus the stale-save merge rule.
  - `states.md`: "Sidecar state" becomes the aggregate's fields plus how the adapter stores them. "Observed hand moves" is reported by the adapter as events. "Data model" and "Task store interface" are rewritten to the port. `blocked_cause` and `last_outcome` become closed sets, with an unknown value read as null.
  - `orchestrator.md`: the dispatch order key is `queued_at`.
  - `implementation-notes.md`: where the debug fire delay lives.
  - `CLAUDE.md`: the repo map (`tasks.py` -> `adapters/markdown_tasks.py`, `domain/task.py`, `domain/task_id.py`, `app/machine.py`).
- [ ] Add a `## Log` entry to the task file with: the stale-save decision, the `sidecar` -> `task` JSON key rename, and any black-box test change with its reason. Spec and manual: `docs/manual.md` should need no change, because no CLI command changes; `tests/test_manual.py` still checks.
- [ ] Run `git grep -n "Path\|mtime\|sidecar" src/samba/domain src/samba/app`. It must find only comments.
- [ ] Run `uv run pyright` (0 errors) and `uv run pytest -q`, as separate plain commands.

### Files to change

- New:
  - `src/samba/domain/task.py`
  - `src/samba/domain/task_id.py`
  - `src/samba/app/machine.py`
  - `src/samba/adapters/markdown_tasks.py`
  - `tests/fake_tasks.py`
  - `tests/test_tasks_port.py`
  - extra black-box tests in `tests/test_blackbox.py`
- Edit:
  - `src/samba/ports.py`
  - `domain/{states,questions,transitions,deps}.py`
  - `app/turn.py`
  - `orchestrator.py`
  - `cli.py`
  - `views.py`
  - `config.py` (no change needed if the adapter has its own front-matter copy; otherwise drop `split_front_matter` from it)
  - `tests/test_scenarios.py`
  - `tests/scenarios/*.json` (key rename)
  - `tests/test_architecture.py`
  - the spec chapters listed above
  - `CLAUDE.md`
- Delete:
  - `src/samba/tasks.py`
  - `src/samba/transitions.py` (moved)
  - `src/samba/domain/sidecar.py`

### Risks

- **Size.** Roughly 15 files change at once. Follow the split below so each commit stays green.
- **Dispatch order.** The mtime-to-`queued_at` change could reorder tasks in edge cases (hand-created files, edits by hand). Black-box ordering tests are the check. Fix the rule, not the test.
- **Merge correctness.** The snapshot merge is the subtle part. The contract tests must cover both interleavings: a worker save after a command, and a command after a worker save. Make sure the in-place refresh does not clobber unsaved in-memory changes in the aggregate.
- **Log and question rendering.** The `## Log` and `## Questions` text must stay byte-identical, because black-box tests assert on files. Reuse the existing section functions unchanged.
- **Hand-move bookkeeping.** `state` in the sidecar JSON must be written only by a status-changing save, by first sight and by `accept_move`. A stale save that rewrites it would hide or repeat a hand move.
- **Effects on a lost race.** `fire` with a worker copy mutates the copy even when `save` returns False. That is harmless because the worker ends, but the worker must not reuse the copy after a False.
- **Old sidecars.** Old sidecars can hold unknown values (`approved`, unknown causes). The adapter coerces them to null.
- **Closed types.** The closed-type change in the spec ("open string, not a closed set") is a spec decision this task makes, as the task asks. State it in the log.

### How to verify

- `uv run pyright` reports 0 errors, and `uv run pytest -q` passes with `tests/test_blackbox.py` unchanged. If it must change, give the reason in the task `## Log`.
- `git grep -n "Path\|mtime\|sidecar" src/samba/domain src/samba/app` finds no code, only comments.
- `tests/test_architecture.py` lists the new domain and app modules. It passes, and its new check fails when `Path` or `sidecar` is added to a domain module (test it with a temporary file, as the existing scanner test does).
- `tests/test_tasks_port.py` passes for both `FakeTasks` and `MarkdownTasks`. Add a case that fails if `save` writes a field the aggregate did not change.
- A manual run of `samba run --exit-when-idle` with the fake claude gives the same files as before the change. Compare a diff of the `.samba/tasks` and `.samba/state` trees.

### Suggested subtasks

Run in order. Each leaves pyright and the full suite green.

1. **5a: Domain types, the `Tasks` port, `FakeTasks` and `MarkdownTasks` with the merge strategy.** Nothing else is rewired. It is mostly new code plus the contract tests. Done when the contract tests pass for both implementations.
2. **5b: Move the core onto the aggregate.** This covers effects on `Task`, `app/machine.py`, `TurnFlow`, the orchestrator and the scenario JSON rename. `domain/sidecar.py` is deleted. The CLI still builds the adapter and goes through the new port. Done when the full suite passes.
3. **5c: Move the CLI and the views onto the port.** Delete `tasks.py`, move front matter into the adapter, and extend `test_architecture.py`. Do the spec step, the `CLAUDE.md` update and the log entries. Done when the "Done when" list of the task is met.

If time allows only one run, do 5a and 5b together and leave 5c, because the `grep` check needs 5c.

## Assumptions
- `TaskId` is a `str` subclass (validated `parse`, `slug(title)`, pure `resolve(known, text)`), so git, workspace, JSON and f-string code keeps working. It is not a wrapper dataclass.
- `Task` is a mutable dataclass with `eq=False` and keeps the sidecar field names (`turns_total`, `cost_usd_total`, `input_tokens_total` and so on), so the sidecar JSON on disk stays byte-compatible and black-box tests that read it do not change.
- `branch` and `workspace` stay on the aggregate as opaque `str | None`: the orchestrator and `task show` use them, and they are not paths to the domain. `updated_at` and the recorded last-known folder (`state` in the JSON) are adapter-private bookkeeping, not aggregate fields.
- `queued_at` is set in the domain: `Task.new` sets it, and `apply_row` sets it when the destination is a todo state. The adapter fills it from the file mtime only for a task with no recorded value (hand-created file), and persists it in the sidecar JSON as a new optional field. Today's mtime is bumped by the `## Log` append of each transition, so the order should be equivalent. If an ordering black-box test disagrees, fix this rule and not the test.
- The scenario JSON key `sidecar` becomes `task`. Field names stay the same, so only the key and the runner change. This is the only test-data change.
- `Machine` moves to `app/machine.py`. The test-only `SAMBA_DEBUG_FIRE_DELAY` sleep moves into the markdown adapter's save, between the rename and the sidecar write. That keeps the same observable window and keeps `time` and `os` out of `app/`.
- `orchestrator.py`, `cli.py` and `views.py` stay where they are, rewritten against the port. Moving their use cases into `app/` and building the composition root is later work in the chain. Constructors keep defaulting to `MarkdownTasks`.
- An unknown `blocked_cause` or `last_outcome` read from an old sidecar is coerced to `None` by the adapter. The closed types are the domain's contract.
- The new, closed `Question` fields are `status` in {open, answered, dismissed} and `stage` in {plan, work}.

## Log
- 2026-11-10 19:46 samba: dispatch_plan: plan-todo -> plan-running
- 2026-11-10 19:50 samba: planned: plan-running -> plan-review: planned (turns 1, $0.62): Plan for the Task aggregate, the Tasks port and a `MarkdownTasks` adapter. The adapter avoids stale saves with a three-way merge against a snapshot it keeps from load time. The work is big, so I recommend three sequential subtasks (5a, 5b, 5c), each leaving the suite green.
- 2026-11-11 10:38 samba: task.discard: plan-review -> discarded
