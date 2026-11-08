# Samba specification index

The Samba specification is split into the chapters below, one file per topic. Chapters are referenced by name (for example "states, Sidecar state"), not by number. Read the chapter that matches what you are changing.

- [overview.md](overview.md): read first, for what Samba is and the v0 non-goals.
- [layout.md](layout.md): read when touching the repo layout, the `.samba/` folder or where files live on disk.
- [task-files.md](task-files.md): read when touching task file identity, format, sections or write discipline.
- [states.md](states.md): read when touching task states, the transition table, the sidecar, questions or the data model.
- [orchestrator.md](orchestrator.md): read when touching startup, the tick, workers, failures or retries.
- [workflow-config.md](workflow-config.md): read when touching `WORKFLOW.md` front matter, config defaults or permissions.
- [workspaces.md](workspaces.md): read when touching git worktrees, their safety invariants, validation or removal.
- [prompts.md](prompts.md): read when touching template rendering, built-in prompts or the protocol prompt.
- [running-claude.md](running-claude.md): read when touching how `claude` is invoked, the stream, the outcome schema or config isolation.
- [observability.md](observability.md): read when touching logs and what an operator can see.
- [cli.md](cli.md): read when adding or changing a CLI command or its output.
- [implementation-notes.md](implementation-notes.md): read for implementation details and the verified Claude Code behavior.
- [later.md](later.md): read to see what is explicitly out of v0.
- [planning.md](planning.md): read when touching the planning phase (plan states, planning run, plan review).
- [dependencies.md](dependencies.md): read when touching `depends_on` and task dependencies.
