---
priority: 3
depends_on: ["split-spec-md-into-docs-spec-chapters"]
---
# Dissolve phase sections of the spec into topic chapters

After the SPEC split, fold the sections that read as build plans or backlog into the topic chapters of docs/spec/. Read docs/spec/README.md first.

Decisions already made by the human:
- The "Planning phase" and "Task dependencies" sections describe how those features were built. Keep what is still true as reference text inside the topic chapters (states and transitions, orchestrator, prompts, task files, config) and drop the build-plan parts: "Fake claude additions", "Black-box tests to add" and similar. The tests themselves are the record of those.
- The "Verified Claude Code behavior" section keeps its date and Claude Code version, and moves into the chapter on running Claude Code.
- The "Later" section becomes a short backlog file, docs/spec/backlog.md, linked from the index.
- Rationale ("we do X because Y") that is not needed to understand the behavior should be flagged in your log as an ADR candidate, not rewritten. Do not write ADRs in this task.

Done when:
- No chapter is named after a development phase or version.
- Every fact in the removed sections is either in a topic chapter, deliberately dropped as a build plan (listed in the log), or listed as an ADR candidate.
- The index is updated, references to the old chapter names are fixed, and pyright and the tests pass.

## Plan
### Approach

First add drift tests, then rewrite the spec. The spec currently has two chapters that read as build plans (`planning.md` titled "Planning phase (v0.2)", `dependencies.md`), a "Verified Claude Code behavior (2.1.220, 2026-11-06)" section inside `implementation-notes.md`, and `later.md` ("Later (explicitly out of v0)"). Do four things:

1. Dissolve `planning.md` into the topic chapters. Keep reference text, drop build-plan parts.
2. Dissolve `dependencies.md` the same way.
3. Move the verified-behavior section, with its date and version, into `running-claude.md`.
4. Replace `later.md` with a short `backlog.md`.

Then fix every cross-reference and update the index and CLAUDE.md.

Work from the current text of each file, because line numbers drift as you edit. Do not paraphrase behavior statements. Move them nearly verbatim, adapting only the `chapter, Section` references. Em-dashes are not allowed in the prose.

### Fact inventory and destination

### planning.md

| planning.md part | Destination |
|---|---|
| Status bullets: `--exit-when-idle` also waits on `plan-todo/` | cli (the `run` flag description), plus orchestrator if the idle rule lives there. Dependencies' idle rule goes beside it. |
| `plan_approved` set on `plan.accept` so a later stop or retry does not re-plan | states, Sidecar state (the `plan_approved` field) |
| `#` and `##` headings in `plan`, `assumptions` and question text rewritten as `###` | task-files, Write discipline (writing agent output into sections) |
| `prompts.plan` replaces the default whole; `prompts.plan_revise` replaces the revise prompt; default `plan` is the `WORKFLOW.md` body followed by the sentence | prompts, Built-in defaults, with the two default texts |
| Planning protocol variant lives in `prompts.PLAN_PROTOCOL`; budget caps apply to planning | prompts, Protocol prompt (planning variant) and running-claude, Invocation (`--max-budget-usd`) |
| STATE column in `task list` is the folder name | observability and cli (`task list`), if not already stated |
| Goal: opt-in per task or via `require_plan`; planning can read but not change; plan comes back as structured output and Samba writes it | states (new "Planning stage" subsection under States, a short overview), or the top of the planning run text in running-claude |
| States and flow diagram, reconcile/stop/shutdown/recovery per running folder, retry back to the todo folder of the same stage, give-up reflection skipped for planning, giving up goes to `stuck/` | states (flow diagram after the table; the table already has the rows). Retry and backoff and the reflection skip go in orchestrator, Failures and retries. Recovery is already in orchestrator, Startup. |
| Dispatch rules 1-3 and "nothing is inferred" | orchestrator, Tick step 3 (spell out the three-way stage decision and `last_stage`). states already says approval is only the `plan.accept` row. |
| Hand move `plan-review -> work-todo` observed as `plan.accept`; rejected plan moved to `work-todo` is illegal | already in states, Observed hand moves. Check and add only what is missing. |
| Attempt reset applies to planning too | already in orchestrator, Failures and retries. |
| The planning run: permissions, model, session, one invocation, outcome schema, protocol prompt content, writing the result, transitions | running-claude, new section "Planning run": the differences from a work run, the schema as a second code block beside the work schema, and the transitions. The prompt content goes to prompts, Protocol prompt. The result-writing rules go to task-files, Write discipline: replace the whole `## Plan` section, create before `## Log` or at the end, never duplicate it, same for `## Assumptions`, render `## Questions`, append a `## Log` line with the summary. |
| Executing an approved plan: fresh session, extra protocol rule, rework keeps `plan_approved` and resumes the session | prompts, Protocol prompt (extra rule when `plan_approved`) and states, Sidecar state or the flow text |
| Config block (`planning.require_plan`, `model`, `allow`) | workflow-config, Config. Check it is already in the YAML there, add the comments if missing. |
| Sidecar and status: `plan_session_id`, `plan_approved`, `last_stage`, `blocked_cause`; old `phase` ignored; `task new` creates in `plan-todo/`, `--skip-plan` uses `work-todo/` | states, Sidecar state (the last sentence already covers old fields); cli, `task new` |

