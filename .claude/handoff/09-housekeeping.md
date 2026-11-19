# 09: Housekeeping, loose ends and questions for the owner

Nothing here is decided. Clean-up is safe only after checking with the owner.

## Git state (checked 2026-11-19; re-check before acting)

- Main: 04aa06a. Git reports main up to date with origin/main (ADRs and notes were pushed or committed
  since the last handoff; verify push state before assuming).
- The v2 worktree (`symphony-autonomy-design-v2`, branch `design/autonomy-model-v2`) is gone: it was
  merged into main as 0c8bbae. ADRs 0021 to 0025 and the target-design diagrams are on main.
- `.claude/handoff/` (these notes) is tracked in git. `.claude/worktrees/` no longer exists, so there
  are no subagent worktrees to clean up.
- The only untracked file under `.claude/` now is `.claude/.DS_Store`. Consider adding a `.DS_Store`
  ignore rule (ask first: it is a repo config change).
- `docs/implementation-folder` and `design/autonomy-model` branches still exist locally (now unused);
  `symphony/*` and `samba/*` task branches also remain. Not cleaned up; ask the owner before deleting.

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
- ADR title numbers inside 0021 to 0023 did not match their filenames (0011, 0012, 0021). Fixed to match
  on 2026-11-19.

## Questions the owner must answer (collected)

1. Accept or revise the proposed ADRs in order: 0021, 0022, 0023, 0024, 0025, 0026.
2. Is Samba now opinionated (`ddd-hexagonal` default)? Needs its own ADR.
3. Who writes the glossary terms (file 05)? He must confirm the words and the core domain.
4. The TEP name, and whether an Epic is one file or a folder.
5. The Designer resumes its session on review, or starts fresh?
6. Round cap for the review loop (file 06).
7. Is `samba explore` a command or a skill (file 08)?
8. Warning prefix for the no-validation warning.
9. Remove or keep the old worktrees and the `symphony/*` and `samba/*` branches?
10. Whether to ignore `.DS_Store` (and add `.claude/` to `.gitignore`, or keep the notes tracked).
