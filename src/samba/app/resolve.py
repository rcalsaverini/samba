"""Resolving a task id or unique prefix (shared by every command that takes an id)."""

from __future__ import annotations

from samba.domain.task_id import AmbiguousTask, TaskId, UnknownTask
from samba.domain.ports import Tasks


class ResolveError(Exception):
    """A state or task id argument did not resolve. `candidates` lists the valid or close names."""

    def __init__(self, message: str, candidates: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.candidates = candidates

    def render(self) -> str:
        text = str(self)
        if self.candidates:
            text += "\n" + "\n".join(f"  {c}" for c in self.candidates)
        return text


def resolve_task_id(tasks: Tasks, text: str) -> TaskId:
    """An exact id, else a unique prefix of an id in any status (`TaskId.resolve`)."""
    try:
        return TaskId.resolve(tasks.ids(), text)
    except UnknownTask:
        raise ResolveError(f"unknown task {text!r}") from None
    except AmbiguousTask as e:
        raise ResolveError(f"ambiguous task id {text!r}; candidates:", e.candidates) from None


def resolve_deps(tasks: Tasks, text: str) -> list[TaskId]:
    """Comma separated ids or prefixes to full ids, in order, without repeats. Raises ResolveError."""
    ids: list[TaskId] = []
    for part in text.split(","):
        part = part.strip()
        if part:
            found = resolve_task_id(tasks, part)
            if found not in ids:
                ids.append(found)
    return ids
