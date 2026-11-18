---
priority: 3
depends_on: ["dissolve-phase-sections-of-the-spec-into-topic-chapters"]
---
# Make the spec update an explicit step of every task

Today WORKFLOW.md only says "update the spec if you had to settle a detail", which is optional and drifts. Make updating the spec a gate at plan, work and review. Read ADR 0001 and docs/spec/README.md first.

Decisions already made by the human:
- The plan gets a required section, "Spec changes": the docs/spec chapters the task will change with one line of intent each, or "none, because ...".
- The work prompt requires making those edits on the task branch before reporting done, and the log says what changed. The spec diff is reviewed next to the code diff at work accept.
- If the task made a real decision (a choice between alternatives with a lasting reason), the agent also proposes an ADR in docs/adr/ with status proposed, one decision per file, as in ADR 0001.
- No new folders, no delta files, no archive step. The spec and code merge together through work accept.
- Keep it light: the repo's WORKFLOW.md prompt body, the built-in prompts and the protocol prompt carry the rule. Do not add machinery that checks prose.

Done when:
- The plan prompt, work prompt and the repo's WORKFLOW.md body implement the above, with black-box tests (fake claude) showing the plan section is requested and the work prompt mentions the step.
- The prompts chapter of docs/spec and the user manual describe it.
- pyright and the tests pass.

## Plan
### Approach

Make the spec update a gate at three points, using prompt text only and no new code paths:

