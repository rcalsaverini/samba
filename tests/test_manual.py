"""Keeps docs/manual.md from drifting away from the CLI.

Black-box like the rest of the suite: it runs the CLI (`samba_cmd()`, honors SAMBA_CMD) and reads
files. It never imports `samba`. The expected commands come from `--help` itself, so adding a
subcommand without documenting it fails here.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from conftest import samba_cmd

ROOT = Path(__file__).parent.parent
MANUAL = ROOT / "docs" / "manual.md"
README = ROOT / "README.md"
EM_DASH = chr(0x2014)


def help_text(*words: str) -> str:
    res = subprocess.run([*samba_cmd(), *words, "--help"], capture_output=True, text=True,
                         timeout=60)
    assert res.returncode == 0, res.stderr
    return res.stdout


def top_level_commands() -> list[str]:
    """Names listed under `Commands:`, plus those under the epilog's `development commands:`."""
    names = command_block(help_text())
    names.extend(command_block(help_text(), "development commands:"))
    return names


def command_block(text: str, header: str = "Commands:") -> list[str]:
    """Names in the block that follows the line `header` of a plain Click help text."""
    names: list[str] = []
    in_block = False
    for line in text.splitlines():
        if line.strip() == header:
            in_block = True
        elif in_block:
            m = re.match(r"^\s+([a-z][a-z-]*)(\s{2,}|$)", line)
            if m:
                names.append(m.group(1))
            elif line.strip():
                break
    return names


def verbs(noun: str) -> list[str]:
    """Verbs of a noun, from its `Commands:` block; empty for a leaf command."""
    return command_block(help_text(noun))


def test_manual_documents_shell_completion() -> None:
    text = MANUAL.read_text()
    for needle in ("--install-completion", "--show-completion"):
        assert needle in text, needle


def documented_commands() -> list[str]:
    commands: list[str] = []
    for name in top_level_commands():
        found = verbs(name)
        if found:
            commands.extend(f"{name} {v}" for v in found)
        else:
            commands.append(name)
    return commands


def test_command_discovery_is_not_vacuous() -> None:
    commands = documented_commands()
    for known in ("run", "task new", "plan accept", "work accept", "question answer",
                  "dev transitions"):
        assert known in commands, commands


def test_manual_mentions_every_subcommand() -> None:
    assert MANUAL.exists(), "docs/manual.md is missing"
    text = MANUAL.read_text()
    missing = [c for c in documented_commands() if f"samba {c}" not in text]
    assert not missing, f"docs/manual.md does not mention: {missing}"


def test_docs_have_no_em_dashes() -> None:
    for path in (README, MANUAL):
        assert path.exists(), f"{path.name} is missing"
        assert EM_DASH not in path.read_text(), f"{path.name} contains an em-dash"
