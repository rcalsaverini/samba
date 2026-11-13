"""`TerminalSession`, the `InteractiveSession` port over a real child process (spec: cli, explore).

Only a real process shows the exact argv it receives, the working directory it starts in and the
error for a program that does not exist. What `StartExplore` asks for is component-tested.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from samba.adapters.interactive_session import TerminalSession
from samba.app.ports import ExploreSession, LaunchError

RECORDER = """\
import json, os, sys
json.dump({"argv": sys.argv[2:], "cwd": os.getcwd()}, open(sys.argv[1], "w"))
"""


def run(tmp_path: Path, topic: str | None, model: str | None) -> dict[str, object]:
    script = tmp_path / "rec.py"
    script.write_text(RECORDER)
    out = tmp_path / "out.json"
    work = tmp_path / "work"
    work.mkdir()
    session = ExploreSession(topic, "the guide", ("A", "B(x:*)"), ("C",), str(work))
    code = TerminalSession([sys.executable, str(script), str(out)], model).run(session)
    assert code == 0
    got: dict[str, object] = json.loads(out.read_text())
    assert got["cwd"] == str(work.resolve())
    return got


def test_topic_and_model_are_in_the_argv_in_order(tmp_path: Path) -> None:
    got = run(tmp_path, "queues", "opus")
    assert got["argv"] == ["queues", "--append-system-prompt", "the guide", "--allowedTools", "A",
                           "B(x:*)", "--disallowedTools", "C", "--model", "opus"]


def test_no_topic_and_no_model_leave_them_out(tmp_path: Path) -> None:
    got = run(tmp_path, None, None)
    assert got["argv"] == ["--append-system-prompt", "the guide", "--allowedTools", "A", "B(x:*)",
                           "--disallowedTools", "C"]


def test_a_missing_program_is_a_launch_error(tmp_path: Path) -> None:
    session = ExploreSession(None, "g", (), (), str(tmp_path))
    with pytest.raises(LaunchError, match="cannot start"):
        TerminalSession(["definitely-not-a-program-xyz"], None).run(session)
