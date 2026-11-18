---
status: proposed
date: 2026-11-13
supersedes: []
---

# 0024: Each document has one audience and one kind of truth

## Context

The docs grew while the code was written, and one file often serves several readers. The principles
chapter holds a general method (DDD, hexagonal) and Samba's own application of it. The architecture
chapter names Python modules, so it describes this implementation and not the behavior a rewrite must
reproduce (ADR 0010, principle 9). `CLAUDE.md` repeats that module catalog on every agent session. A
reader cannot tell which parts are the contract, which are a method any project could reuse, and which
only matter to someone editing Samba.

## Decision

- A document has one audience and one kind of truth. The kinds are:

  | Kind | Says | Lives in | Survives a rewrite |
  |---|---|---|---|
  | Contract | what Samba does, as a user sees it | `docs/spec/` | yes |
  | Method | how a project is designed and built | the method packs shipped with Samba (ADR 0025) | yes |
  | Implementation | how this version is built: modules, layers, files | `docs/implementation/` | no |
  | Project instance | the decisions, words and plans of one project | `docs/adr/`, `docs/glossary.md`, the backlog | n/a |

- The architecture chapter and the implementation notes move from `docs/spec/` to
  `docs/implementation/`. `docs/spec/` holds the contract only.
- The method half of the principles chapter moves into a pack. Samba's own principles document is the
  pack text plus a part specific to Samba, and a check fails when the shared part differs from the pack.
- `CLAUDE.md` points at the documents and holds only what an agent needs on every session. It does not
  repeat the module catalog.
- Samba's own repository is the first project built from its own pack.

## Consequences

- A rewrite reuses `docs/spec/`, the method packs and the scenario data, and replaces
  `docs/implementation/`.
- Moves touch the spec index, `CLAUDE.md`, and the checks that read `docs/spec/`.
- A document that mixes kinds is a defect, fixed by splitting it in the change that finds it, in the
  spirit of principle 10.
- Open: how far to shrink `CLAUDE.md`, which is also guarded by tests that read its module map.
