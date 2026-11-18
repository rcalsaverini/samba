---
status: proposed
date: 2026-11-13
supersedes: []
---

# 0012: Agents have roles, and the human approves intent while machines approve plans

## Context

The human reviews every plan and every piece of work, and that is the bottleneck. Self-review by
the agent that wrote a plan misses what that agent already knows, so removing the human review
without a replacement is unsafe. Two runs of the same model also share blind spots.

## Decision

The work has five roles. Each runs as a separate agent session, and files are the handoff between
them (ADR 0005).

- **Owner**: the human. Approves intent: ADRs, Epics and bugfix tasks. Answers questions. Gives the
  final approval before anything reaches the main branch.
- **Explorer**: the interactive session with the Owner (ADR 0002). Writes ADRs, Epics and backlog
  items. Records paths not taken.
- **Designer**: writes the TEP from an Epic, then slices it into tasks. Reads what the Explorer
  wrote, with a fresh context. Answers the Reviewer's findings.
- **Reviewer**: reads a TEP, a set of tasks or a finished piece of work with a fresh context and
  only the documents and code it is given. Two lenses in one call: Architect (simplicity, reuse,
  consistency with ADRs, code rot) and Senior Developer (could I build this without deciding
  anything architectural?). Only Blocker and Major findings hold work back. Nits are written down
  and do not.
- **Implementer**: today's work phase. It sees the task, the TEP section it points at, the ADRs, the
  spec and the code. When the task is ambiguous it asks a question instead of choosing.

Who approves what:

| Artifact | Approved by |
|---|---|
| ADR, Epic, bugfix | Owner |
| TEP, tasks | Reviewer, without the Owner |
| Finished work | Reviewer first, then Owner, who gets a pre-review saying where to look |

A plan that contradicts an accepted ADR does not pass. It becomes a question for the Owner, who
either fixes the plan or supersedes the ADR. A plan that only suggests a new ADR passes, and the
suggestion becomes a backlog item.

The model is set per role in `WORKFLOW.md`. The Reviewer should use a different model than the
Designer, and a stronger one.

## Consequences

- The Owner reads less and decides more: intent and final results, not every plan.
- Reviewer agreement is weak evidence, since both agents are models. The objective checks are
  validation and tests (ADR 0008). Nothing here replaces them.
- The Reviewer cannot judge whether a plan serves the project's long-term goals, because they are
  not written down. The Owner covers that for now.
- The Reviewer starts in advisory mode: it critiques plans while the Owner still accepts them, and
  it becomes the gate only after its verdicts have been compared with the Owner's.
- A role is data, not code: a prompt, a tool profile (the Reviewer is read-only) and a model,
  chosen by the use case that runs the agent and passed in the request. The agent runner stays a
  translator and decides nothing (principle 7). Today's closed `plan` or `work` kind of the request
  becomes a role.
- The objective facts a Reviewer is shown (diff size, commit count, files outside the task's file
  list, test result) are computed outside the domain, by the adapters, and reach the rules as
  values (principle 3).
- Left to later ADRs: the review protocol (rounds, contests, severities), how reviews and merges are
  grouped for Epics, dependency policy, and which non-Claude models are allowed.
- Open: whether the Designer's answers to a review resume its own session or start a fresh one.
