---
status: accepted
date: 2026-11-07
supersedes: []
---

# 0010: Python for v0, with a rewrite expected, chosen for agent self-verification

Recorded retroactively on 2026-11-08.

## Context

Samba started as an experiment, and the language question came up at once. The human's main criterion
is how well an agent can check its own work, meaning type checking and fast tests, and not their own
familiarity with the language.

## Decision

- v0 is Python 3.11+, fully typed, with `pyright` in strict mode and `pytest` as the validation
  gate (`uv run pyright && uv run pytest -q`).
- A rewrite, likely in Rust, is expected. Nothing here is designed to last forever.
- To keep the rewrite cheap, the behavior contract lives outside the Python: the spec in
  `docs/spec/`, the black-box suite (ADR 0009), and the process boundary to `claude` (ADR 0006).
- Public signatures use no `Any`. Values from JSON and YAML are cast at the boundary.

## Consequences

- Fast iteration now, with checks an agent can run in the loop.
- Some choices are made for the agent's benefit, for example strict typing everywhere.
- The rewrite is a reimplementation against a contract. A line-by-line port is not the goal.
- If the rewrite language changes the answer to "what can an agent check", this ADR should be
  superseded rather than edited.
