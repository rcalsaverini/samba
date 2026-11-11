"""What to start for an interactive session: a program, its arguments and where (spec: cli, explore).

Pure: building the spec touches nothing. `cwd` is opaque text.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from samba.domain.prompts import EXPLORE_ALLOW, EXPLORE_DENY, EXPLORE_GUIDE


@dataclass(frozen=True)
class LaunchSpec:
    """A program to run attached to the person's terminal."""

    argv: tuple[str, ...]
    cwd: str


def explore_launch(command: Sequence[str], model: str | None, topic: str | None,
                   cwd: str) -> LaunchSpec:
    """The `claude` session of `samba explore`. The topic is the positional first prompt, put right
    after the command because the flags that follow take lists."""
    argv = [*command]
    if topic:
        argv.append(topic)
    argv += ["--append-system-prompt", EXPLORE_GUIDE,
             "--allowedTools", *EXPLORE_ALLOW,
             "--disallowedTools", *EXPLORE_DENY]
    if model:
        argv += ["--model", model]
    return LaunchSpec(tuple(argv), cwd)