### Dropped as build plan (list in the log)

- "Fake claude additions" (the `plan`, `assumptions` and `questions` step fields of `tests/fake_claude.py`). `fake_claude.py` is the record.
- "Black-box tests to add" items 1-11.
- The tests/test_layout.py, test_transitions.py and test_dependencies.py lists.
- "All existing tests must keep passing" and "tests that moved a running task to done by hand now move it to discarded".
- The "Status: implemented, details settled" framing sentence itself.

### dependencies.md

Move the guard and its behavior into reference text:

- Front matter `depends_on`, guard `deps_met`, `done` means merged, `discarded` does not count, and the guard gates planning as well. Destination: task-files, Format (field) and states (guard description).
- Waiting does not count toward `max_concurrent`. Unknown id is unmet, with the `unknown_dependency` warning once per pair. `dependency_discarded` and `dependency_cycle` stuck rows, cycle definition, and a task that only depends on a cycle keeps waiting. Destination: orchestrator, Tick step 3, as a subsection "Dependencies". The table rows are already in states.
- `task list` "waiting on" text: observability and cli (already referenced).
- `--exit-when-idle` rule: cli, `run`.
- A non-list `depends_on` is ignored: task-files, Format (already says so).

### Verified Claude Code behavior

Move the whole section, with the heading's version and date ("Verified Claude Code behavior (2.1.220, 2026-11-06)"), to the end of `running-claude.md`. Keep every bullet, including the dated 2026-11-07 ancestor memory file finding and the read-only planning finding. Retarget its internal references: "planning, The planning run" becomes "running-claude, Planning run", and "see running-claude, User config isolation" becomes "above". `prompts.md` and `workflow-config.md` cite "implementation-notes, Verified Claude Code behavior": change these to "running-claude, Verified Claude Code behavior".

### later.md to backlog.md

`git mv docs/spec/later.md docs/spec/backlog.md`. Retitle it "Backlog" and keep the eight items as a short list:

- Reviewer pass.
- Gardening.
- Other task stores (retarget its "states, Task store interface" reference; this stays valid).
- PR creation and CI feedback.
- Agent SDK runner.
- Live reload of `WORKFLOW.md`.
- Automatic subtask creation from a plan with dependency tracking. Drop the "blocked by" aside only if it is now implemented by `depends_on`. Otherwise keep it and note that `depends_on` exists.
- Plans committed into the repo.

Drop the "v0" wording from the title, since "v0" is a version name. Describe it as "ideas not built yet". The overview chapter's "v0 non-goals" may point at it: grep `overview.md` and fix.

### ADR candidates to list in the log, not rewrite

While moving text, flag these "we do X because Y" statements and do not rewrite them. Keep the behavior statement, and keep the Y only where it is needed to understand the behavior. Add the rest to the log:

