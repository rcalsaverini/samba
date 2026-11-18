# Handoff: where Samba's design stands (2026-11-17)

Read this first. It is an index plus the working rules. Each numbered file covers one open item.
These notes are for a fresh session. They are not part of the repo, and they are not a spec.

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

- Head: 3b703c4. Recent: 5a70d9d (DDD section and principle 10 in docs/spec/principles.md, the four
  diagrams in docs/diagrams/), e5c8a8c (docs move, `samba init` with the base pack).
- ADRs on main: 0001 to 0020 accepted (0016 supersedes 0009; 0017 and 0018 accepted; 0019 and 0020
  accepted, the agent technology and the agent protocol). Newest accepted ADR text is in docs/adr/.
- `samba init --method base` exists. Only the `base` pack ships. `DEFAULT_METHOD = "base"` in
  src/samba/app/init_project.py. The `ddd-hexagonal` pack does not exist yet.
- `.claude/` in the repo root is untracked: it holds the subagent worktrees (`.claude/worktrees/`).
  Do not commit it. Consider removing those worktrees when no subagent is running.

## Files in this folder

1. `01-autonomy-roles.md`: who does what (Owner, Explorer, Designer, Reviewer, Implementer) and what
   approves what. Draft ADR 0022.
2. `02-artifact-model.md`: backlog item, ADR, spec, Epic, TEP, task, bugfix. Draft ADRs 0021 and 0023.
3. `03-docs-by-kind.md`: the four kinds of document and the follow-up doc work. Draft ADR 0024.
4. `04-ddd-hexagonal-pack.md`: step 4 of the plan, the `ddd-hexagonal` method pack.
5. `05-glossary-and-strategic-pass.md`: step 2, the glossary for Samba (needs the owner).
6. `06-review-protocol-and-escalation.md`: how the Reviewer gates, nits, rounds, contests, escalation.
7. `07-waves-merge-and-dependencies.md`: waves, the epic branch, stacked merge, dependency policy.
   Deferred. Diagrams only.
8. `08-explore-and-planning.md`: the explore command, the TEP name, the Designer's session.
9. `09-housekeeping.md`: worktrees, unmerged drafts, stale docs, open questions to the owner.

## Where the drafts live

Draft ADRs 0021 to 0025 are NOT on main. They are uncommitted files in the worktree
`/Users/rafael.calsaverini/Dev/sandbox/symphony-autonomy-design-v2` (branch `design/autonomy-model-v2`).
Read them there. 0025 was corrected: packs copy verbatim except two markers, and `.samba/` is not
created by `init`.
