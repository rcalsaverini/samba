# 09: Housekeeping, loose ends and questions for the owner

Nothing here is decided. Clean-up is safe only after checking with the owner.

## Git state (checked 2026-11-17 in the transcript; re-check before acting)

- Main: 3b703c4, not pushed. The branch is ahead of origin by commits made in this session.
- Merged branch `docs/implementation-folder` and its worktree `/Users/rafael.calsaverini/Dev/sandbox/symphony-docs-kinds`.
  Can be removed after the owner confirms.
- Worktree `/Users/rafael.calsaverini/Dev/sandbox/symphony-autonomy-design` on `design/autonomy-model`:
  OLD (based on 8a41dd2, has nothing of its own). Its drafts were superseded. Can be removed.
- Worktree `/Users/rafael.calsaverini/Dev/sandbox/symphony-autonomy-design-v2` on `design/autonomy-model-v2`:
  holds the UNCOMMITTED drafts ADR 0021 to 0025, `docs/diagrams/`, and a copy of `principles.md`. Those
  drafts are not on main. The owner has not said whether to commit them. Ask before doing anything. Note:
  `docs/spec/principles.md` in that worktree is a copy of an older main version, so do not merge it
  blindly.
- `.claude/` in the repo root is untracked, and holds `.claude/worktrees/` (subagent worktrees) and now
  `.claude/handoff/` (these notes). Do not commit it. Consider a `.gitignore` entry (ask first: it is a
  repo config change).
- Subagent worktrees under `.claude/worktrees/` (e.g. `agent-a5356356d0169428f`, `agent-abb15241e24adbf94`)
  are from finished subagents. Remove them only when no subagent runs.
- Stale `symphony/*` branches from the old Samba tasks may still exist (about 14, from an earlier count).
  Not checked this session.

## Open code/tool issues noticed

- `CLAUDE.md` says the full run takes about 20 seconds. The last measured run on main was 17 to 23 seconds
  with `-n auto`. Fine now. Earlier, serial runs took about 4.5 minutes, which is why `-n auto` is the
  documented command.
- Warning text: the no-validation warning (`validate.command is not set: Samba will accept work without
  running validation`) has no `samba: ` prefix, unlike other notes. The owner has not chosen. Ask.
- `samba init` writes a partial result if a write fails midway (it reports and stops; it does not roll
  back). Known and accepted for v1.
- The e2e level is at 29 of 30 functions (`tests/checks/test_e2e_budget.py` caps it at 30). Adding a test
  there needs a decision.
- Samba's `WORKFLOW.md` is read only at startup (noted earlier; a live reload is in the backlog chapter).
- The drift test's failure message is weak (shows only the filename). Not fixed.
- No "answer and discard" option for questions. Not built.
- Samba still runs tasks through the old task store while the new artifact model is only a draft.

## Questions the owner must answer (collected)

1. Commit the v2 drafts (ADR 0021 to 0025, the diagrams) to main, or keep them on the branch?
2. Accept or revise the draft ADRs in order: 0021, 0022, 0023, 0024, 0025.
3. Is Samba now opinionated (`ddd-hexagonal` default)? Needs its own ADR.
4. Who writes the glossary terms (file 05)? He must confirm the words and the core domain.
5. The TEP name, and whether an Epic is one file or a folder.
6. The Designer resumes its session on review, or starts fresh?
7. Round cap for the review loop (file 06).
8. Is `samba explore` a command or a skill (file 08)?
9. Warning prefix for the no-validation warning.
10. Remove or keep the old worktrees and the `symphony/*` branches?
11. Whether to add `.claude/` to `.gitignore`.
