"""Black-box tests for `task new` (spec: cli). Must not import samba."""

from __future__ import annotations

import os
import select
import subprocess
import time
from pathlib import Path

import pytest
import yaml
from legacy_support import Sandbox, samba_cmd

STATE_DIRS = ("plan-todo", "work-todo")


def md_files(sb: Sandbox) -> list[Path]:
    return sorted(sb.tasks_dir.glob("*/*.md")) if sb.tasks_dir.exists() else []


def front_matter(text: str) -> dict[str, object]:
    if not text.startswith("---\n"):
        return {}
    return yaml.safe_load(text.split("---\n")[1]) or {}


def test_default_destination_is_plan_todo(sb: Sandbox) -> None:
    res = sb.run("task", "new", "Hello")
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == str(sb.tasks_dir / "plan-todo" / "hello.md")
    assert sb.state_of("hello") == "plan-todo"


def test_skip_plan_goes_to_work_todo(sb: Sandbox) -> None:
    res = sb.run("task", "new", "Hello", "--skip-plan")
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == str(sb.tasks_dir / "work-todo" / "hello.md")
    assert sb.state_of("hello") == "work-todo"


def test_plan_flag_is_gone(sb: Sandbox) -> None:
    assert sb.run("task", "new", "Hello", "--plan").returncode == 2
    assert md_files(sb) == []


def test_flags_only_full_task(sb: Sandbox) -> None:
    sb.add_task("base-task", state="work-review")
    res = sb.run("task", "new", "Do it", "--body", "Line one.\nLine two.", "--depends-on", "base",
                 "--priority", "4", "--skip-plan")
    assert res.returncode == 0, res.stderr
    path = sb.tasks_dir / "work-todo" / "do-it.md"
    assert res.stdout == f"{path}\n"
    text = path.read_text()
    assert front_matter(text) == {"priority": 4, "depends_on": ["base-task"]}
    assert text.endswith("---\n# Do it\n\nLine one.\nLine two.\n")


def test_defaults_without_tty(sb: Sandbox) -> None:
    res = sb.run("task", "new", "Plain")
    assert res.returncode == 0, res.stderr
    text = (sb.tasks_dir / "plan-todo" / "plain.md").read_text()
    assert front_matter(text) == {"priority": 3}
    assert "depends_on" not in text
    assert text.endswith("---\n# Plain\n\n")
    assert "Describe the goal" not in text


def test_comma_separated_dependencies(sb: Sandbox) -> None:
    sb.add_task("alpha", state="work-review")
    sb.add_task("beta", state="done")
    res = sb.run("task", "new", "Both", "--depends-on", "alp, beta,")
    assert res.returncode == 0, res.stderr
    text = (sb.tasks_dir / "plan-todo" / "both.md").read_text()
    assert front_matter(text)["depends_on"] == ["alpha", "beta"]


def test_unknown_dependency_by_flag_creates_nothing(sb: Sandbox) -> None:
    sb.add_task("alpha", state="work-review")
    before = md_files(sb)
    res = sb.run("task", "new", "Child", "--depends-on", "alpha,ghost")
    assert res.returncode == 2
    assert "ghost" in res.stderr
    assert md_files(sb) == before


def test_ambiguous_dependency_by_flag_creates_nothing(sb: Sandbox) -> None:
    sb.add_task("beta-one", state="work-review")
    sb.add_task("beta-two", state="done")
    before = md_files(sb)
    res = sb.run("task", "new", "Child", "--depends-on", "beta")
    assert res.returncode == 2
    assert "beta-one" in res.stderr and "beta-two" in res.stderr
    assert md_files(sb) == before


def test_no_title_and_no_tty_is_a_usage_error(sb: Sandbox) -> None:
    res = sb.run("task", "new")
    assert res.returncode == 2
    assert "usage" in res.stderr.lower() or "title" in res.stderr.lower()
    assert md_files(sb) == []


# ---- TTY ---------------------------------------------------------------------------------------


class Pty:
    """Drives `samba task new` on a pty: wait for a prompt, then answer."""

    def __init__(self, sb: Sandbox, *args: str) -> None:
        import pty
        self.master, slave = pty.openpty()
        self.proc = subprocess.Popen([*samba_cmd(), "task", "new", *args, "--repo", str(sb.repo)],
                                     cwd=sb.repo, env=sb.env(), stdin=slave, stdout=slave,
                                     stderr=subprocess.PIPE, text=True)
        os.close(slave)
        self.out = ""

    def expect(self, text: str, timeout: float = 30) -> None:
        end = time.monotonic() + timeout
        while text not in self.out:
            left = end - time.monotonic()
            if left <= 0:
                self.proc.kill()
                raise AssertionError(f"timeout waiting for {text!r}; got {self.out!r}")
            if select.select([self.master], [], [], min(left, 0.5))[0]:
                try:
                    chunk = os.read(self.master, 4096)
                except OSError:
                    chunk = b""
                if not chunk:
                    raise AssertionError(f"eof waiting for {text!r}; got {self.out!r}")
                self.out += chunk.decode(errors="replace")
        self.out = self.out.split(text, 1)[1]

    def send(self, line: str) -> None:
        os.write(self.master, (line + "\n").encode())

    def finish(self) -> int:
        try:
            return self.proc.wait(timeout=30)
        finally:
            self.proc.kill()
            os.close(self.master)


def test_tty_prompts_for_all_fields(sb: Sandbox) -> None:
    pytest.importorskip("pty")
    sb.add_task("alpha", state="work-review")
    t = Pty(sb)
    t.expect("Title:")
    t.send("Prompted task")
    t.expect("Description (end with an empty line):")
    t.send("First line")
    t.send("Second line")
    t.send("")
    t.expect("Depends on (ids or prefixes, comma separated, empty for none):")
    t.send("alp")
    t.expect("Plan first? [Y/n]")
    t.send("n")
    assert t.finish() == 0
    text = (sb.tasks_dir / "work-todo" / "prompted-task.md").read_text()
    assert front_matter(text) == {"priority": 3, "depends_on": ["alpha"]}
    assert text.endswith("---\n# Prompted task\n\nFirst line\nSecond line\n")


def test_tty_reasks_empty_title_and_bad_dependency(sb: Sandbox) -> None:
    pytest.importorskip("pty")
    sb.add_task("alpha", state="work-review")
    t = Pty(sb)
    t.expect("Title:")
    t.send("")
    t.expect("Title:")
    t.send("Again")
    t.expect("Description (end with an empty line):")
    t.send("")
    t.expect("Depends on (ids or prefixes, comma separated, empty for none):")
    t.send("ghost")
    t.expect("Depends on (ids or prefixes, comma separated, empty for none):")
    t.send("alpha")
    t.expect("Plan first? [Y/n]")
    t.send("")
    assert t.finish() == 0
    assert sb.state_of("again") == "plan-todo"
    assert front_matter((sb.tasks_dir / "plan-todo" / "again.md").read_text())["depends_on"] == [
        "alpha"]


def test_tty_only_prompts_for_missing_fields(sb: Sandbox) -> None:
    pytest.importorskip("pty")
    t = Pty(sb, "Given title", "--body", "b", "--depends-on", "", "--skip-plan")
    assert t.finish() == 0
    assert "Title:" not in t.out
    assert sb.state_of("given-title") == "work-todo"
