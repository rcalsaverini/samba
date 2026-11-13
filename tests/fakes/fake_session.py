"""In-memory fake of the `InteractiveSession` port: records the sessions, returns a scripted code."""

from __future__ import annotations

from samba.app.ports import ExploreSession, LaunchError


class FakeSession:
    def __init__(self, exit_code: int = 0, error: str | None = None) -> None:
        self.exit_code = exit_code
        self.error = error
        self.sessions: list[ExploreSession] = []

    def run(self, session: ExploreSession) -> int:
        self.sessions.append(session)
        if self.error is not None:
            raise LaunchError(self.error)
        return self.exit_code
