---
priority: 3
depends_on: [cli-cleanup]
---
# Questions as data

Today a question is free text the agent writes under `## Questions` in the task file. The human
cannot see which question they are answering, and the answer is stored as a feedback round. Make
questions records with ids, owned by Symphony, and give the human commands to find and answer
them.

Read first: SPEC §3 (task files), §3.3 (write discipline), §4.1 and §4.2 (states, sidecar), §8
(prompts, protocol prompt), §11 (`question answer`), §14 (planning outcome);
`src/symphony/prompts.py` (outcome schemas, protocol prompt), `tasks.py` (`Sidecar`, task file
editing), `orchestrator.py` (handling of the `blocked` outcome and resume prompts), `cli.py`
(`question answer`), `views.py`.

Decisions already made by the human:

- **The agent reports questions in its outcome, not in the file.** The work and plan outcome
  schemas get `questions: [{text, context}]` (an array; `context` explains why it matters). It is
  required to be non-empty when `outcome` is `blocked` for a question. The protocol prompt tells
  the agent to never write `## Questions` itself.
- **Symphony assigns ids and stores the records** in the sidecar, as a `questions` list. Each
  record: `id` (`q1`, `q2`, ..., per task, increasing, never reused), `round` (the number of the
  blocking event that asked it), `stage` (plan or work), `status` (`open`, `answered`,
  `dismissed`), `text`, `context`, `asked_at`, `answer`, `answered_at`. The full name of a question
  is `<task>/<qid>`.
- **The task file shows a rendered view.** Symphony regenerates the `## Questions` section from the
  records each time they change: every question with its id, round, status and answer. Neither
  the agent nor the human edits it. Add this to the write discipline in SPEC §3.3.
- **Commands:**
  - `question list`: every open question across tasks; columns TASK, QID, STAGE, ASKED,
    QUESTION (truncated to the terminal).
  - `question show TASK[/QID]`: full text and context. Without QID, all questions of the latest
    round, with their status.
  - `question answer TASK[/QID] (TEXT | --edit)`: the `/QID` part may be left out only when exactly one
    question is open (otherwise exit 2 listing the open ids). `--edit` opens `$EDITOR` with the
    question and context quoted at the top as comment lines that are stripped.
- **When the task resumes:** each answer is recorded immediately (under the repo lock). The
  `question.answer` event fires, moving the task to its todo folder, only when no question of the
  round is still open. Answering a question that is not open is exit 1.
- **What the agent sees on resume:** the resume prompt includes the round's question and answer
  pairs (and says which were dismissed), so the agent does not dig them out of the file.
- **Hand moves:** moving the task from `question/` to a todo folder by hand stays the legal
  observed `question.answer` event; open questions of the round become `dismissed`.
- **Plan "Questions" become "Assumptions":** rename the planner's non-blocking `questions` string
  field and the section it renders into to `assumptions`. They are answered through plan review
  (`plan accept` / `plan reject`), not through `question`. A planner that is truly blocked uses
  the structured `questions` list like the work agent.
- **Answers are not feedback rounds anymore.** `question answer` no longer writes under
  `## Feedback`; the `## Log` line names the question (`question.answer: work/q2 answered`).
- **SPEC gets a "Data model" section** listing every record kind: task, run, feedback round,
  question, log line. For each: its identifier, who writes it, where it is stored, and its
  lifecycle. Questions are the first record with real ids; the others are documented as they are,
  not changed. Note that the store is files, and that a database would replace the storage, not
  the model.
- Existing tasks have no `questions` field: a missing field means an empty list. No migration of
  old free-text `## Questions` sections.

Acceptance:

- Black-box tests first, using the fake agent's structured outcomes:
  - a blocked run with two questions gives `q1` and `q2`, both `open`, in the sidecar, the
    rendered section and `question list`;
  - answering one leaves the task in `question/`; answering the second moves it to its todo
    folder and the next prompt contains both pairs;
  - QID omitted with two open questions is exit 2;
  - a second blocking round gives `q3` with `round: 2`;
  - a hand move dismisses open questions;
  - plan assumptions render under the new name.
- `uv run pyright` 0 errors, `uv run pytest -q` passes. No em-dashes.

If the plan is large, propose a split (for example, data model, SPEC and storage first, then the
commands and prompts).

## Plan
### Approach

