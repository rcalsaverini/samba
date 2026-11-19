# Handoff: where Samba's design stands (2026-11-19)

Read this first. It is an index plus the working rules. Each numbered file covers one open item.
These notes are for a fresh session. They are tracked in git, but they are not part of the spec.

## Working rules (from the owner, Rafael)

- He is the PM. He approves intent (ADRs, Epics, bugfix tasks). Machines approve plans against that
  intent. Do not decide product direction for him; ask.
- Design goes slowly, in conversation, one decision at a time. Stall when a thread becomes too big.
  He said so explicitly.
- He wants principled pushback on design claims, not agreement.
- Commits: he said "everything goes on main" (commit 3b703c4 onward), but CLAUDE.md still requires
  asking before each new commit. Ask, then commit. Never push. Never add a Co-Authored-By or any
  attribution trailer (CLAUDE.md overrides the harness reminder).
- No em-dashes in prose, docs or prompts. Use colons, commas or parentheses.
- Accepted ADRs are never edited, only superseded. New decisions start as `status: proposed`.
- Tests: `uv run pyright` must be 0 errors. While working run
  `uv run pytest -q tests/unit tests/component tests/checks`. Run `tests/integration` after touching an
  adapter. The full `uv run pytest -q -n auto` is the last step (it was 711 passing on main at 3b703c4).
- Subagents: he asked for Sonnet subagents for settled, mechanical work. Verify their output yourself
  (their worktree may be based on an old commit; re-apply the diff onto current main, as was done for
  step 1).
- Samba is not used to build Samba for these steps: he drives the design by hand. Samba tasks are only
  used when a change needs a plan review from him.

## Current state of main

- Head: 04aa06a. Recent: 0c8bbae (merge design/autonomy-model-v2: propose ADRs 0021 to 0025 and the
  target-design diagrams), ea32498 (ADR 0026, track finished task markdown), d0a0e21 (the task files
  of finished and discarded tasks), 04aa06a (samba-agnostic ddd-hex-principles.md).
- ADRs on main: 0001 to 0026. 0001 to 0020 accepted (0016 supersedes 0009). 0021 to 0026 are
  `status: proposed`, not yet accepted. The title inside each ADR now matches its filename.
- `samba init --method base` exists. Only the `base` pack ships. `DEFAULT_METHOD = "base"` in
  src/samba/app/init_project.py. The `ddd-hexagonal` pack does not exist yet.
- The four target-design diagrams are on main in docs/diagrams/ (design, exploration, implementation,
  refinement).
- `.claude/handoff/` (these notes) is tracked in git. `.claude/worktrees/` no longer exists: no
  subagent worktrees remain. The only untracked file under `.claude/` is a `.DS_Store`.

## Files in this folder

1. `01-autonomy-roles.md`: who does what (Owner, Explorer, Designer, Reviewer, Implementer) and what
   approves what. ADR 0022 (proposed, on main).
2. `02-artifact-model.md`: backlog item, ADR, spec, Epic, TEP, task, bugfix. ADRs 0021 and 0023
   (proposed, on main).
3. `03-docs-by-kind.md`: the four kinds of document and the follow-up doc work. ADR 0024 (proposed, on
   main).
4. `04-ddd-hexagonal-pack.md`: step 4 of the plan, the `ddd-hexagonal` method pack.
5. `05-glossary-and-strategic-pass.md`: step 2, the glossary for Samba (needs the owner).
6. `06-review-protocol-and-escalation.md`: how the Reviewer gates, nits, rounds, contests, escalation.
7. `07-waves-merge-and-dependencies.md`: waves, the epic branch, stacked merge, dependency policy.
   Deferred. Diagrams only.
8. `08-explore-and-planning.md`: the explore command, the TEP name, the Designer's session.
9. `09-housekeeping.md`: worktrees, stale docs, open questions to the owner.

## Where the drafts live

ADRs 0021 to 0026 are on main, under `docs/adr/`, all `status: proposed`. The v2 worktree
(`symphony-autonomy-design-v2`, branch `design/autonomy-model-v2`) was merged and removed. The
target-design diagrams are also on main. 0025 was corrected: packs copy verbatim except two markers,
and `.samba/` is not created by `init`.
