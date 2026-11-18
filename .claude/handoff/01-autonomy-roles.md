# 01: Roles and the autonomy boundary

Status: decided in principle, draft ADR 0022 (proposed), not on main.
Draft: `/Users/rafael.calsaverini/Dev/sandbox/symphony-autonomy-design-v2/docs/adr/0022-roles-and-the-autonomy-boundary.md`

## Problem

Samba needs too much of the owner's supervision: he reviews every plan and every work result, and
the queue stalls waiting for him. Removing him from review without a replacement is unsafe. Two
runs of the same model share blind spots, so self-review is weak evidence.

## Decided

- Five roles. Each is a separate agent session. Files are the handoff (ADR 0005).
  - Owner: the human. Approves intent: ADRs, Epics, bugfix tasks. Answers questions. Approves the
    final merge to main.
  - Explorer: an interactive session with the Owner (today `samba explore`, ADR 0002). Writes ADRs,
    Epics and backlog items, and records paths not taken.
  - Designer: writes a TEP from an Epic, then slices it into tasks. Reads what the Explorer wrote,
    with a fresh context. Answers the Reviewer's findings.
  - Reviewer: reads a TEP or tasks or finished work with a fresh context and only the documents and
    code it is given. Two lenses in one call: Architect (simplicity, reuse, ADR consistency, rot) and
    Senior Developer ("could I build this without deciding anything architectural?"). Only Blocker and
    Major findings hold work back. Nits are recorded, not acted on.
  - Implementer: today's work phase. Sees the task, its TEP section, the ADRs, the spec and the code.
    Asks a question instead of choosing when a task is ambiguous.
- Who approves what: ADR, Epic, bugfix: Owner. TEP and tasks: Reviewer, without the Owner. Finished
  work: Reviewer first, then the Owner, who gets a pre-review saying where to look.
- A plan that contradicts an accepted ADR does not pass. It becomes a question for the Owner (fix the
  plan, or supersede the ADR). A plan that only suggests an ADR passes, and the suggestion becomes a
  backlog item.
- Models are configured per role in WORKFLOW.md. The Reviewer uses a different and stronger model
  than the Designer. The owner's sandbox may use non-Claude models later. Company data may not go to
  unapproved hosts: the owner said this is sandbox-only for now.
- A role is data (prompt, tool profile, model), chosen by the use case that runs the agent. The
  runner stays a translator (principle 7). The closed `plan`/`work` kind of the agent request becomes
  a role.
- The Reviewer computes nothing itself that Samba can compute. Diff size, commit count, files outside
  the task's file list and test result come from the adapters as values (principle 3).
- The Reviewer starts in advisory mode: it critiques while the Owner still accepts. It becomes the gate
  only after its verdicts have been compared with the Owner's decisions over a few tasks.
- The Owner's "Scrum Master" (a proposer of stories) is a possible future role. Not built. A proposer
  would only queue candidates, and the Owner would promote them.

## Not decided

- Whether the Designer resumes its own session to answer a review, or starts fresh with the review
  appended. Leaning: resume, because the Designer's memory of the plan matters. Ask the owner.
- The review protocol (rounds, contests, severities, settled findings). See file 06.
- Whether a Reviewer lens can be one call with two sections, or needs two calls. Start with one call;
  split only if the lenses bleed into each other.

## Next steps

1. Owner accepts or revises draft ADR 0022 (it is in the v2 worktree).
2. Only after acceptance: the roles appear in `WORKFLOW.md` config (per-role model) and in the
   spec. Samba has no per-role config today (only `claude.model` and the planning model).