Questions become records in the sidecar (`Sidecar.questions: list[dict]`, a missing field means `[]`). Symphony owns them: the agent reports `questions: [{text, context}]` in its structured outcome, the orchestrator assigns ids (`q1`, `q2`, ..., max existing + 1, never reused) and rounds, and the `## Questions` section of the task file is a rendered view regenerated on every change. `question list|show|answer` operate on the records. `question.answer` fires only when no question of the round is still open. Hand moves out of `question/` are observed as `question.answer` and dismiss open questions. Plan "Questions" become "Assumptions".

Design decisions to settle (record them in SPEC and the task `## Log`):

- **Round number.** Round = 1 + max `round` among existing records, assigned per blocking event that carries questions. No separate counter is needed. The "latest round" is the max `round`.
- **Record shape (JSON in sidecar):** `{id, round, stage, status, text, context, asked_at, answer, answered_at}`. `asked_at` and `answered_at` are ISO-8601 local-time strings, `answer` is null until answered. A dismissed question has `answered_at` set to the dismissal time and `answer` null.
- **Blocked without questions (decided by the human).** The schemas make `questions` an optional array with `minItems: 1`. A `blocked` outcome with no valid questions (for example an agent blocked by a permission denial) still goes to `question/`: Symphony synthesizes one open question whose `text` is the run summary (or "The agent reported blocked without a question" if empty) and whose `context` says it was synthesized and lists the run's permission denials, if any. Never retry a blocked run. Test it.
- **Where dismissal lives.** Add a row effect `questions=dismiss_open` on the four `question.answer` rows. It is a sidecar-only effect, so it respects the table's rule that rows change only Symphony's own state. `Machine.fire` and `Machine.observe` re-render `## Questions` after `_apply` when the questions changed. The command path never has open questions at fire time, so the effect is a no-op there. For a hand move no agent runs, so writing the file is safe (§3.3).
- **Answers recorded immediately.** `question answer` writes the record and re-renders the section under the repo lock. It fires `question.answer` only if no question of the latest round is open. The `## Log` line is `question.answer: work/q2 answered` per answer. When the last answer fires the event, the usual transition line also appears. Do not append anything under `## Feedback`.
- **Resume prompt.** On the first run after a question round, `_variables` gets a new `{{ questions }}` variable. It holds the latest round's pairs, marking dismissed ones: `q1 (answered): text` / `Answer: ...`. The default `resume` prompt includes `{{ questions }}`. A custom `prompts.resume` override that lacks the variable still works. Also append the block to the `plan_revise` prompt, and use it when a planner was blocked. The planner resumes through `plan_revise` if `plan_session_id` exists, so the round's pairs must appear there too. Render strictly as in `template.py`. If the round has no questions the variable is an empty string.
- **Plan assumptions.** Rename the plan schema field `questions` (string) to `assumptions` and render it into `## Assumptions` via `set_section`. `RunResult.questions` becomes `RunResult.assumptions` (text) plus a new `RunResult.question_items` (parsed list of `{text, context}`, dropping malformed entries). The plan schema gets the structured `questions` array like the work schema.

### Steps

