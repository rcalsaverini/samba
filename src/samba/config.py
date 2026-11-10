"""Load and validate WORKFLOW.md (spec: workflow-config)."""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import yaml

WORKFLOW_FILE = "WORKFLOW.md"
PERMISSION_MODES = ("dontAsk", "acceptEdits", "bypassPermissions", "default", "auto", "plan")
PROMPT_KEYS = ("continue", "validate_failed", "resume", "give_up", "plan", "plan_revise")

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
class ClaudeConfig:
    command: list[str]
    model: str | None
    permission_mode: str
    allow: list[str]
    args: list[str]
    isolate_user_config: bool
    turn_timeout_s: float
    stall_timeout_s: float


@dataclass(frozen=True)
class PlanningConfig:
    require_plan: bool = False
    model: str | None = None
    allow: list[str] = field(default_factory=lambda: list(DEFAULT_PLANNING_ALLOW))


@dataclass(frozen=True)
class Config:
    repo: Path
    samba_dir: Path
    workspaces_root: Path
    base_branch: str
    poll_interval_s: float
    shell: list[str]
    max_concurrent: int
    max_turns: int
    max_attempts: int
    retry_base_s: float
    max_retry_backoff_s: float
    max_cost_usd_per_task: float | None
    reflect_on_give_up: bool
    after_create: str | None
    hooks_timeout_s: float
    validate_command: str | None
    validate_timeout_s: float
    validate_tail_lines: int
    claude: ClaudeConfig
    prompt_template: str
    prompts: dict[str, str] = field(default_factory=lambda: {})
    planning: PlanningConfig = field(default_factory=PlanningConfig)
    warnings: list[str] = field(default_factory=lambda: [])


