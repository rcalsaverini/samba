---
priority: 3
---
# Add a README.md

We need a README.md for the github page. 

## Plan
- [x] Read CLAUDE.md, SPEC.md, CLI help definitions
- [x] Write README.md (docs only, no behavior change, so no tests or SPEC change)
- [x] Commit

## Log
- Added README.md: overview, how it works, install, quick start, commands, docs, dev checks.
  No SPEC.md change needed.
- 2026-11-08 00:35 samba: dispatch_work: work-todo -> work-running
- 2026-11-08 00:38 samba: done: work-running -> work-review: validation passed (turns 1, $0.11): I added README.md and committed it on the branch. It covers an overview, how Samba works, install, quick start, the command list, doc links and the dev checks. This is docs only, so I wrote no tests and made no SPEC.md change. I didn't run `uv run pyright` or `uv run pytest` myself, so the system's validation will be the first run of them.
- 2026-11-08 00:50 samba: work.accept: work-review -> done: merged 9ba21c4, validated
