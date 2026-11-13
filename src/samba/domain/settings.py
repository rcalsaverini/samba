"""What the domain and the use cases read: plain data (spec: architecture).

No location, no file format, and nothing named for a technology: each adapter declares its own
settings next to itself (ADR 0019).
"""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_ALLOW = [
    "Edit",
    "Write",
    "Bash(git add:*)",
    "Bash(git commit:*)",
    "Bash(git status:*)",
    "Bash(git diff:*)",
    "Bash(git log:*)",
    # Read-only ADR commands; accept, reject and supersede are the human's.
    "Bash(samba adr list:*)",
    "Bash(samba adr show:*)",
]
DEFAULT_PLANNING_ALLOW = ["Read", "Grep", "Glob", "Bash(samba adr list:*)", "Bash(samba adr show:*)"]


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Policy:
    """Limits and scheduling: turns, retries, cost, concurrency, polling."""

    max_turns: int
    max_attempts: int
    retry_base_s: float
    max_retry_backoff_s: float
    max_cost_usd_per_task: float | None
    reflect_on_give_up: bool
    require_plan: bool
    max_concurrent: int
    poll_interval_s: float


@dataclass(frozen=True)
class ToolAccess:
    """What the agent may do in one stage: the tool rules it is allowed, or everything."""

    allowed: tuple[str, ...]
    unrestricted: bool


@dataclass(frozen=True)
class Prompts:
    """The WORKFLOW.md body and the per-key prompt overrides."""

    template: str
    overrides: dict[str, str] = field(default_factory=lambda: {})


@dataclass(frozen=True)
class Config:
    """The composite of the parts above; each consumer takes only the part it needs."""

    policy: Policy
    prompts: Prompts
    base_branch: str
    validate_command: str | None
    work_tools: ToolAccess
    planning_tools: ToolAccess
    warnings: list[str] = field(default_factory=lambda: [])
