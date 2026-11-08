---
status: accepted
date: 2026-11-08
supersedes: []
---

# 0003: Agents consult ADRs through `samba adr`, not through the prompt

## Context

Accepted ADRs describe the lasting structure of the software, so every agent may need them. Putting
all of them in every prompt costs tokens and grows without bound. Listing only the ones a task
references relies on someone remembering to reference them.

## Decision

- `samba adr list` prints accepted ADRs with number, title and a one-line summary. Superseded and
  rejected ones are hidden unless asked for (`--all`).
- `samba adr show N` prints one ADR.
- `samba adr accept|reject|supersede N` change the status in the front matter. They edit the file
  and do not commit.
- Both read commands are in the default agent allow list. The status commands are not: accepting is
  a human decision.
- The agent prompt gets one fixed paragraph: decisions shaping the architecture live in
  `docs/adr/`; run `samba adr list` and read the relevant ones before designing.

## Consequences

- Prompts stay small, and hiding superseded ADRs is the value over a plain file read.
- An agent can still skip the check. The prompt paragraph asks for it, and review catches the rest.
- The summary line needs a source: the first sentence of Decision, or a `summary` front matter field.
  To be settled in implementation.
