"""In-memory fake of the `InteractiveSession` port: records the specs, returns a scripted code."""

from __future__ import annotations

from samba.domain.launch import LaunchSpec
from samba.ports import LaunchError


class FakeSession:
    def __init__(self, exit_code: int = 0, error: str | None = None) -> None:
        self.exit_code = exit_code
        self.error = error
        self.specs: list[LaunchSpec] = []

    def run(self, spec: LaunchSpec) -> int:
        self.specs.append(spec)
        if self.error is not None:
            raise LaunchError(self.error)
        return self.exit_code
