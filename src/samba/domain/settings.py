"""The settings the core reads: plain data, no location, no file format (spec: architecture)."""

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
class AgentSettings:
    """How the `claude` CLI is run, for work (`claude.*`) and for planning (`planning.*`)."""

    command: list[str]
    model: str | None
    permission_mode: str
    allow: list[str]
    args: list[str]
    isolate_user_config: bool
    turn_timeout_s: float
    stall_timeout_s: float
    planning_model: str | None = None
    planning_allow: list[str] = field(default_factory=lambda: list(DEFAULT_PLANNING_ALLOW))


@dataclass(frozen=True)
class Repository:
    """The branch that work is merged into."""

    base_branch: str


@dataclass(frozen=True)
class Prompts:
    """The WORKFLOW.md body and the per-key prompt overrides."""

    template: str
    overrides: dict[str, str] = field(default_factory=lambda: {})


@dataclass(frozen=True)
class Validation:
    command: str | None
    timeout_s: float
    tail_lines: int
    shell: list[str]


@dataclass(frozen=True)
class Hooks:
    after_create: str | None
    timeout_s: float


@dataclass(frozen=True)
class Config:
    """The composite of the parts above; each consumer takes only the part it needs."""

    policy: Policy
    agent: AgentSettings
    repository: Repository
    prompts: Prompts
    validation: Validation
    hooks: Hooks
    warnings: list[str] = field(default_factory=lambda: [])
