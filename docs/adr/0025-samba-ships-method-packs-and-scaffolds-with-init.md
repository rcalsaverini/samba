---
status: proposed
date: 2026-11-13
supersedes: []
---

# 0025: Samba ships method packs and scaffolds a project with `samba init`

## Context

Samba runs agents on a project, and what the agents build depends on the rules the project gives them.
Today those rules are whatever the person writes in `WORKFLOW.md` and the repo's docs. Samba's own repo
has a worked-out method (DDD and hexagonal architecture, ADRs, a spec gate), but a new project starts
from nothing and has to copy it by hand. ADR 0024 separates the method from Samba's own docs, which
makes it shippable.

## Decision

- Samba ships method packs: directories that mirror a project tree, kept as package data under
  `src/samba/packs/`. A pack holds plain files, copied verbatim except for two fixed markers: the date
  of the run and the validation command.
- `samba init [--method NAME]` writes a pack into a repository. The methods are `base` and
  `ddd-hexagonal`, which is the default. Other methods can be added later, each a self-consistent
  directory. There is one name per method and no flag per practice.
  - `base` creates `WORKFLOW.md`, a `CLAUDE.md` skeleton, the first ADR (`0000`, which records that the
    project uses ADRs), a `docs/spec/README.md` index skeleton. The `.samba/` folders are created by the commands that
    need them, not by `init`.
  - `ddd-hexagonal` adds, on top of `base`, a short principles document, an empty glossary, a guide to
    writing the project's own architecture test, a first ADR choosing the method, and a `WORKFLOW.md`
    whose body tells agents to read the principles and the glossary first. Where both packs have a file,
    the method's wins.
- `init` never overwrites. It writes the files that are missing, says which it skipped, offers
  `--dry-run` and never commits. This version targets new repositories.
- `init` asks for the validation command on a terminal. The person may skip it, and then the key is
  left empty and Samba warns every time it is unset.
- The method is documentation and prompts. Samba ships no per-language architecture checks: the guide
  describes how to write one, and the project owns it and runs it as part of its validation.
- The pack stays small. A method that needs pages of ceremony to start is the wrong size.

## Consequences

- A new project gets a working structure and the method from one command, and owns the files from then
  on. A later Samba upgrade does not change a project's rules.
- Samba becomes opinionated by default (`ddd-hexagonal`), which changes the earlier "generic and
  barebones" framing. This ADR records the mechanism. Whether that stance is right for Samba is its own
  decision.
- Adopting a method in a repository that already has code, and upgrading a pack, are not decided here.
- A pack file is part of the behavior contract of `init`, so the spec gains a `packs` chapter that
  lists what each method creates.
- Open: whether packs may declare dependencies on each other beyond overlaying `base`.