- [x] Read SPEC §3, §3.3, §4.1, §4.2, §8, §9.3, §11, §14 and the existing question tests (`test_blackbox.py`, `test_commands_phase2.py`, `test_layout.py`, `test_planning.py`, `test_transitions.py`, `test_cli_surface.py`, `test_dependencies.py`). Grep `question|Questions` in `tests/` (70 hits) to list everything that changes.
- [x] **Fake agent** (`tests/fake_claude.py`): the step field `questions` becomes a list of `{text, context}` (or `[text, context]` pairs) emitted in `structured_output.questions` for both work and plan runs. Add the step field `assumptions` (string) for planning runs. Update the docstring. Keep it standard library only. The fake already records argv in `<task>.calls.jsonl`. Tests need the prompt, so check how the prompt is passed in argv (`-p`) and assert on that.
- [x] **Black-box tests first** (new file `tests/test_questions.py`, or in `test_blackbox.py` style, no `symphony` import). Add Sandbox helpers if missing: read the sidecar JSON, read a task file, run the CLI. Cases:
  1. A blocked work run with two questions gives `q1` and `q2`, both `open`, `round: 1`, `stage: work`, in the sidecar. The task file has `## Questions` rendering ids, round, status. `question list` shows both with TASK, QID, STAGE, ASKED and QUESTION columns. The text is truncated to the terminal width (use `COLUMNS`).
  2. Answering `q1` leaves the task in `question/`. The sidecar shows `q1` answered, `q2` open, and the rendered section shows the answer. Answering `q2` moves the task to `work-todo/`. The next prompt (from the fake's calls file) contains both question and answer pairs. No `## Feedback` section appears. The `## Log` has `question.answer: work/q1 answered`.
  3. QID omitted with two open questions: exit 2, stderr lists the open ids. QID omitted with exactly one open question works. Answering a non-open (answered or dismissed) question: exit 1. An unknown QID: exit 2. `question answer` with neither TEXT nor `--edit`: exit 2. Empty text: exit 2, as today.
  4. A second blocking round gives `q3` with `round: 2`, `q1`/`q2` untouched, and `question show TASK` (no QID) shows only round 2 questions with their status. `question show TASK q1` shows the full text and context.
  5. A hand move `question/` -> `work-todo/` (and `plan-todo/` for a planner) marks the open questions `dismissed`, keeps answered ones, rewrites the section, and the resume prompt says which were dismissed.
  6. A plan run with `assumptions` renders `## Assumptions`, and no `## Questions` section is written. A blocked planner with structured questions gives open records with `stage: plan`, `question list` shows them, and answering resumes via `plan-todo`.
  7. A task with no `questions` field in its sidecar works: `question list` is empty, and nothing crashes.
  8. `question --help` and `symphony --help` list the new verbs. Update `test_cli_surface.py`.
  9. A blocked outcome without questions follows the chosen failure path. `question.answer` hand move still works for old tasks in `question/`. `dev transitions` output still matches the SPEC-embedded table.
- [x] **Existing tests**: update every test that uses the free-text `questions` step field or checks `## Questions` content, the answer-as-feedback behavior (`test_commands_phase2.py`, `test_planning.py`, `test_layout.py`, `test_blackbox.py`), and the `question answer ID` positional form.
- [x] **Storage** (`tasks.py`): add `Question` as a frozen or plain dataclass (typed) and `Sidecar.questions: list[dict[str, object]]`. Keep it a list of plain dicts so `asdict`/JSON stay simple, and use `cast` at the load boundary. Add helpers: `next_question_ids`, `add_questions(side, stage, items, now)`, `open_questions(side)`, `latest_round(side)`, `answer_question`, `dismiss_open`, and `render_questions(side) -> str`. Add `TaskStore.render_questions(task_id, side)`, which calls `set_section("Questions", ...)`. Rendered format, per question: `### q1 (round 1, open)` then the text, the context, and `Answer: ...` when answered. `_demote` handles stray headings in the agent's text, and the generated `###` lines must survive `replace_section` (it only treats `## ` as a section end). With no questions, remove the section or write nothing (keep it simple: do not create it).
- [x] **Transitions** (`transitions.py`): add the effect `questions=dismiss_open` to the four `question.answer` rows and register it in `EFFECTS`. In `Machine.fire` and `Machine.observe`, re-render the section when questions changed. Regenerate the SPEC §4.1 table via `uv run symphony dev transitions` and paste it between the markers.
- [x] **Outcome plumbing** (`claude.py`, `prompts.py`): `OUTCOME_SCHEMA` and `PLAN_OUTCOME_SCHEMA` get `questions: {type: array, minItems: 1, items: {type: object, properties: {text, context}, required: [text, context]}}`. The plan schema renames the string field to `assumptions`. `RunResult.question_items` and `RunResult.assumptions`. Update `PROTOCOL` ("never write `## Questions` yourself; report questions in `questions` with outcome `blocked`; each has `text` and `context`") and `PLAN_PROTOCOL` (assumptions are non-blocking and go in `assumptions`; truly blocking questions go in `questions`). Update the default `resume` and `plan_revise` prompts and the give_up prompt wording. No em-dashes anywhere.
- [x] **Orchestrator** (`orchestrator.py`): in the work `blocked` branch and in `_plan`, build the records from `res.question_items` (id and round assignment, `asked_at`, `stage`), save the sidecar, and render the section before `_finish`. `_finish` passes the same `side` into `fire`, so the sidecar saved by the effect includes the new questions, so add them to `side` before calling `_finish`. A blocked outcome with no items goes to `_fail`. For plans, write `## Assumptions` instead of `## Questions`. Add the `questions` template variable in `_variables` (the latest round's pairs). Write the `## Log` summary line for the block, such as `blocked (turns N, $X): summary`.
- [x] **CLI** (`cli.py`, `views.py`): `question list` (all open questions across task folders, columns TASK, QID, STAGE, ASKED, QUESTION, truncated with `shutil.get_terminal_size`; a `question_rows` helper in `views.py`, printed with `print_table`), `question show TASK [QID]` (full text and context; without QID, all questions of the latest round with status), `question answer TASK [QID] (TEXT | --edit)`. Parsing (decided by the human): the first positional is `TASK` or `TASK/QID` (the full question name from the design), the second is the optional TEXT. So `question answer TASK TEXT` (only valid with exactly one open question) and `question answer TASK/q2 TEXT`, with no ambiguity. The task part accepts prefixes as usual; split on the last `/`. `question show` takes the same `TASK` or `TASK/QID` form. `question list` prints the QID column as the full `task/qid` name so it can be copied straight into `answer`. Implement `cmd_question_answer` separately from `cmd_transition` (which assumes one fire and feedback): reuse `resolve_task_id`, `repo_lock`, the legality check (`question.answer` must be legal in the current state), then record the answer, re-render, log, and fire only when none is open in the latest round. `--edit` opens `$EDITOR` with the question and context quoted as `# ` comment lines at the top, which are stripped (add `_edit_answer`, mirroring `_edit_feedback`, before taking the lock). Exit codes: 2 for usage errors (missing text, ambiguous or unknown QID, QID omitted with several open) and 1 for a non-open question or lock failure. Print the new path after a fire, as other commands do. Add `repo` args like the others. Update `views.render_show` to print open question counts.
- [x] **SPEC**: §3.2 and §3.3 (the `## Questions` section is rendered and neither the agent nor the human edits it; the write discipline allows a command to rewrite it under the repo lock), §4.2 (`questions` field and its record), §8.5 (protocol prompt), §9.3 (schemas), §11 (new command synopses, exit codes and the `question answer` rules), §14 (outcome schema, rename to `assumptions`, `## Assumptions`, fake additions and test list), §5.4 and §8.2 (resume prompt contents), and a new **"Data model"** section (suggest placing it as §4.0, or a new section after §4, avoiding renumbering where possible): a table of task, run, feedback round, question, log line, each with identifier, writer, storage and lifecycle. Note that the store is files and that a database would replace the storage, not the model. Document the existing kinds as they are: task id = file name, run = `runs/<task>/NNN.jsonl` (turn number), feedback round = `### Round N` under `## Feedback`, log line = timestamped bullet, no id. Remove the old "answer appended as feedback" text.
- [x] **CLAUDE.md map**: mention the new `question` commands and the question helpers in `tasks.py`.
- [x] Run `uv run pyright` (0 errors) and `uv run pytest -q` as separate commands. Fix, then grep for em-dashes in changed files. Add a line to the task's `## Log` saying which spec details were settled (round numbering, blocked-without-questions, QID parsing ambiguity, rendered format).

### Files to change

- `tests/fake_claude.py`, `tests/conftest.py` (helpers), new `tests/test_questions.py`, and updates to `tests/test_blackbox.py`, `test_commands_phase2.py`, `test_planning.py`, `test_layout.py`, `test_transitions.py`, `test_cli_surface.py`.
- `src/symphony/tasks.py` (Sidecar field, record helpers, rendering), `transitions.py` (effect, re-render hook), `claude.py` (`RunResult`), `prompts.py` (schemas, prompts), `orchestrator.py` (recording, variables, plan assumptions), `cli.py` (three commands, parsing, editor), `views.py` (rows, show).
- `SPEC.md` (many sections plus Data model), `CLAUDE.md`.

### Risks

- **Sidecar save ordering.** `_finish` passes the worker's `side` object to `fire`, which saves it. Questions must be added to that same object, or the effect will overwrite them with stale state. The command path loads a fresh sidecar under the lock, so keep load, modify and save inside it.
- **Observed hand moves with a running agent** defer `## Log` lines (`_note`). The re-render of `## Questions` is safe because the task came from `question/`, where no agent runs, but guard it by skipping the file write if the task is in `self.running`.
- **Table sync tests.** The SPEC-embedded transition table must match `dev transitions` exactly after the new effect.
- **Resume prompt for custom `prompts.resume` overrides** that lack `{{ questions }}`: those agents would not see answers. Mitigate by appending the block to the prompt in code if the template does not reference the variable, or document it. Pick the append approach to avoid silent loss.
- **Schema strictness.** If a model emits `questions` as a string (old behavior), parsing must not crash. Drop malformed items and take the blocked-without-questions path.
- Old tasks in `question/` with free-text `## Questions` and no records: answering has nothing to answer, and the human can hand move them, which is the legal observed `question.answer`. Mention this in SPEC (no migration).

### How to verify

- `uv run pyright` reports 0 errors.
- `uv run pytest -q` passes, including the new tests listed above (blocked with two questions, partial answer stays in `question/`, full answer resumes with both pairs in the prompt, QID omitted exits 2, second round gives `q3` with `round: 2`, a hand move dismisses, assumptions render under the new name).
- `uv run symphony dev transitions` output equals the SPEC embed (an existing test covers this).
- Grep for em-dashes in changed files finds none.

### Suggested subtasks (split)

1. **Data model, storage and orchestration:** fake agent changes, schemas, `RunResult`, sidecar records and rendering, orchestrator recording, the dismissal effect, plan `assumptions`, protocol prompts, resume variable and prompt, tests 1, 4, 5, 6 and 7 (via sidecar and file checks and the hand-move path), and the SPEC sections for §3, §4, §8, §9, §14 and the Data model.
2. **Commands:** `question list|show|answer` (including `--edit` and QID parsing), exit-code rules, tests 2, 3 and 8, SPEC §11, CLAUDE.md.

Subtask 2 depends on 1. If done as one change, keep the order above.

## Questions
Answered by the human (edited into the plan above): (1) a blocked outcome with no questions moves to `question/` with one synthesized question; (2) questions are addressed as `TASK/QID`, no separate QID positional. Do it as one change, in the order of the suggested subtasks.

## Log
- 2026-11-07 23:13 symphony: dispatch_plan: plan-todo -> plan-running
- 2026-11-07 23:14 symphony: planned: plan-running -> plan-review: planned (turns 1, $0.38): The plan covers the sidecar question records, the rendered `## Questions` view, the three `question` commands, the resume prompt, plan `assumptions`, and the SPEC Data model section. It starts with black-box tests and proposes a two-part split: data model and orchestration first, commands second. Two open questions remain: how to handle a `blocked` outcome with no questions, and how to parse `TASK QID TEXT`.
- 2026-11-07 23:28 symphony: plan.accept: plan-review -> work-todo
- 2026-11-07 23:28 symphony: dispatch_work: work-todo -> work-running
- 2026-11-07 23:50 agent: implemented as one change. Details settled: round = 1 + highest existing round (latest round = highest); ids = highest ever used + 1; rendered format `### qN (round R, status)` + text + `Context:` + `Answer:` (no records: no section); blocked without valid questions synthesizes one open question from the run summary (never retried); `question list` QID column is the full `task/qid`; target parsed by splitting on the last `/`; `question answer` with no open question is exit 1; the `{{ questions }}` variable is filled only when `last_outcome == blocked` and nothing is open, and custom resume/plan_revise prompts without it get the block appended. SPEC renumbered: §4.3 Questions, §4.4 in-memory state, §4.5 Data model, §4.6 task store interface (refs updated). Tests: new tests/test_questions.py (14 cases); updated test_commands_phase2, test_blackbox, test_planning. pyright 0 errors, pytest 274 passed.
- 2026-11-07 23:39 symphony: permission denied: Bash (python3 - <<'EOF'
import re
p='src/symphony/tasks.py'
s=open(p).read()
s=s.replace("from dataclasses import asdict, data)
- 2026-11-07 23:39 symphony: permission denied: Bash (grep -n "validate_command\` \|attempt\` \|^| \`attempt\|{{ attempt }}\|base_branch" SPEC.md)
- 2026-11-07 23:42 symphony: done: work-running -> work-review: validation passed (turns 2, $1.88): Questions are now sidecar records with ids (q1, q2, ...). The agent reports them in its outcome, and Symphony renders `## Questions` and adds `question list|show|answer`. `uv run pyright` reports 0 errors and `uv run pytest -q` passes (274 tests, including the new `tests/test_questions.py`); the work is committed on the branch.
- 2026-11-07 23:46 symphony: work.accept: work-review -> done: merged 68ccd9e, validated