- Do not use `--permission-mode plan` because it writes to `~/.claude/plans/` and switches model. This is evidence; keep it in the verified-behavior bullet.
- Fresh session for execution after approval, because the plan must stand on its own.
- A separate `plan_session_id`.
- Planning always uses `dontAsk` and its own allow list regardless of `claude.*`.
- No `phase` sidecar field, because the folder name carries the stage.
- Approval is only an explicit row, nothing inferred.
- The give-up reflection turn is skipped for planning.
- Planning is opt-in per task.
- `done` means merged, so a dependent task's worktree contains the dependency's work.
- An unknown dependency id is unmet so a typo never unblocks.
- The `--exit-when-idle` exemption for dependency-held tasks, so a human-held dependency cannot hang it.
- Plus any further "because" found in implementation-notes (for example the Rust rewrite and the black-box suite choice, and the rejected alternatives under User config isolation).

### Steps

- [ ] Read `docs/spec/README.md`, then `task-files.md`, `workflow-config.md`, `cli.md`, `observability.md`, `layout.md` and `overview.md` in full. These were not read during planning. Note what each already says about planning and dependencies, so nothing is duplicated.
- [ ] Add the drift tests first, in `tests/test_spec_docs.py`. It reads files only and must not import `samba`.
  - [ ] No chapter filename or first heading names a development phase or version. Check `re.search(r"\bv\d|phase|\blater\b", name or heading, re.I)`. This fails now for `planning.md` ("Planning phase (v0.2)") and `later.md`.
  - [ ] `backlog.md` exists, `later.md`, `planning.md` and `dependencies.md` do not, and the index links `backlog.md`. The existing test already requires the index links to equal the chapter set.
  - [ ] No spec chapter or other tracked file references the removed chapters. Match `\b(planning|dependencies|later), [A-Z]` and `implementation-notes, Verified`. Skip `docs/adr/`.
  - [ ] `running-claude.md` contains a heading starting `## Verified Claude Code behavior` with a version and an ISO date, and `implementation-notes.md` does not contain that heading.
  - [ ] Run `uv run pytest -q tests/test_spec_docs.py` and confirm the new tests fail for the right reason.
- [ ] Fold the planning content into the topic chapters per the table above.
  - [ ] states.md: add the planning stage overview, the flow diagram, and the `plan_approved` rationale in Sidecar state. Fix the `plan-todo` and `plan-review` table cells, the `deps_met` guard text, the `plan_session_id` bullet (currently "planning, planning, Sidecar and status"), and the `blocked_cause` line citing "dependencies". Add the dependency behavior as a "Dependencies" subsection. Keep the `<!-- transitions:begin/end -->` block byte-identical, because a test checks it against `samba dev transitions`.
  - [ ] orchestrator.md: expand Tick step 3 with the three dispatch rules and the dependency waiting rules. Add a "Planning worker" note to the Worker section, or refer to running-claude, Planning run. Extend Failures and retries with planning retry and the reflection skip.
  - [ ] running-claude.md: add "Planning run" (permissions, model, session, one invocation, outcome schema, transitions) and the budget cap remark.
  - [ ] prompts.md: add the planning protocol variant, the `plan` and `plan_revise` defaults and their override behavior, and the approved-plan extra rule. Fix the table references.
  - [ ] task-files.md: add the result-writing rules and the heading demotion rule to Write discipline. Check that the Format section covers `depends_on` and the Plan and Assumptions sections.
  - [ ] workflow-config.md: ensure the `planning:` block and its comments are complete and fix the references.
  - [ ] cli.md and observability.md: fix references; add the `--exit-when-idle` plan-todo rule and the STATE column note if missing.
