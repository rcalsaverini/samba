---
status: accepted
date: 2026-11-07
supersedes: []
---

# 0006: Run the plain `claude` CLI headless, not an SDK

Recorded retroactively on 2026-11-08.

## Context

Samba needs to run an agent on a task for many turns and read its structured result. The options were
a Claude SDK embedded in the orchestrator, or the `claude` command-line tool run as a subprocess.

## Decision

- The orchestrator runs `claude -p` as a subprocess and reads its `stream-json` output. It passes the
  permission mode, the allowed tools, the JSON schema for the outcome and the isolation settings as
  command-line arguments.
- The agent is whatever Claude Code the user has installed. Samba owns the prompt protocol and the
  outcome schema, and nothing in the agent itself.

## Consequences

- Samba stays generic: any model, any Claude Code setup and any improvement to the CLI work without
  changes here.
- The interface is a process boundary, so it is the same from a Python or a Rust orchestrator.
- Samba depends on the CLI's flags and stream format. The spec records the verified behavior, with
  the version, in `docs/spec/running-claude.md`, and the fake `claude` in the tests pins what Samba
  relies on.
- Headless Claude Code loads the user's own configuration by default, so Samba isolates it with
  `--setting-sources project,local`, `--strict-mcp-config` and excluded ancestor memory files.
