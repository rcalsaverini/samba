# 06: Review protocol and escalation

Status: partly discussed, NO ADR written. Decided in conversation; treat as a proposal to confirm.

## Review gating

- Only Blocker and Major findings hold work back. Nits go into the final report and are NOT acted on.
  The owner can turn any nit into a task. Otherwise nits are archived.
- Nits and "ADR candidate" notes from a Reviewer go into the backlog as `open` items, once the Epic is
  designed (owner's point). The owner decides which become work.
- Settled findings: a contested or declined finding stays settled across rounds. A fixed finding
  re-opens if a later review raises it again. (Copied in spirit from the EGM plugin's resolve loop.)
- Round cap. Copied idea from EGM: stop after two consecutive clean rounds, or at 5 rounds. Reverting an
  earlier fix to satisfy a new finding stops the loop and goes to the owner. Exact numbers are NOT yet
  confirmed by the owner.
- The Reviewer is advisory until its verdicts are compared with the owner's decisions over a few tasks.
  Then it becomes the gate. Writing that switch-over down is a separate, later ADR.

## Contests (what the author may argue back)

- A contest must cite evidence the Reviewer could read: a file and symbol, or a recorded decision (an
  ADR). "This was intentional" is not evidence.
- A comprehension gap cannot be contested. If a fresh reader could not follow the document, the document
  is missing context. The author edits it. The owner's example: the goldfish's confusion is the evidence.
- A contest of a severity is not allowed without a stated reason; the Reviewer does not change its own
  severity.
- The author must not add context only to satisfy a reviewer. If only the zero-context reader needs it,
  the finding is an escalation, not a fix.

## Escalation to the owner

- A plan that CONTRADICTS an accepted ADR: blocks, and becomes a question. Either the plan is wrong or the
  ADR needs superseding; only the owner decides which.
- A plan that merely SUGGESTS a new ADR: does NOT block. It is a note, and a backlog item.
- The owner does not want to be bothered with small issues. Escalate only the decision that needs his
  judgment.
- A finding that needs knowledge outside the reviewed files (a team convention, a verbal decision) is
  an escalation, not a contest.

## Pre-review for the owner

- The Reviewer's final report (on finished work) says: what to look at first (risk-ordered), any
  spec or ADR touches, files changed outside the plan's file list, test coverage gaps, the nits and ADR
  candidates, and a "what I did not check" line.
- Samba computes the objective facts itself (boundary violations, spec edits, test results). The
  Reviewer's text does not replace them.
- Risk: the owner anchors on what the pre-review points at. Mitigation: the diff stays the source of truth.

## Open with the owner

- Exact round cap and whether it is per task or per epic.
- Whether the Reviewer's two lenses (Architect, Senior Developer) are one call with two sections (leaning
  yes) or two calls.
- Whether to keep the "product manager" lens: the owner said it is for later, since it needs written
  long-term goals. Dropped for now.