- [ ] Move the "Verified Claude Code behavior (2.1.220, 2026-11-06)" section into running-claude.md. Retarget references in prompts.md and workflow-config.md. Update the implementation-notes bullets that pointed to it (the "Isolation results" bullet).
- [ ] Update the implementation-notes intro in the index description: it no longer carries the verified behavior.
- [ ] `git mv docs/spec/later.md docs/spec/backlog.md` and retitle. Check the overview chapter for a "Later" link.
- [ ] `git rm docs/spec/planning.md docs/spec/dependencies.md`.
- [ ] Update `docs/spec/README.md`.
  - [ ] Remove the planning and dependencies lines.
  - [ ] Replace the `later.md` line with `backlog.md` ("read to see ideas not built yet").
  - [ ] Change the implementation-notes line to drop "the verified Claude Code behavior".
  - [ ] Extend the one-line "read when" descriptions of states, orchestrator, prompts, task-files, workflow-config and running-claude to cover planning, dependencies and verified behavior. Keep one line per chapter.
- [ ] Fix every other reference.
  - [ ] `CLAUDE.md` chapter list (line 10: drop `later`, `planning` and `dependencies`, add `backlog`; line 33: `deps.py` points at `docs/spec/dependencies.md`, retarget to `docs/spec/states.md` and `orchestrator.md`).
  - [ ] `docs/manual.md` lines about 99, 151 and 156 ("Spec chapter planning", "Spec chapter dependencies"): retarget to the new chapters, for example "Spec chapters running-claude and orchestrator".
  - [ ] Docstrings and comments in src and tests: `src/samba/deps.py:1`, `src/samba/claude.py:30`, `src/samba/transitions.py:35` (`spec: implementation-notes`, which stays valid), `src/samba/orchestrator.py:417` and `:284`, `src/samba/prompts.py`, `tests/test_planning.py:1`, `tests/test_questions.py:1`, `tests/test_dependencies.py:1`. Do a final `grep -rnE "spec: (planning|dependencies|later)|(planning|dependencies), " src tests docs CLAUDE.md README.md` to confirm none remain.
- [ ] Write the `## Log` in the task file. List what was moved where, the facts deliberately dropped as build plan (the list above), and the ADR candidates (the list above). Say that the spec details settled while moving, if any, are recorded here.
- [ ] Run `uv run pyright` (must be 0 errors) and `uv run pytest -q` as separate plain commands.

### Files to change

- docs/spec/README.md
- docs/spec/states.md
- docs/spec/orchestrator.md
- docs/spec/running-claude.md
- docs/spec/prompts.md
- docs/spec/task-files.md
- docs/spec/workflow-config.md
- docs/spec/cli.md
- docs/spec/observability.md
- docs/spec/implementation-notes.md
- docs/spec/overview.md (only if it links later or planning)
- docs/spec/later.md renamed to docs/spec/backlog.md
- docs/spec/planning.md and docs/spec/dependencies.md (deleted)
- CLAUDE.md
- docs/manual.md (spec pointers only)
- src/samba/deps.py, claude.py, orchestrator.py and prompts.py (docstring and comment references only; no behavior change)
- tests/test_spec_docs.py (new drift tests); docstring references in tests/test_planning.py, tests/test_questions.py and tests/test_dependencies.py
- the task file's `## Log`

### Risks

- **Silent fact loss.** The inventory table is the checklist. After the edits, diff the old text against the new chapters: `git show HEAD:docs/spec/planning.md` and `git show HEAD:docs/spec/dependencies.md`. Tick off each bullet.
- **Transition table drift.** Editing states.md near the generated block could break `tests/test_transitions.py`, which compares the block with `samba dev transitions`. Do not touch the block.
- **Index test.** `test_index_links_every_chapter_and_every_link_resolves` requires the links to equal the chapter set exactly, so delete and rename files in the same change as the index.
- **Stale test.** `test_no_stale_references_outside_the_adrs` only forbids the old SPEC.md name. Keep it passing.
- **Reference style.** The spec's cross-references are `chapter, Section` text, so renamed sections or chapters leave dangling ones. The grep in the steps catches them. After merging text into running-claude, do not leave "planning, planning, Sidecar and status" style leftovers.
- **Duplicate rules.** Several rules are already in states and orchestrator. Merge rather than copy, to avoid two copies that drift.
- **Rationale rewrite.** Do not rewrite "because" statements. Flag them in the log only.
- **Test file names.** `tests/test_planning.py` and `tests/test_dependencies.py` are test names, not chapters; leave them.