1. **Plan.** `PLAN_PROTOCOL` requires a section "Spec changes". It lists the chapters or files of the project's spec the task will change, one line of intent each, or "none, because ...". The Samba-owned prompts say "the project's spec" and never name a path, because they go to every repository that uses Samba and only this repository keeps its spec in `docs/spec/`.
2. **Work.** `PROTOCOL` (the Samba-owned protocol prompt for every work run) gets a rule. Before reporting `done`, make the spec edits on the task branch (the repo's WORKFLOW.md body says where the spec lives). If an approved plan has a "Spec changes" section, that section is the list of edits. Log in `## Log` what changed in the spec. If the task made a real decision (a choice between alternatives with a lasting reason), also add a proposed ADR in `docs/adr/`, one decision per file, in the format of ADR 0001: front matter with `status: proposed`, `date` and `supersedes`, then Context, Decision, Consequences. The next number comes from the existing filenames.
3. **Repo policy.** The WORKFLOW.md body replaces the optional "Update the spec ... if your implementation had to settle a detail" sentence with the explicit step, and is the only place that names `docs/spec/` (start at `docs/spec/README.md`). It also says the spec diff is reviewed with the code diff at `work accept`. `docs/adr/` is named in the protocol prompt, since ADRs 0001 to 0003 make it a Samba convention.

There are no new folders, delta files, archive step or checker. The spec and code merge together through `work accept`.

### Steps
- [ ] Read `tests/test_planning.py`, `tests/test_blackbox.py` (around line 259) and `tests/conftest.py` to see how the fake records the system prompt and the first-turn prompt. Pick the existing helpers to reuse.
- [ ] Write the tests first (below). Run them and confirm they fail.
- [ ] Edit `PLAN_PROTOCOL` in `src/samba/prompts.py`. Add "Spec changes" to the required section list, after Files to change, with a sentence on its content. Say "the project's spec", with no path. Check that the existing plan tests still pass.
- [ ] Edit `PROTOCOL` in `src/samba/prompts.py`. Add the spec-step bullet (again "the project's spec", no `docs/spec`) and the ADR bullet (this one names `docs/adr/`). Keep the plain wording, with no em-dashes. Keep `APPROVED_PLAN_RULE` and add "its Spec changes section lists the spec edits you owe" to it.
- [ ] Edit the repo `WORKFLOW.md` body (lines 50-53) as described in Approach, point 3: it names `docs/spec/` and `docs/spec/README.md`.
- [ ] Update `docs/spec/prompts.md`. In "Protocol prompt", add the spec-step and ADR rules. In "Planning variant", add "Spec changes" to the section list. In "Executing an approved plan", mention that the section drives the spec edits. In "What the WORKFLOW.md body should tell the agent", add that the body should keep the spec step. Check `docs/spec/README.md` and the other chapters for plan section lists (`grep "Files to change"`) and fix them.
- [ ] Update `docs/manual.md`. In section 4 (Review the plan), say that the plan has a "Spec changes" section to check. In section 6 (Accept the work), say the diff includes spec edits and maybe a proposed ADR, and that accepting an ADR means changing its status to `accepted` in a follow-up commit by the human. Keep `tests/test_manual.py` passing.
- [ ] Run `uv run pyright` and `uv run pytest -q` as separate commands. Add a `## Log` line saying that the spec was updated and what changed.

### Tests (black-box, in `tests/test_planning.py` and `tests/test_blackbox.py`, no `samba` import)
- Planning run: the `--append-system-prompt` argv value contains "Spec changes" and "none, because".
- Work run, no plan: the `--append-system-prompt` value mentions updating the spec before reporting done, the `## Log` line and the proposed ADR in `docs/adr/` (assert on stable substrings such as "spec", "docs/adr" and "proposed", and assert that "docs/spec" does not appear in the Samba-owned prompt).
- Work run after plan approval: the same assertions, plus the approved-plan rule.
- If the fake exposes the first-turn prompt, assert that the repo WORKFLOW.md rule survives rendering. Otherwise write a test that reads the repo's `WORKFLOW.md` from disk and asserts it mentions "Spec changes" and "docs/spec", in the same style as `test_manual.py`.

### Files to change
- `src/samba/prompts.py`: `PLAN_PROTOCOL`, `PROTOCOL`, `APPROVED_PLAN_RULE`.
- `WORKFLOW.md` (body only).
- `docs/spec/prompts.md` (and any other spec chapter listing plan sections).
- `docs/manual.md`.
- `tests/test_planning.py`, `tests/test_blackbox.py` (and `tests/conftest.py` only if a helper is needed).

### Spec changes
- `docs/spec/prompts.md`: planning variant gets the "Spec changes" section. The protocol prompt gets the spec-step rule (generic, no path) and the proposed-ADR rule. The WORKFLOW.md guidance names `docs/spec/` and mentions the step, and says that path-specific policy belongs in the repo's WORKFLOW.md body.
- Other `docs/spec` chapters: only if they list the plan sections (checked with grep). Otherwise none.
- ADR: none proposed. This task applies the decision the human already made, and ADR 0001 already covers the format. The executing agent may propose one only if it finds a real new choice.

### Risks
- Prompt text drifts from the spec. Mitigated by editing both together and asserting on the stable key phrases only.
- `PROTOCOL` runs every work turn. Keep the added text short so it does not weigh on the budget caps (spec: Planning variant, "same budget caps"). Check that no existing test pins the exact protocol text.
- Tasks that change no behavior need an escape. The "none, because ..." form in the plan, and a one-line log note in work, cover this.
- Template rendering is strict. Do not introduce `{{ }}` text in the new rules (the ADR number example must not use braces).
- ADR number collisions across branches are accepted by ADR 0001 (the later merge renumbers). Do not add machinery for it.

### How to verify
- `uv run pytest -q` (new tests pass, old ones unchanged) and `uv run pyright` reports 0 errors, each as a separate command.
- Read the rendered `PLAN_PROTOCOL` and `PROTOCOL` once, and check that the spec chapter, the manual and the WORKFLOW.md body all say the same thing.
- Search for em-dashes in the changed prose.

### Suggested subtasks
None. The task is small enough to run as one.

## Assumptions
- "Built-in prompts and the protocol prompt carry the rule" means `PLAN_PROTOCOL` and `PROTOCOL` in `src/samba/prompts.py`, which users cannot override. The configurable defaults (`plan`, `continue`, ...) stay as they are, apart from a possible short mention in `plan`.
- The plan sections are required by wording in the prompt only. Nothing checks the plan text, as the task says.
- Decided by the human after plan review: Samba-owned prompts stay repo-agnostic ("the project's spec"), and the `docs/spec` path lives only in this repo's WORKFLOW.md body ("policy lives in the repo"). `docs/adr/` may be named in the protocol, as ADRs 0001 to 0003 make it a Samba convention.
- The ADR rule applies to work runs only. The plan may note a likely ADR inside "Spec changes", but the file is written during work.
- The repo's WORKFLOW.md at the repo root is edited. Other copies (for example a template in tests or docs) are changed only if one exists and has the same sentence.
- `--append-system-prompt` is visible in the fake's recorded argv, as `tests/test_planning.py:68` shows. I did not check where the fake records the user prompt (the WORKFLOW.md body). The WORKFLOW.md assertion may need `fake_claude.py`'s recorded stdin or argv.

## Feedback
### Round 1

Change from the plan review: the Samba-owned prompts (PLAN_PROTOCOL, PROTOCOL, APPROVED_PLAN_RULE) must say 'the project's spec' and never name docs/spec, because they go to every repo that uses Samba. docs/spec/ and docs/spec/README.md are named only in this repo's WORKFLOW.md body. docs/adr/ may stay in the protocol. Update the tests: assert 'spec' (not 'docs/spec') in the protocol prompts, assert 'docs/spec' is NOT in them, and assert WORKFLOW.md mentions 'Spec changes' and 'docs/spec'. Update docs/spec/prompts.md and docs/manual.md to match. The plan in the task file now describes this.

## Log
- 2026-11-08 19:05 samba: dispatch_plan: plan-todo -> plan-running
- 2026-11-08 19:06 samba: planned: plan-running -> plan-review: planned (turns 1, $0.22): Put the "Spec changes" rule in the Samba-owned plan and work protocol prompts and in the repo's WORKFLOW.md body, with fake-claude black-box tests and matching spec and manual updates.
- 2026-11-09 10:48 samba: plan.accept: plan-review -> work-todo
- 2026-11-09 10:48 samba: dispatch_work: work-todo -> work-running
- 2026-11-09 10:48 samba: recover: work-running -> work-todo: stopped by shutdown
- 2026-11-09 10:48 samba: dispatch_work: work-todo -> work-running
- 2026-11-09 10:48 samba: task.stop: work-running -> stuck
- 2026-11-09 10:49 samba: task.retry: stuck -> work-todo
- 2026-11-09 10:50 samba: dispatch_work: work-todo -> work-running
- Implemented: PLAN_PROTOCOL (Spec changes section), PROTOCOL (spec step + proposed ADR rule), APPROVED_PLAN_RULE, WORKFLOW.md body. Black-box tests added in test_planning.py and test_blackbox.py (the WORKFLOW.md check reads the file from disk). pyright 0 errors, 288 tests pass.
- Spec updated: docs/spec/prompts.md (planning variant, protocol prompt, approved-plan rule, WORKFLOW.md guidance). docs/manual.md sections 4 and 6 describe the Spec changes section and the proposed ADR. No ADR proposed.
- 2026-11-09 10:58 samba: done: work-running -> work-review: validation passed (turns 4, $0.57): The plan prompt now requires a "Spec changes" section. The work prompt and the repo's WORKFLOW.md body require the spec edits before `done`, and a proposed ADR in `docs/adr/` when the task made a real decision. Black-box tests, the prompts chapter of the spec and the manual are updated; pyright reports 0 errors and all 288 tests pass. Changes are committed on the task branch.
- 2026-11-09 11:03 samba: work.reject: work-review -> work-todo: feedback round 1
- 2026-11-09 11:03 samba: dispatch_work: work-todo -> work-running
- 2026-11-09 11:09 samba: done: work-running -> work-review: validation passed (turns 5, $1.02): The Samba-owned prompts now say "the project's spec" and never name docs/spec; only the repo's WORKFLOW.md body names it, and docs/adr/ stays in the protocol. I updated the tests, docs/spec/prompts.md and the manual to match. pyright reports 0 errors and all 288 tests pass; the changes are committed on the task branch.
- 2026-11-09 14:29 samba: work.accept: work-review -> done: merged 8a41dd2, validated
