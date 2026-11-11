"""`StdTerminal`: the `Terminal` port over stdin, stdout and `$EDITOR`."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from samba.domain.ports import EditResult


class StdTerminal:
    def is_interactive(self) -> bool:
        return sys.stdin.isatty() and sys.stdout.isatty()

    def ask(self, prompt: str) -> str:
        print(prompt, end="", flush=True)
        line = sys.stdin.readline()
        if not line:
            raise EOFError
        return line.rstrip("\r\n")

    def read_block(self, prompt: str) -> list[str]:
        print(prompt, flush=True)
        lines: list[str] = []
        while True:
            line = sys.stdin.readline().rstrip("\r\n")
            if not line:  # an empty line or EOF
                break
            lines.append(line)
        return lines

    def warn(self, line: str) -> None:
        print(line, file=sys.stderr)

    def edit(self, initial: str) -> EditResult:
        """`$EDITOR`, then `$VISUAL`, then `vi`."""
        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "edit.md"
            path.write_text(initial)
            try:
                res = subprocess.run([*shlex.split(editor), str(path)])
            except OSError as e:
                return EditResult(error=f"cannot run editor {editor!r}: {e}")
            if res.returncode != 0:
                return EditResult(error=f"editor exited with {res.returncode}; nothing changed")
            return EditResult(text=path.read_text())
