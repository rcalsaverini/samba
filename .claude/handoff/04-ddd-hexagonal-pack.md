# 04: The `ddd-hexagonal` method pack (plan step 4)

Status: NOT STARTED. Depends on step 3 (`samba init`, done on main) and on file 03.

## Why

`samba init` is meant to start a new project with the method the owner wants: DDD plus hexagonal
architecture, opinionated by default. Only `base` ships. The owner said: "I'm changing my mind a little
bit and leaning towards making it opinionated." That lean is NOT yet an ADR. Draft ADR 0025 records the
mechanism (packs, init); it says the opinionated stance "deserves its own ADR when the owner is sure".
Ask before writing that ADR.

## What to build

A directory `src/samba/packs/ddd-hexagonal/`, overlaid on `base` (the method's file wins). Files:

- `docs/principles.md`: SHORT. Strategic design first, then tactical; the dependency rule; ports
  declared by the use cases; values, not capabilities; one word, one meaning; the triggers for
  strategic rituals; the severity dial; a proportionality clause.
- `docs/glossary.md`: an empty table and instructions ("a term is added when the owner agrees it").
- `docs/enforcing-the-architecture.md`: a language-neutral recipe for writing the project's own
  architecture test. Samba ships NO per-language checks.
- `docs/adr/0001-use-ddd-and-hexagonal-architecture.md`: accepted, with the date filled by the
  `@@DATE@@` marker.
- `WORKFLOW.md`: the body fragment telling agents to read the principles and the glossary first, and
  to prefer the smallest model that expresses the rule.

## Rules this pack must encode (from the design talk)

- Ceremony follows triggers, not project size. Glossary entries, event storming and context maps
  happen when (a) a concept appears that is not in the glossary, (b) a word has two meanings, or (c) the
  work crosses or creates a bounded context. Work inside the existing model needs none of that.
  New contexts and glossary terms need the owner: an agent must not invent them.
- Severity is the dial. Only violations of machine-checkable rules or explicit ADRs are Blocker or
  Major. Smell-level advice (anemic model, a missing value object) is a Nit: recorded, never blocking.
- Tactical blocks appear only when a rule demands them. The Reviewer's Architect lens asks of a new
  type: "which requirement of this task fails without it?"
- Build the model small: "the smallest model that expresses the rule in front of you".
- "Applies to the code a task touches or adds." Legacy code is OUT OF SCOPE for v1 (owner: "maybe a
  v2"). The pack assumes a new repo.
- Enforcement is docs in v1. Samba requires `validate.command` to pass and nothing more. The Reviewer
  is a soft enforcer until the project adds its own check.
- Keep it SMALL. The owner: "If it's 200 lines of DDD, we've rebuilt the ceremony problem." Target: a
  short principles page, an empty glossary, the guide, ADR 0001, the workflow fragment. Count the lines
  and say so in the report.

## Acceptance

- `samba init` with the default method writes these files; `--method base` writes none of them.
- A test (integration) loads each shipped file; no em-dashes; the shipped WORKFLOW loads through
  `load_config`.
- Component test: overlay (method wins) with `FakePacks`.
- Samba's own `docs/spec/principles.md` becomes the pack text plus a Samba part. A check test fails when
  the shared part drifts. Decide the exact mechanism when writing the test (a marker block copied from
  the pack, compared as text).
- Spec: `docs/spec/packs.md` gains the `ddd-hexagonal` contents. ADR 0025 open question about packs
  depending on each other stays open.

## Open with the owner

- Exact wording of the principles page (it is the method; he should read it).
- Whether `ddd-hexagonal` becomes the default now or only after the opinionated ADR is accepted.
  Currently `DEFAULT_METHOD = "base"` in `src/samba/app/init_project.py`.