### How to verify

- `uv run pytest -q tests/test_spec_docs.py`: the new drift tests pass (they failed before the change).
- `uv run pyright`: 0 errors.
- `uv run pytest -q`: the full suite passes, including `tests/test_transitions.py`, `tests/test_manual.py` and the black-box suites (about 25 s).
- `ls docs/spec` shows no `planning.md`, `dependencies.md` or `later.md`, and shows `backlog.md`.
- `grep -rnE "planning\.md|dependencies\.md|later\.md" .` outside `.git` and `docs/adr` returns nothing.
- The first heading of every spec chapter is topic-named (no "phase", no "v0.x").
- `running-claude.md` has "Verified Claude Code behavior (2.1.220, 2026-11-06)" with all the bullets of the original, and `git diff` shows them moved rather than reworded.
- The task file `## Log` lists the dropped build-plan parts and the ADR candidates.

### Suggested subtasks

Not needed. The work is one coherent doc refactor with interlocking references, so one session is safer than splitting.

## Assumptions
- Both planning.md and dependencies.md are deleted. Their names describe a build phase or a feature rollout rather than a topic chapter, and the task says to dissolve them.
- implementation-notes.md keeps its name and its remaining bullets (stack, black-box test strategy, fake claude, auth check, SAMBA_DEBUG_FIRE_DELAY). Only the "Verified Claude Code behavior" section leaves it. The fake-claude bullet there is a description of the harness, not a build plan, so it stays.
- The v0.2 "Status: implemented, details settled" bullets are still-true behavior and go into topic chapters. Where a fact already exists in a topic chapter (for example the transitions table in states), do not duplicate it; cross-reference instead.
- Documents under docs/adr/ are not edited. docs/manual.md only gets its "Spec chapter planning" and "Spec chapter dependencies" pointers retargeted.
- "ADR candidate" means a line in the task's `## Log`, not a file. No ADR is written.
- Section titles that were "Planning, X" or "Dependencies" are replaced with the name of the new host chapter and section in the `chapter, Section` reference style used elsewhere.

## Questions
### q1 (round 1, answered)

Please run `git rm docs/spec/later.md docs/spec/planning.md docs/spec/dependencies.md` and commit, or allow `git rm` for those paths and re-run me. Do you want to do the deletion yourself?

Context: I created `docs/spec/backlog.md` and moved all the content, but I may only run `git rm SPEC.md`, so I could not delete these three files. The 4 failing tests pass once they are gone: the index must match the chapter set, no chapter may be phase-named, and the old names must not exist.

Answer: Done: I ran git rm on those three files in your worktree (staged, not committed). Commit and re-run validation.

