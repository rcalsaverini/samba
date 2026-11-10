"""Ports: the interfaces the core needs from the outside world (spec: architecture).

Protocols only. Adapters in `samba.adapters` implement them; nothing here may import them.
"""

from __future__ import annotations

from typing import Protocol

from samba.domain.agent import AgentReport, AgentRequest, Readiness


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


class AgentRunner(Protocol):
    async def run(self, request: AgentRequest) -> AgentReport:
        """One agent turn. Never raises for an agent failure: it is in `report.failure`.
        Cancelling the coroutine stops the agent."""
        ...

    async def ready(self) -> Readiness:
        """Whether the agent can run (for Claude, logged in)."""
        ...
