"""Unit tests of `load_config`: the composite of frozen parts (spec: workflow-config).

This file may import `samba.config`; the black-box files must not.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from samba.config import (DEFAULT_ALLOW, DEFAULT_PLANNING_ALLOW, ConfigError, Hooks, Layout,
                          Policy, Prompts, Validation, load_config)


def write(repo: Path, front: str, body: str = "Do {{ task.title }}\n") -> None:
    (repo / "WORKFLOW.md").write_text(f"---\n{front}---\n{body}")


def test_defaults(tmp_path: Path) -> None:
    write(tmp_path, "")
    cfg = load_config(tmp_path)
    repo = tmp_path.resolve()
    assert cfg.policy == Policy(
        max_turns=10, max_attempts=3, retry_base_s=10, max_retry_backoff_s=300,
        max_cost_usd_per_task=None, reflect_on_give_up=True, require_plan=False,
        max_concurrent=2, poll_interval_s=10)
    assert cfg.layout == Layout(
        repo=repo, samba_dir=repo / ".samba",
        workspaces_root=(Path("~/.samba/workspaces").expanduser()).resolve(),
        base_branch="main")
    assert cfg.prompts == Prompts(template="Do {{ task.title }}", overrides={})
    assert cfg.validation == Validation(command=None, timeout_s=900, tail_lines=200,
                                        shell=["bash", "-c"])
    assert cfg.hooks == Hooks(after_create=None, timeout_s=300)
    assert cfg.agent.command == ["claude"]
    assert cfg.agent.model is None
    assert cfg.agent.permission_mode == "dontAsk"
    assert cfg.agent.allow == DEFAULT_ALLOW
    assert cfg.agent.args == []
    assert cfg.agent.isolate_user_config is True
    assert cfg.agent.turn_timeout_s == 3600
    assert cfg.agent.stall_timeout_s == 300
    assert cfg.agent.planning_model is None
    assert cfg.agent.planning_allow == DEFAULT_PLANNING_ALLOW
    assert cfg.warnings == []


def test_values_land_in_their_parts(tmp_path: Path) -> None:
    ws = tmp_path.parent / f"{tmp_path.name}-ws"
    write(tmp_path, f"""base_branch: trunk
samba_dir: state
workspaces_root: {ws}
poll_interval_s: 3
max_concurrent: 4
max_turns: 7
max_attempts: 2
retry_base_s: 1
max_retry_backoff_s: 9
max_cost_usd_per_task: 1.5
reflect_on_give_up: false
shell: [sh, -c]
hooks:
  after_create: echo hi
  timeout_s: 5
validate:
  command: make test
  timeout_s: 60
  output_tail_lines: 20
claude:
  command: my-claude --flag
  model: m1
  permission_mode: acceptEdits
  allow: [Read]
  args: [--x]
  isolate_user_config: false
  turn_timeout_s: 11
  stall_timeout_s: 12
prompts:
  continue: keep going
planning:
  require_plan: true
  model: m2
  allow: [Grep]
""")
    cfg = load_config(tmp_path)
    repo = tmp_path.resolve()
    assert cfg.layout == Layout(repo=repo, samba_dir=repo / "state", workspaces_root=ws.resolve(),
                                base_branch="trunk")
    assert cfg.policy == Policy(
        max_turns=7, max_attempts=2, retry_base_s=1, max_retry_backoff_s=9,
        max_cost_usd_per_task=1.5, reflect_on_give_up=False, require_plan=True,
        max_concurrent=4, poll_interval_s=3)
    assert cfg.validation == Validation(command="make test", timeout_s=60, tail_lines=20,
                                        shell=["sh", "-c"])
    assert cfg.hooks == Hooks(after_create="echo hi", timeout_s=5)
    assert cfg.prompts.overrides == {"continue": "keep going"}
    agent = cfg.agent
    assert (agent.command, agent.model, agent.permission_mode) == (
        ["my-claude", "--flag"], "m1", "acceptEdits")
    assert (agent.allow, agent.args, agent.isolate_user_config) == (["Read"], ["--x"], False)
    assert (agent.turn_timeout_s, agent.stall_timeout_s) == (11, 12)
    assert (agent.planning_model, agent.planning_allow) == ("m2", ["Grep"])


def test_parts_are_frozen(tmp_path: Path) -> None:
    write(tmp_path, "")
    cfg = load_config(tmp_path)
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.policy.max_turns = 1  # type: ignore[misc]


def test_unknown_keys_warn_and_empty_body_fails(tmp_path: Path) -> None:
    write(tmp_path, "bogus: 1\nhooks:\n  nope: 2\n")
    assert load_config(tmp_path).warnings == [
        "unknown config key ignored: bogus", "unknown config key ignored: hooks.nope"]
    write(tmp_path, "", body="\n")
    with pytest.raises(ConfigError):
        load_config(tmp_path)
