---
status: accepted
date: 2026-11-08
supersedes: []
---

# 0001: ADRs are plain markdown files, one decision each

## Context

Decisions that shape Samba's structure currently live in chat history and in the "Decisions already
made by the human" lists of task files. They are easy to lose and agents cannot find them. We want a
durable record that humans review and agents can consult.

## Decision

- An ADR is a markdown file at `docs/adr/NNNN-short-title.md`, numbered in creation order.
- The number comes from the filename. There is no sidecar and no database: ADRs are committed and
  reviewed in git, unlike `.samba/` state, which is local runtime data.
- Front matter holds `status` (`proposed`, `accepted`, `rejected`, `superseded`), `date` and
  `supersedes` (a list of numbers).
- The body has three sections: Context, Decision, Consequences.
- **One decision per ADR.** A draft that contains two decisions is split into two ADRs, so each can be
  accepted or rejected on its own.
- An accepted ADR is never edited to change its decision. A new ADR supersedes it, and the old one
  becomes `superseded`.

## Consequences

- Reviewing a decision is reviewing a small diff, with history for free.
- Narrow scope means more files, and the numbering needs a rule when two branches add an ADR at the
  same time (the later merge renumbers).
- `samba adr` commands (see ADR 0003) parse the front matter, so the format must stay simple.
