"""Ports: the interfaces the core needs from the outside world (spec: architecture).

Protocols only. Adapters in `samba.adapters` implement them; nothing here may import them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from samba.domain.agent import AgentReport, AgentRequest, Readiness

if TYPE_CHECKING:  # the domain's Task imports Clock from here
    from samba.domain.states import State
    from samba.domain.task import ObservedMove, Task
    from samba.domain.task_id import TaskId


class StoreError(Exception):
    """The task store cannot be used (for example a legacy layout it refuses)."""


class TaskExists(Exception):
    """`Tasks.create` found the id already taken."""


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


class Tasks(Protocol):
    """The task store, in the domain's vocabulary (spec: architecture, Ports; states, Task aggregate)."""

    def prepare(self) -> None:
        """Make the store ready. Raises `StoreError(message)` if it cannot be used."""
        ...

    def get(self, id: TaskId) -> Task | None: ...

    def list(self, status: State) -> list[Task]:
        """The valid tasks in a status. Records the store skipped are in `rejected_names`."""
        ...

    def ids(self, status: State | None = None) -> list[TaskId]:
        """Valid ids, in one status or in all, without reading the records."""
        ...

    def create(self, task: Task) -> None:
        """Raises `TaskExists` when the id is taken."""
        ...

    def save(self, task: Task) -> bool:
        """Save the whole aggregate. False, with nothing written, when the aggregate changes
        `status` and the stored status is no longer the one it was loaded with. Fields the
        caller did not change keep their stored values (spec: task-files, Stale saves)."""
        ...

    def observe_moves(self) -> list[ObservedMove]:
        """Hand moves noticed since the last `accept_move` or `save`."""
        ...

    def accept_move(self, move: ObservedMove) -> None: ...

    def revert_move(self, move: ObservedMove) -> bool:
        """Put the task back where it was. False if that is no longer possible."""
        ...

    def rejected_names(self, status: State) -> list[str]:
        """Records in a status the store skipped as invalid."""
        ...

    def location(self, id: TaskId) -> str:
        """Opaque: where the agent finds its task (the `task.path` prompt variable)."""
        ...


class AgentRunner(Protocol):
    async def run(self, request: AgentRequest) -> AgentReport:
        """One agent turn. Never raises for an agent failure: it is in `report.failure`.
        Cancelling the coroutine stops the agent."""
        ...

    async def ready(self) -> Readiness:
        """Whether the agent can run (for Claude, logged in)."""
        ...
