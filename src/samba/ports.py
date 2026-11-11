"""Ports: the interfaces the core needs from the outside world (spec: architecture).

Protocols only. Adapters in `samba.adapters` implement them; nothing here may import them.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

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


@dataclass(frozen=True)
class EditResult:
    """What `Terminal.edit` returns: the text, or `error` (a message without the `samba: `
    prefix) when the editor could not run or failed."""

    text: str | None = None
    error: str | None = None


class Terminal(Protocol):
    """The person at the keyboard (spec: cli, confirmation policy)."""

    def is_interactive(self) -> bool:
        """Whether both input and output are a terminal."""
        ...

    def ask(self, prompt: str) -> str:
        """Print `prompt` (no newline), read one line without its line end. Raises `EOFError`
        at end of input."""
        ...

    def read_block(self, prompt: str) -> list[str]:
        """Print `prompt` (and a newline), read lines until an empty line or end of input."""
        ...

    def warn(self, line: str) -> None:
        """Show one complete line to the person (stderr), in the middle of a dialogue."""
        ...

    def edit(self, initial: str) -> EditResult:
        """Let the person edit `initial` in their editor. Returns the file's content."""
        ...


MergeStatus = Literal["merged", "already", "conflict", "validation_failed", "error"]


@dataclass(frozen=True)
class MergeResult:
    """What `Merger.merge` returns. `detail` is the short sha (merged), the files (conflict), the
    log tail (validation_failed) or the git error; `log_path` names the full validation output."""

    status: MergeStatus
    detail: str = ""
    validated: bool = False
    log_path: str | None = None


class Merger(Protocol):
    """The git steps of `work accept` over the main checkout (spec: cli, work accept)."""

    def branch_name(self, task_id: str) -> str:
        """The branch the task's work lives on."""
        ...

    def preflight(self, branch: str) -> str | None:
        """A message for the first failed check, or None when the merge may proceed."""
        ...

    def commit_count(self, branch: str) -> int:
        """Commits on `branch` not yet in the base branch."""
        ...

    def merge(self, task_id: str, branch: str, message: str, validate: bool) -> MergeResult:
        """Merge without committing, validate the result when asked, commit only on a pass. On any
        failure the checkout is left as it was."""
        ...


class RepoLock(Protocol):
    """The advisory lock that serialises state-changing commands and the orchestrator."""

    def acquire(self, blocking: bool = True) -> AbstractContextManager[bool]:
        """Hold the lock for a `with` block. Yields True once held, False (holding nothing) if
        it could not be had."""
        ...


class WorkspaceError(Exception):
    """A workspace could not be created or removed."""


class Workspaces(Protocol):
    """The per-task workspaces, the part the tick needs (spec: workspaces)."""

    def existing_ids(self) -> list[str]:
        """Ids of the tasks that have a workspace."""
        ...

    async def remove(self, task_id: str) -> None:
        """Raises `WorkspaceError(message)` when it cannot be removed."""
        ...


class AdrError(Exception):
    """An ADR command refusal; `code` is the exit code (1 wrong state or bad file, 2 usage or
    unknown number)."""

    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class AdrInfo:
    """One ADR as the use cases see it: `file` is where it is stored, as opaque text."""

    number: int
    file: str
    status: str
    title: str
    summary: str
    text: str


class Adrs(Protocol):
    """The ADR records of the repository (spec: cli, ADR commands). Every method may raise
    `AdrError`."""

    def parse_number(self, text: str) -> int:
        """`3`, `03` and `0003` are the same ADR; anything but digits is a usage error."""
        ...

    def load_all(self) -> list[AdrInfo]:
        """Every ADR, ordered by number."""
        ...

    def find(self, number: int) -> AdrInfo: ...

    def set_status(self, number: int, verb: str, allowed_from: str, status: str) -> list[str]:
        """Change the status, only from `allowed_from`. Returns the files written."""
        ...

    def supersede(self, old: int, new: int) -> list[str]:
        """Mark `old` superseded by `new`. Returns the files written."""
        ...


class AgentRunner(Protocol):
    async def run(self, request: AgentRequest) -> AgentReport:
        """One agent turn. Never raises for an agent failure: it is in `report.failure`.
        Cancelling the coroutine stops the agent."""
        ...

    async def ready(self) -> Readiness:
        """Whether the agent can run (for Claude, logged in)."""
        ...
