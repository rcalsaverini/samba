# 08: Explore, planning and the handoff between them

Status: partly decided. The owner chose option A (two sessions, one role, files as the handoff), with a
middle ground. Explore is NOT yet decided as a command or a skill.

## Decided

- Two sessions, files as the handoff. Explore ends by writing ADRs and supplemental documents (technical
  designs, light specs), including paths not taken. The Designer reads them fresh and writes the detailed
  technical plan.
- Why not the other way: a resumed interactive session is a long context resumed headlessly, and its cost
  and behavior were never verified. The owner's concern (the Designer's memory is only as good as what
  was written down) is accepted; the answer is to escalate to the owner, not to keep a long session.
- How planning tasks are born: (1) Explore decomposes, writing task stubs (title, intent, depends_on)
  next to the ADRs, approved by the owner inside the session. (2) Reviewer nits and ADR candidates become
  backlog items the owner promotes. (3) A proposer agent suggesting stories is a LATER option; only once
  the queue runs dry. A proposer only queues candidates; the owner promotes them.

## Open

- Is `samba explore` a Samba command, or only a Claude Code slash command or skill? ADR 0002 left this
  open. The current code has `samba explore` as a thin launcher (`StartExplore`, `TerminalSession`).
  Samba gains little beyond passing a fixed allow list (ADR 0004). Lean: keep the launcher, and ask.
- The TEP name (file 02).
- Whether an Epic is one file or a folder with its TEP and tasks inside.
- Whether the Designer resumes its session to answer a Reviewer or starts fresh (file 01).
- Whether Explore's ADRs go straight to `proposed` and the owner accepts them with `samba adr accept`
  (current behavior, ADR 0003/0004) or in-session. Current behavior is the default.

## Constraints from accepted ADRs

- ADR 0003: agents consult ADRs through `samba adr list|show`.
- ADR 0004: the explorer spawns tasks but never accepts. Task stubs from Explore must follow this: the
  Explorer writes stubs, the owner approves them.
- ADR 0005: state is the folder a file sits in (today's model).
