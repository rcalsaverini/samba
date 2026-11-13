"""`TerminalSession`: the `InteractiveSession` port over a child process on the person's terminal.

It builds the `claude` command line of `samba explore` (ADR 0019).
"""

from __future__ import annotations

import signal
import subprocess
from collections.abc import Sequence

from samba.app.ports import ExploreSession, LaunchError


class TerminalSession:
    def __init__(self, command: Sequence[str], model: str | None) -> None:
        self.command = tuple(command)
        self.model = model

    def argv(self, session: ExploreSession) -> list[str]:
        """The topic is the positional first prompt, put right after the command because the flags
        that follow take lists."""
        argv = [*self.command]
        if session.topic:
            argv.append(session.topic)
        argv += ["--append-system-prompt", session.guide,
                 "--allowedTools", *session.allowed,
                 "--disallowedTools", *session.denied]
        if self.model:
            argv += ["--model", self.model]
        return argv

    def run(self, session: ExploreSession) -> int:
        """Inherit stdin, stdout and stderr. Ctrl-C goes to the child (same process group), so
        Samba ignores SIGINT while it runs and exits with the child's code."""
        argv = self.argv(session)
        previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            return subprocess.run(argv, cwd=session.location).returncode
        except (FileNotFoundError, PermissionError) as e:
            raise LaunchError(f"cannot start {argv[0]}: {e.strerror or e}") from e
        finally:
            signal.signal(signal.SIGINT, previous)
