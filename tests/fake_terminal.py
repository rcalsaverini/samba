"""Scripted `Terminal` and a fake `RepoLock` for in-process tests."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import AbstractContextManager, contextmanager

from samba.ports import EditResult


class FakeTerminal:
    def __init__(self, interactive: bool = True, lines: list[str] | None = None,
                 edits: list[EditResult] | None = None) -> None:
        self.interactive = interactive
        self.lines = list(lines or [])
        self.edits = list(edits or [])
        self.prompts: list[str] = []
        self.edit_initials: list[str] = []
        self.warnings: list[str] = []

    def is_interactive(self) -> bool:
        return self.interactive

    def ask(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self.lines:
            raise EOFError
        return self.lines.pop(0)

    def read_block(self, prompt: str) -> list[str]:
        self.prompts.append(prompt)
        block: list[str] = []
        while self.lines and self.lines[0]:
            block.append(self.lines.pop(0))
        if self.lines:
            self.lines.pop(0)
        return block

    def warn(self, line: str) -> None:
        self.warnings.append(line)

    def edit(self, initial: str) -> EditResult:
        self.edit_initials.append(initial)
        return self.edits.pop(0)


class FakeLock:
    def __init__(self, held: bool = True) -> None:
        self.held = held
        self.entered = 0

    def acquire(self, blocking: bool = True) -> AbstractContextManager[bool]:
        @contextmanager
        def ctx() -> Generator[bool]:
            self.entered += 1
            yield self.held
        return ctx()