## Log
- 2026-11-08 15:37 samba: dispatch_plan: plan-todo -> plan-running
- 2026-11-08 15:38 samba: planned: plan-running -> plan-review: planned (turns 1, $0.36): Fold planning.md and dependencies.md into states, orchestrator, prompts, task-files, workflow-config, running-claude, cli and observability, move the verified-behavior section into running-claude, turn later.md into backlog.md, fix every `planning,` and `dependencies` cross-reference, and add drift tests.
- 2026-11-08 16:16 samba: plan.accept: plan-review -> work-todo
- 2026-11-08 16:16 samba: dispatch_work: work-todo -> work-running
- Progress: all content moves, references, index, CLAUDE.md, manual, docstrings and drift tests are done and committed. pyright is 0 errors. `backlog.md` was created with Write (content of `later.md`, retitled "Backlog", "Ideas not built yet").
- BLOCKED on deletions: `git mv docs/spec/later.md ...` and `git rm docs/spec/planning.md docs/spec/dependencies.md` were denied (only `git rm SPEC.md` is allowed). The human must run `git rm docs/spec/later.md docs/spec/planning.md docs/spec/dependencies.md` (and commit). Until then 4 tests in tests/test_spec_docs.py fail only because those 3 files still exist; all other tests pass (checked spec_docs, transitions, manual).
- Moved: planning.md "Status" bullets, Goal, States and flow -> states ("Planning stage", `plan.accept` text, `plan_session_id`/`plan_approved` bullets), orchestrator (Tick step 3 dispatch rules, Worker note, retry and reflection skip), cli (`--exit-when-idle`), observability (STATE column). Planning run (permissions, model, session, schema, transitions) -> running-claude "Planning run". Prompts (`plan`, `plan_revise`, overrides, planning protocol variant, approved-plan rule, fresh session) -> prompts. Result-writing and heading demotion -> task-files Write discipline. Config block comments -> workflow-config. dependencies.md -> states (guard `deps_met`, "Dependencies" intro) and orchestrator "Dependencies" subsection. Verified Claude Code behavior (2.1.220, 2026-11-06), all bullets verbatim -> running-claude. later.md -> backlog.md; the "blocked by" aside now notes `depends_on` exists.
- Settled while moving: overview.md first heading "Samba: Specification v0" became "Samba: Specification" (a version in a chapter title); overview Non-goals now points at backlog. Spec details otherwise unchanged. The `--exit-when-idle` plan-review/work-review remark was moved into cli and orchestrator.
- Dropped as build plan: "Fake claude additions" (fake_claude.py is the record); "Black-box tests to add" items 1-11; the tests/test_layout.py, test_transitions.py, test_dependencies.py lists; "All existing tests must keep passing" and "tests that moved a running task to done by hand now move it to discarded"; the "Status: implemented, details settled" framing.
- ADR candidates (not rewritten): fresh session for execution after approval (plan must stand alone); separate `plan_session_id`; planning always `dontAsk` with its own allow list regardless of `claude.*`; no `phase` sidecar field since the folder carries the stage; approval only as an explicit row, nothing inferred; give-up reflection skipped for planning; planning opt-in per task; `done` means merged so a dependent worktree has the dependency's work; unknown dependency id is unmet so a typo never unblocks; `--exit-when-idle` exemption for dependency-held tasks; not using `--permission-mode plan` (kept as evidence in verified behavior); Rust rewrite and black-box suite choice (implementation-notes); the rejected alternatives under running-claude User config isolation (`--bare`, `--safe-mode`, `--disable-slash-commands`, empty `CLAUDE_CONFIG_DIR`); the `claude.allow` in WORKFLOW.md rather than repo settings (workflow-config, Permissions).
- 2026-11-08 16:20 samba: permission denied: Bash (grep -rnE "\b(planning|dependencies|later|implementation-notes)(,| \(|\)|$)|planning\.md|dependencies\.md|later\.md|[Pp])
- 2026-11-08 16:20 samba: permission denied: Bash (git mv docs/spec/later.md docs/spec/backlog.md)
- 2026-11-08 16:20 samba: permission denied: Bash (git rm -q docs/spec/planning.md docs/spec/dependencies.md)
- 2026-11-08 16:20 samba: work_blocked: work-running -> question: blocked (turns 2, $1.18): All the content is moved into the topic chapters and committed. The three old chapter files still exist because my `git rm` and `git mv` calls were denied. 4 tests in `tests/test_spec_docs.py` fail only because of that. pyright reports 0 errors. I haven't run the full `uv run pytest -q`. The files I ran (`test_spec_docs.py`, `test_transitions.py`, `test_manual.py`) pass apart from those 4.
- 2026-11-08 16:26 samba: question.answer: dissolve-phase-sections-of-the-spec-into-topic-chapters/q1 answered
- 2026-11-08 16:26 samba: question.answer: question -> work-todo
- 2026-11-08 16:27 samba: dispatch_work: work-todo -> work-running
- 2026-11-08 16:32 samba: done: work-running -> work-review: validation passed (turns 3, $2.07): I committed the deletion of `later.md`, `planning.md` and `dependencies.md`. The planning and dependency content now lives in the topic chapters, `backlog.md` replaces `later.md`, and the new drift tests pass. `uv run pyright` reports 0 errors and `uv run pytest -q` passes all 285 tests.
- 2026-11-08 19:05 samba: work.accept: work-review -> done: merged b31908d, validated
