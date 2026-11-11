"""The confirmation policy of dangerous commands (spec: cli)."""

from __future__ import annotations

from samba.app.results import Refused, refused, usage
from samba.domain.ports import Terminal


def confirm(terminal: Terminal, prompt: str, command: str, yes: bool) -> Refused | None:
    """None to proceed. `--yes` skips; without a terminal the command is a usage error; else ask
    `[y/N]` and anything but y/yes declines."""
    if yes:
        return None
    if not terminal.is_interactive():
        return usage(f"{command} needs confirmation: run it on a terminal or pass --yes; "
                     "nothing changed")
    try:
        answer = terminal.ask(f"{prompt}? [y/N] ")
    except EOFError:
        answer = ""
    if answer.strip().lower() not in ("y", "yes"):
        return refused("not confirmed; nothing changed")
    return None