def split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """Split `---` YAML front matter from a markdown body. Missing front matter gives {}."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            raw = "".join(lines[1:i])
            body = "".join(lines[i + 1:])
            try:
                data: Any = yaml.safe_load(raw) if raw.strip() else {}
            except yaml.YAMLError as e:
                raise ConfigError(f"invalid YAML front matter: {e}") from e
            if data is None:
                data = {}
            if not isinstance(data, dict):
                raise ConfigError("front matter must be a YAML map")
            return cast(dict[str, Any], data), body
    raise ConfigError("front matter starts with --- but has no closing ---")


class _Reader:
    """Typed access to a nested YAML map, collecting unknown keys."""

    def __init__(self, data: dict[str, Any], prefix: str = "") -> None:
        self.data = data
        self.prefix = prefix
        self.used: set[str] = set()

    def _get(self, key: str) -> Any:
        self.used.add(key)
        return self.data.get(key)

    def name(self, key: str) -> str:
        return f"{self.prefix}{key}"

    def section(self, key: str) -> _Reader:
        value = self._get(key)
        if value is None:
            return _Reader({}, f"{self.name(key)}.")
        if not isinstance(value, dict):
            raise ConfigError(f"{self.name(key)} must be a map")
        return _Reader(cast(dict[str, Any], value), f"{self.name(key)}.")

    def string(self, key: str, default: str | None) -> str | None:
        value = self._get(key)
        if value is None:
            return default
        if not isinstance(value, (str, int, float)):
            raise ConfigError(f"{self.name(key)} must be a string")
        return str(value)

    def number(self, key: str, default: float, positive: bool = True) -> float:
        value = self._get(key)
        if value is None:
            return default
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ConfigError(f"{self.name(key)} must be a number")
        try:
            number = float(value)
        except ValueError as e:
            raise ConfigError(f"{self.name(key)} must be a number") from e
        if positive and number <= 0:
            raise ConfigError(f"{self.name(key)} must be positive")
        return number

    def integer(self, key: str, default: int) -> int:
        number = self.number(key, default)
        if number != int(number):
            raise ConfigError(f"{self.name(key)} must be an integer")
        return int(number)

    def optional_number(self, key: str) -> float | None:
        if self.data.get(key) is None:
            self.used.add(key)
            return None
        return self.number(key, 0.0)

    def boolean(self, key: str, default: bool) -> bool:
        value = self._get(key)
        if value is None:
            return default
        if not isinstance(value, bool):
            raise ConfigError(f"{self.name(key)} must be true or false")
        return value

    def string_list(self, key: str, default: list[str]) -> list[str]:
        value = self._get(key)
        if value is None:
            return list(default)
        if not isinstance(value, list):
            raise ConfigError(f"{self.name(key)} must be a list of strings")
        items = cast(list[Any], value)
        if not all(isinstance(v, str) for v in items):
            raise ConfigError(f"{self.name(key)} must be a list of strings")
        return [str(v) for v in items]

    def unknown(self) -> list[str]:
        return [self.name(k) for k in self.data if k not in self.used]


def _expand(path: str, base: Path) -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = base / p
    return p.resolve()


def load_config(repo: Path) -> Config:
    repo = repo.resolve()
    workflow = repo / WORKFLOW_FILE
    try:
        text = workflow.read_text()
    except OSError as e:
        raise ConfigError(f"cannot read {workflow}: {e}") from e
    data, body = split_front_matter(text)

    r = _Reader(data)
    hooks = r.section("hooks")
    validate = r.section("validate")
    claude = r.section("claude")
    prompts_r = r.section("prompts")
    planning_r = r.section("planning")

    samba_dir = _expand(r.string("samba_dir", ".samba") or ".samba", repo)
    workspaces_root = _expand(r.string("workspaces_root", "~/.samba/workspaces")
                              or "~/.samba/workspaces", repo)
    if workspaces_root == repo or repo in workspaces_root.parents:
        raise ConfigError(f"workspaces_root ({workspaces_root}) must be outside the repository, "
                          "or the agent would also load the main checkout's CLAUDE.md")

    command_str = claude.string("command", "claude") or ""
    command = shlex.split(command_str)
    if not command:
        raise ConfigError("claude.command must not be empty")
    permission_mode = claude.string("permission_mode", "dontAsk") or "dontAsk"
    if permission_mode not in PERMISSION_MODES:
        raise ConfigError(f"claude.permission_mode must be one of {', '.join(PERMISSION_MODES)}")

    shell = r.string_list("shell", ["bash", "-c"])
    if not shell:
        raise ConfigError("shell must not be empty")

    prompts: dict[str, str] = {}
    for key in PROMPT_KEYS:
        value = prompts_r.string(key, None)
        if value:
            prompts[key] = value

    claude_cfg = ClaudeConfig(
        command=command,
        model=claude.string("model", None),
        permission_mode=permission_mode,
        allow=claude.string_list("allow", DEFAULT_ALLOW),
        args=claude.string_list("args", []),
        isolate_user_config=claude.boolean("isolate_user_config", True),
        turn_timeout_s=claude.number("turn_timeout_s", 3600),
        stall_timeout_s=claude.number("stall_timeout_s", 300),
    )

    planning_cfg = PlanningConfig(
        require_plan=planning_r.boolean("require_plan", False),
        model=planning_r.string("model", None),
        allow=planning_r.string_list("allow", DEFAULT_PLANNING_ALLOW),
    )

    config = Config(
        repo=repo,
        samba_dir=samba_dir,
        workspaces_root=workspaces_root,
        base_branch=r.string("base_branch", "main") or "main",
        poll_interval_s=r.number("poll_interval_s", 10),
        shell=shell,
        max_concurrent=r.integer("max_concurrent", 2),
        max_turns=r.integer("max_turns", 10),
        max_attempts=r.integer("max_attempts", 3),
        retry_base_s=r.number("retry_base_s", 10),
        max_retry_backoff_s=r.number("max_retry_backoff_s", 300),
        max_cost_usd_per_task=r.optional_number("max_cost_usd_per_task"),
        reflect_on_give_up=r.boolean("reflect_on_give_up", True),
        after_create=hooks.string("after_create", None),
        hooks_timeout_s=hooks.number("timeout_s", 300),
        validate_command=validate.string("command", None),
        validate_timeout_s=validate.number("timeout_s", 900),
        validate_tail_lines=validate.integer("output_tail_lines", 200),
        claude=claude_cfg,
        prompt_template=body.strip(),
        prompts=prompts,
        planning=planning_cfg,
    )
    for reader in (r, hooks, validate, claude, prompts_r, planning_r):
        config.warnings.extend(f"unknown config key ignored: {k}" for k in reader.unknown())
    if not config.prompt_template:
        raise ConfigError("WORKFLOW.md has an empty prompt body")
    return config
