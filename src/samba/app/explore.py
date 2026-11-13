"""`samba explore`: start the interactive exploration session (spec: cli, explore)."""

from __future__ import annotations

from collections.abc import Sequence

from samba.app.ports import ExploreSession, InteractiveSession, LaunchError
from samba.app.results import Explored, Refused, refused


class StartExplore:
    def __init__(self, guide: str, allowed: Sequence[str], denied: Sequence[str], location: str,
                 session: InteractiveSession) -> None:
        self.guide = guide
        self.allowed = tuple(allowed)
        self.denied = tuple(denied)
        self.location = location
        self.session = session

    def run(self, topic: str | None) -> Explored | Refused:
        request = ExploreSession(topic, self.guide, self.allowed, self.denied, self.location)
        try:
            return Explored(self.session.run(request))
        except LaunchError as e:
            return refused(str(e))
