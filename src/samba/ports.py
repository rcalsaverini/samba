"""Ports: the interfaces the core needs from the outside world (spec: architecture).

Protocols only. Adapters in `samba.adapters` implement them; nothing here may import them.
"""

from __future__ import annotations

from typing import Protocol


class Clock(Protocol):
    def time(self) -> float:
        """Wall-clock time, seconds since the epoch."""
        ...

    def monotonic(self) -> float:
        """Monotonic time in seconds, for durations and deadlines."""
        ...

    def iso_seconds(self) -> str:
        """`time()` as local-offset ISO 8601 text, to the second (question timestamps)."""
        ...

    def log_stamp(self) -> str:
        """`time()` as local `YYYY-MM-DD HH:MM` text (`## Log` lines)."""
        ...


class IdGenerator(Protocol):
    def new_session_id(self) -> str:
        """A fresh Claude session id."""
        ...
