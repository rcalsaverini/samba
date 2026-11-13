"""`ClaudeSettings`: how the `claude` CLI is run, read by its two adapters (ADR 0019).

A helper, not an adapter: `ClaudeCliRunner` and `TerminalSession` both import it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ClaudeSettings:
    """The `claude.*` keys and `planning.model` of `WORKFLOW.md`."""

    command: tuple[str, ...]
    model: str | None
    planning_model: str | None
    permission_mode: str
    args: tuple[str, ...]
    isolate_user_config: bool
    turn_timeout_s: float
    stall_timeout_s: float
