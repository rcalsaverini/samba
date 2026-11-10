"""Result types shared by the use cases. Use cases never print or return exit codes: the CLI
prints `messages` (stderr, complete lines) and maps `kind` to an exit code."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Refused:
    """The command stopped and nothing (more) changed. `usage` is exit 2, `refused` exit 1."""

    kind: Literal["refused", "usage"]
    messages: tuple[str, ...]


def refused(message: str) -> Refused:
    return Refused("refused", (f"samba: {message}",))


def usage(message: str) -> Refused:
    return Refused("usage", (f"samba: {message}",))


LOCK_BUSY = "another command or the orchestrator holds .samba/lock; try again"
