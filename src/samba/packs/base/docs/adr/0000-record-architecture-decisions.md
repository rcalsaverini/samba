---
status: accepted
date: @@DATE@@
supersedes: []
---

# 0000: Record architecture decisions

## Context

Decisions that shape a project live in chat history and in task descriptions, where they are easy
to lose and agents cannot find them. We want a durable record that people review and agents read.

## Decision

- This project records its decisions as ADRs: markdown files at `docs/adr/NNNN-short-title.md`,
  numbered in creation order, one decision per file.
- Front matter holds `status` (`proposed`, `accepted`, `rejected`, `superseded`), `date` and
  `supersedes` (a list of numbers). The body has three sections: Context, Decision, Consequences.
- An accepted ADR is never edited to change its decision. A new ADR supersedes it, and the old one
  becomes `superseded`.

## Consequences

- Reviewing a decision is reviewing a small diff, with history in git.
- A reversed decision leaves a trail: the old ADR stays, marked superseded.
