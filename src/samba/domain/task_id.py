"""Task identity: validation, slugs from titles, prefix resolution (spec: task-files, Identity). Pure."""

from __future__ import annotations

import re
from collections.abc import Iterable

ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class InvalidTaskId(ValueError):
    pass


class UnknownTask(Exception):
    def __init__(self, text: str) -> None:
        super().__init__(f"unknown task {text!r}")
        self.text = text


class AmbiguousTask(Exception):
    def __init__(self, text: str, candidates: tuple[str, ...]) -> None:
        super().__init__(f"ambiguous task id {text!r}")
        self.text = text
        self.candidates = candidates


class TaskId(str):
    """A valid task id: letters, digits, `.`, `_` and `-`, and not `.` or `..`. A `str`, so it
    works as a file stem, a branch part and a JSON key."""

    __slots__ = ()

    def __new__(cls, text: str) -> TaskId:
        if not TaskId.is_valid(text):
            raise InvalidTaskId(f"invalid task id {text!r}")
        return super().__new__(cls, text)

    @staticmethod
    def is_valid(text: str) -> bool:
        return bool(ID_RE.fullmatch(text)) and text not in (".", "..")

    @staticmethod
    def slug(title: str) -> TaskId:
        """The id a title gives: lower case words joined by `-`, at most 60 characters, `task` if empty."""
        s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        return TaskId(s[:60].strip("-") or "task")

    @staticmethod
    def resolve(known: Iterable[TaskId], text: str) -> TaskId:
        return resolve(known, text)


def resolve(known: Iterable[TaskId], text: str) -> TaskId:
    """An exact id, else the one id `text` is a prefix of. Raises UnknownTask or AmbiguousTask."""
    ids = sorted(set(known))
    if text in ids:
        return TaskId(text)
    matches = [i for i in ids if text and i.startswith(text)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise UnknownTask(text)
    raise AmbiguousTask(text, tuple(matches))
