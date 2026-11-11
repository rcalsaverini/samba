"""Ports: the interfaces the core needs from the outside world (spec: architecture).

Protocols only. Adapters in `samba.adapters` implement them; nothing here may import them.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from samba.domain.agent import AgentReport, AgentRequest, Readiness
from samba.domain.launch import LaunchSpec
from samba.domain.validation import ValidationResult

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


class Lock(Protocol):
    """The advisory lock that serialises state-changing commands and the orchestrator."""

    def acquire(self, blocking: bool = True) -> AbstractContextManager[bool]:
        """Hold the lock for a `with` block. Yields True once held, False (holding nothing) if
        it could not be had."""
        ...


class WorkspaceError(Exception):
    """A workspace could not be created or removed."""


@dataclass(frozen=True)
class Workspace:
    """A task's workspace: where it is (opaque) and whether `ensure_workspace` just made it."""

    location: str
    created: bool


MergeAttemptStatus = Literal["pending", "already", "conflict", "error"]


@dataclass(frozen=True)
class MergeAttempt:
    """What `Vcs.begin_merge` returns. `pending`: merged without committing, `detail` empty;
    `already`: nothing to merge; `conflict`: `detail` lists the files; `error`: the git error.
    `restore_point` is what `abort_merge` and `commit_merge` need to put the checkout back."""

    status: MergeAttemptStatus
    detail: str = ""
    restore_point: str = ""


@dataclass(frozen=True)
class CommitResult:
    """What `Vcs.commit_merge` returns: `detail` is the short sha when `ok`, else the git error."""

    ok: bool
    detail: str = ""


class Vcs(Protocol):
    """The repository: per-task workspaces and the merge steps of `work accept` (spec: workspaces,
    cli). Locations are opaque text. Every method is async."""

    def branch_name(self, task_id: str) -> str:
        """The branch the task's work lives on."""
        ...

    def workspace_location(self, task_id: str) -> str:
        """Where the task's workspace is (or would be)."""
        ...

    async def ensure_workspace(self, task_id: str) -> Workspace:
        """Create the workspace if needed, running the `after_create` hook on a new one. Raises
        `WorkspaceError(message)`; a workspace whose hook failed is removed."""
        ...

    async def remove_workspace(self, task_id: str) -> None:
        """Raises `WorkspaceError(message)` when it cannot be removed."""
        ...

    async def existing_workspaces(self) -> list[str]:
        """Ids of the tasks that have a workspace."""
        ...

    async def repository_problem(self) -> str | None:
        """A message when the repository root or the base branch is wrong, else None."""
        ...

    async def preflight(self, branch: str) -> str | None:
        """A message for the first failed check of `work accept`, or None."""
        ...

    async def commit_count(self, branch: str) -> int:
        """Commits on `branch` not yet in the base branch."""
        ...

    async def begin_merge(self, branch: str, message: str) -> MergeAttempt:
        """Merge `branch` into the main checkout without committing. On conflict or error the
        checkout is already restored."""
        ...

    async def abort_merge(self, restore_point: str) -> None:
        """Put the main checkout back as it was before `begin_merge`."""
        ...

    async def commit_merge(self, restore_point: str) -> CommitResult:
        """Commit the pending merge; on failure undo it."""
        ...

    def checkout_location(self) -> str:
        """The main checkout, where `work accept` validates."""
        ...

    async def exclude_samba_dir(self) -> None:
        """Keep the Samba directory out of `git status`, when it is inside the repository."""
        ...


class Validator(Protocol):
    """Runs the validation command in a location (spec: workspaces, Validation)."""

    async def run(self, location: str, log_name: str) -> ValidationResult:
        """Run it, store the full output under `log_name` (relative to the runs directory) and
        return the result. Never raises for a failing command."""
        ...


class Journal(Protocol):
    """The event log (spec: observability). Fields with value None are left out."""

    def debug(self, event: str, **fields: object) -> None: ...

    def info(self, event: str, **fields: object) -> None: ...

    def warning(self, event: str, **fields: object) -> None: ...

    def exception(self, event: str, **fields: object) -> None:
        """Error level, with the traceback of the exception being handled."""
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


class LaunchError(Exception):
    """An interactive program could not be started (for example `claude` is not installed)."""


class InteractiveSession(Protocol):
    """A program run attached to the person's terminal (spec: architecture, Ports; cli, explore)."""

    def run(self, spec: LaunchSpec) -> int:
        """Run it until it exits and return its exit code. Raises `LaunchError(message)` when it
        cannot be started."""
        ...


class AgentRunner(Protocol):
    async def run(self, request: AgentRequest) -> AgentReport:
        """One agent turn. Never raises for an agent failure: it is in `report.failure`.
        Cancelling the coroutine stops the agent."""
        ...

    async def ready(self) -> Readiness:
        """Whether the agent can run (for Claude, logged in)."""
        ...
