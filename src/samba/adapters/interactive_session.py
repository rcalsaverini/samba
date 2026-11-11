"""`TerminalSession`: the `InteractiveSession` port over a child process on the person's terminal."""

from __future__ import annotations

import signal
import subprocess

from samba.domain.launch import LaunchSpec
from samba.ports import LaunchError


class TerminalSession:
    def run(self, spec: LaunchSpec) -> int:
        """Inherit stdin, stdout and stderr. Ctrl-C goes to the child (same process group), so
        Samba ignores SIGINT while it runs and exits with the child's code."""
        previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            return subprocess.run(spec.argv, cwd=spec.cwd).returncode
        except (FileNotFoundError, PermissionError) as e:
            raise LaunchError(f"cannot start {spec.argv[0]}: {e.strerror or e}") from e
        finally:
            signal.signal(signal.SIGINT, previous)
