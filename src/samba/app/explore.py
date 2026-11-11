"""`samba explore`: start the interactive exploration session (spec: cli, explore)."""

from __future__ import annotations

from collections.abc import Sequence

from samba.app.results import Explored, Refused, refused
from samba.domain.launch import explore_launch
from samba.ports import InteractiveSession, LaunchError


class StartExplore:
    def __init__(self, command: Sequence[str], model: str | None, location: str,
                 session: InteractiveSession) -> None:
        self.command = tuple(command)
        self.model = model
        self.location = location
        self.session = session

    def run(self, topic: str | None) -> Explored | Refused:
        spec = explore_launch(self.command, self.model, topic, self.location)
        try:
            return Explored(self.session.run(spec))
        except LaunchError as e:
            return refused(str(e))
