# 03: Documents by kind, and the follow-up doc work

Status: draft ADR 0024 (proposed) in the v2 worktree. Step 1 (the move) is on main.

## The rule

One audience and one kind of truth per document. Kinds:

| Kind | Says | Lives in | Survives a rewrite |
|---|---|---|---|
| Contract | what Samba does, as a user sees it | `docs/spec/` | yes |
| Method | how a project is designed and built | method packs shipped in `src/samba/packs/` | yes |
| Implementation | how this version is built (modules, layers) | `docs/implementation/` | no |
| Project instance | decisions, words and plans of one project | `docs/adr/`, `docs/glossary.md`, the backlog | n/a |

The owner's framing: some docs are for Samba to guide it on ANY project, and some are project
specific. The structure must show that.

## Done on main

- `docs/implementation/` holds `architecture.md` and `implementation-notes.md`, with its own index.
- `docs/spec/README.md` no longer lists them.
- `CLAUDE.md` has a `docs/implementation/` bullet.

## Not done (in order)

1. `docs/spec/principles.md` mixes two audiences. The method half (DDD, hexagonal, the triggers, the
   severity dial) belongs in the `ddd-hexagonal` pack (file 04). The Samba-specific half (the table of
   ADRs per principle, the module pointers) belongs in a Samba doc. Plan: the pack text is the source of
   the generic part; Samba's `principles` chapter is the pack text plus a Samba part; a check fails when
   the shared part drifts. This is the decision in plan step 4. The owner said "pack text is the
   source".
2. `CLAUDE.md` is about 200 lines and repeats the module catalog that `docs/implementation/architecture.md`
   already has. Shrink it to what an agent needs on every session: the map of documents, the checks,
   the conventions. The catalog is guarded by tests that read CLAUDE.md, so change those checks with it.
   Not started. The owner's question "how far to shrink" is open (ADR 0024 lists it).
3. `docs/spec/packs.md` is a contract chapter written in step 3. Keep it in sync if `init` changes.
4. Check the design diagrams are marked as target design (they say so in their headers, but the
   `implementation.mmd` header was edited more than once: re-read it).

## Rules for any new doc

- Name its kind in the first lines, or put it where its kind lives.
- If a doc mixes kinds, split it in the change that finds it (ADR 0024 consequence).
- Diagrams are target design until built. Say so in the header.

## Tests that guard docs (do not weaken)

- `tests/checks/test_spec_docs.py`: the spec index matches the files; no section numbers; no phase or
  version names in chapter names; the implementation-notes test reads `docs/implementation/`.
- `tests/checks/test_repo_docs_match_the_code.py`, `test_manual_text.py`,
  `tests/e2e/test_completion_and_docs_e2e.py` (every CLI command in `--help` is in `docs/manual.md`).
