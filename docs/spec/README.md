# Samba specification index

The Samba specification is split into the chapters below, one file per topic. Chapters are referenced by name (for example "states, The Tasks port"), not by number. Read the chapter that matches what you are changing.

- [overview.md](overview.md): read first, for what Samba is and the v0 non-goals.
- [layout.md](layout.md): read when touching the repo layout, the `.samba/` folder or where files live on disk.
- [task-files.md](task-files.md): read when touching task file identity, format (including `depends_on`), sections, write discipline or how a planning result is written.
- [states.md](states.md): read when touching task states, the planning stage, the transition table, the sidecar, questions or the data model.
- [orchestrator.md](orchestrator.md): read when touching startup, the tick, dispatch, task dependencies, workers, failures or retries.
- [workflow-config.md](workflow-config.md): read when touching `WORKFLOW.md` front matter, config defaults (including `planning`) or permissions.
- [workspaces.md](workspaces.md): read when touching git worktrees, their safety invariants, validation or removal.
- [prompts.md](prompts.md): read when touching template rendering, built-in prompts, the protocol prompt or its planning variant.
- [running-claude.md](running-claude.md): read when touching how `claude` is invoked, the stream, the outcome schemas, the planning run, config isolation or the verified Claude Code behavior.
- [observability.md](observability.md): read when touching logs and what an operator can see.
- [cli.md](cli.md): read when adding or changing a CLI command or its output.
- [architecture.md](architecture.md): read when touching the layers, the dependency rule, ports or adapters.
- [implementation-notes.md](implementation-notes.md): read for implementation details.
- [backlog.md](backlog.md): read to see ideas not built yet.
