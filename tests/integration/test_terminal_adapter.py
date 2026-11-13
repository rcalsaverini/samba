"""`StdTerminal`, the `Terminal` port over the real stdin, stdout and `$EDITOR` (spec: cli,
confirmation policy). A pseudo terminal shows what only a real tty does; the confirmation rules
over the port are component tests (`test_app_use_cases.py`, `test_command_messages.py`)."""

from __future__ import annotations

import io
import os
import pty
import select
import subprocess
import sys
from pathlib import Path

import pytest

from samba.adapters.terminal import StdTerminal

ASK = """\
from samba.adapters.terminal import StdTerminal
t = StdTerminal()
print("interactive=" + str(t.is_interactive()), flush=True)
answer = t.ask("Discard task t1? [y/N] ")
print("answer=" + repr(answer), flush=True)
"""


def on_a_pty(script: str, typed: bytes) -> str:
    """Run `script` with stdin and stdout on a pseudo terminal, type `typed`, return the screen."""
    master, slave = pty.openpty()
    proc = subprocess.Popen([sys.executable, "-c", script], stdin=slave, stdout=slave,
                            stderr=slave, close_fds=True)
    os.close(slave)
    out = b""
    sent = False
    try:
        while True:
            ready, _, _ = select.select([master], [], [], 10)
            if not ready:
                break
            try:
                chunk = os.read(master, 1024)
            except OSError:  # the child closed the terminal
                break
            if not chunk:
                break
            out += chunk
            if not sent and b"[y/N] " in out:
                os.write(master, typed)
                sent = True
    finally:
        os.close(master)
        proc.wait(10)
    return out.decode(errors="replace")


@pytest.mark.parametrize("typed, got", [(b"y\n", "'y'"), (b"\n", "''"), (b"n\n", "'n'")])
def test_on_a_tty_the_prompt_is_shown_and_the_typed_line_is_read(typed: bytes, got: str) -> None:
    screen = on_a_pty(ASK, typed)
    assert "interactive=True" in screen
    assert "Discard task t1? [y/N] " in screen
    assert f"answer={got}" in screen


def test_with_pipes_it_is_not_interactive_and_still_reads_a_line() -> None:
    res = subprocess.run([sys.executable, "-c", ASK], input="y\n", capture_output=True,
                         text=True, timeout=30)
    assert "interactive=False" in res.stdout and "answer='y'" in res.stdout


def test_end_of_input_is_an_eof_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    with pytest.raises(EOFError):
        StdTerminal().ask("Title: ")


def test_a_block_ends_at_an_empty_line(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("one\ntwo\n\nafter\n"))
    assert StdTerminal().read_block("Description:") == ["one", "two"]


def editor(tmp_path: Path, body: str) -> str:
    script = tmp_path / "editor.sh"
    script.write_text("#!/bin/sh\n" + body)
    script.chmod(0o755)
    return str(script)


def test_the_editor_from_the_environment_edits_the_text(tmp_path: Path,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EDITOR", editor(tmp_path, 'printf "edited feedback" > "$1"\n'))
    res = StdTerminal().edit("initial")
    assert (res.text, res.error) == ("edited feedback", None)


def test_an_editor_that_fails_changes_nothing(tmp_path: Path,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EDITOR", editor(tmp_path, 'printf "half written" > "$1"\nexit 3\n'))
    res = StdTerminal().edit("initial")
    assert res.text is None
    assert res.error == "editor exited with 3; nothing changed"


def test_a_missing_editor_is_an_error_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EDITOR", "/no/such/editor")
    res = StdTerminal().edit("initial")
    assert res.text is None and res.error is not None and "cannot run editor" in res.error


def test_a_warning_is_one_line_on_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    StdTerminal().warn("samba: unknown task 'x'")
    out = capsys.readouterr()
    assert (out.out, out.err) == ("", "samba: unknown task 'x'\n")
