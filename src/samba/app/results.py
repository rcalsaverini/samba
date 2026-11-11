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


@dataclass(frozen=True)
class Table:
    """Rows to print as columns; `flex` is the column that takes the room left on the line."""

    rows: tuple[tuple[str, ...], ...]
    flex: int


@dataclass(frozen=True)
class Text:
    """Text for stdout, exactly as it is to be written (newlines included)."""

    text: str


@dataclass(frozen=True)
class Written:
    """Files an ADR command changed, one per line on stdout."""

    files: tuple[str, ...]


LOCK_BUSY = "another command or the orchestrator holds .samba/lock; try again"
