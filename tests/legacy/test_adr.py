"""Black-box tests for `samba adr` (spec: cli, ADR commands). Must not import samba."""

from __future__ import annotations

import subprocess
from pathlib import Path

from legacy_support import Sandbox, flag, git, samba_cmd


def adr_text(number: int, title: str, status: str = "accepted", decision: str | None = None,
             supersedes: str = "[]") -> str:
    decision = decision if decision is not None else f"- Decision {number} is made. Second sentence."
    return (f"---\nstatus: {status}\ndate: 2026-11-08\nsupersedes: {supersedes}\n---\n\n"
            f"# {number:04d}: {title}\n\n## Context\n\nWhy.\n\n## Decision\n\n{decision}\n\n"
            f"## Consequences\n\n- Some.\n")


def write_adr(sb: Sandbox, number: int, title: str, **kw: str) -> Path:
    d = sb.repo / "docs" / "adr"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{number:04d}-{title.lower().replace(' ', '-')}.md"
    p.write_text(adr_text(number, title, **kw))
    return p


def commit_all(sb: Sandbox) -> None:
    git(sb.repo, "add", "-A")
    git(sb.repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "adrs")


def seed(sb: Sandbox) -> None:
    write_adr(sb, 1, "First one", status="accepted")
    write_adr(sb, 2, "Second one", status="superseded")
    write_adr(sb, 3, "Third one", status="proposed")
    write_adr(sb, 4, "Fourth one", status="rejected")
    write_adr(sb, 12, "Twelfth one", status="accepted")
    commit_all(sb)


def test_list_shows_only_accepted_with_summary(sb: Sandbox) -> None:
    seed(sb)
    res = sb.run("adr", "list")
    assert res.returncode == 0, res.stderr
    lines = res.stdout.splitlines()
    assert lines[0].split() == ["NUMBER", "TITLE", "SUMMARY"]
    assert len(lines) == 3
    assert lines[1].split()[:3] == ["0001", "First", "one"]
    assert "Decision 1 is made." in lines[1] and "Second sentence" not in lines[1]
    assert lines[2].split()[:3] == ["0012", "Twelfth", "one"]


def test_list_all_adds_status_and_every_adr(sb: Sandbox) -> None:
    seed(sb)
    res = sb.run("adr", "list", "--all")
    assert res.returncode == 0, res.stderr
    lines = res.stdout.splitlines()
    assert lines[0].split() == ["NUMBER", "STATUS", "TITLE", "SUMMARY"]
    assert [ln.split()[0] for ln in lines[1:]] == ["0001", "0002", "0003", "0004", "0012"]
    assert [ln.split()[1] for ln in lines[1:]] == [
        "accepted", "superseded", "proposed", "rejected", "accepted"]


def test_summary_is_first_sentence_of_decision(sb: Sandbox) -> None:
    write_adr(sb, 1, "Wrapped", decision="- A decision that wraps\n  over two lines. Then more.\n- Next bullet.")
    write_adr(sb, 2, "Prose", decision="Plain paragraph without a bullet. And more.")
    write_adr(sb, 3, "No period", decision="- Only one bullet\n- Another bullet.")
    res = sb.run("adr", "list")
    lines = res.stdout.splitlines()
    assert lines[1].endswith("A decision that wraps over two lines.")
    assert lines[2].endswith("Plain paragraph without a bullet.")
    assert lines[3].endswith("Only one bullet")


def test_list_truncates_summary_to_terminal_width(sb: Sandbox) -> None:
    write_adr(sb, 1, "Long", decision="- " + "word " * 40 + "end.")
    res = sb.run("adr", "list", COLUMNS="50")
    lines = res.stdout.splitlines()
    assert len(lines[1]) <= 50 and lines[1].endswith("...")
    assert lines[1].split()[:2] == ["0001", "Long"]


def test_list_without_adr_dir_or_workflow(sb: Sandbox) -> None:
    (sb.repo / "WORKFLOW.md").unlink()
    res = sb.run("adr", "list")
    assert res.returncode == 0, res.stderr
    assert res.stdout.split() == ["NUMBER", "TITLE", "SUMMARY"]


def test_show_number_forms_and_any_status(sb: Sandbox) -> None:
    seed(sb)
    p = next((sb.repo / "docs" / "adr").glob("0003-*"))
    outs = [sb.run("adr", "show", n) for n in ("3", "03", "0003")]
    for res in outs:
        assert res.returncode == 0, res.stderr
        assert res.stdout == p.read_text()
    assert sb.run("adr", "show", "2").stdout.startswith("---\nstatus: superseded")


def test_unknown_and_malformed_numbers(sb: Sandbox) -> None:
    seed(sb)
    for args in (("show", "99"), ("show", "abc"), ("show", "-1"), ("accept", "x"),
                 ("accept", "99"), ("supersede", "1", "99"), ("supersede", "1", "zz")):
        res = sb.run("adr", *args)
        assert res.returncode == 2, (args, res.stderr)
        assert res.stderr.strip(), args
        assert res.stdout == ""


def test_accept_and_reject_edit_one_line_and_never_commit(sb: Sandbox) -> None:
    write_adr(sb, 1, "One", status="proposed")
    write_adr(sb, 2, "Two", status="proposed")
    commit_all(sb)
    before = git(sb.repo, "rev-list", "--count", "HEAD")
    p1 = next((sb.repo / "docs" / "adr").glob("0001-*"))
    p2 = next((sb.repo / "docs" / "adr").glob("0002-*"))
    old1, old2 = p1.read_text(), p2.read_text()

    res = sb.run("adr", "accept", "1")
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == str(p1)
    assert p1.read_text() == old1.replace("status: proposed", "status: accepted")
    res = sb.run("adr", "reject", "0002")
    assert res.returncode == 0, res.stderr
    assert p2.read_text() == old2.replace("status: proposed", "status: rejected")

    assert git(sb.repo, "rev-list", "--count", "HEAD") == before
    status = git(sb.repo, "status", "--porcelain")
    assert "M docs/adr/0001-one.md" in status and "M docs/adr/0002-two.md" in status


def test_wrong_state_changes_nothing(sb: Sandbox) -> None:
    seed(sb)
    for args in (("accept", "1"), ("reject", "1"), ("accept", "2"), ("reject", "4"),
                 ("supersede", "3", "1"), ("supersede", "2", "1"), ("supersede", "1", "4")):
        res = sb.run("adr", *args)
        assert res.returncode == 1, (args, res.stderr)
        assert "not allowed" in res.stderr or "cannot supersede" in res.stderr, res.stderr
    assert git(sb.repo, "status", "--porcelain") == ""


def test_supersede_marks_old_and_lists_it_in_new(sb: Sandbox) -> None:
    write_adr(sb, 1, "Old", status="accepted")
    write_adr(sb, 2, "Other", status="accepted")
    write_adr(sb, 3, "New", status="proposed", supersedes="[2]")
    write_adr(sb, 4, "Newer", status="proposed")
    commit_all(sb)
    d = sb.repo / "docs" / "adr"
    res = sb.run("adr", "supersede", "1", "3")
    assert res.returncode == 0, res.stderr
    assert "status: superseded" in next(d.glob("0001-*")).read_text()
    new = next(d.glob("0003-*")).read_text()
    assert "supersedes: [2, 1]" in new and "status: proposed" in new
    res = sb.run("adr", "supersede", "2", "4")
    assert res.returncode == 0, res.stderr
    assert "supersedes: [2]" in next(d.glob("0004-*")).read_text()
    assert [ln.split()[0] for ln in sb.run("adr", "list").stdout.splitlines()[1:]] == []
    assert git(sb.repo, "rev-list", "--count", "HEAD") == "2"


def test_supersede_itself_is_usage_error(sb: Sandbox) -> None:
    seed(sb)
    res = sb.run("adr", "supersede", "1", "01")
    assert res.returncode == 2
    assert git(sb.repo, "status", "--porcelain") == ""


def test_adr_without_front_matter_is_an_error(sb: Sandbox) -> None:
    d = sb.repo / "docs" / "adr"
    d.mkdir(parents=True)
    (d / "0001-bad.md").write_text("# 0001: Bad\n\nNo front matter.\n")
    commit_all(sb)
    for args in (("accept", "1"), ("show", "1"), ("list",)):
        res = sb.run("adr", *args)
        assert res.returncode == 1, (args, res.stderr)
        assert "front matter" in res.stderr
    assert git(sb.repo, "status", "--porcelain") == ""


def test_help_lists_adr_verbs(sb: Sandbox) -> None:
    res = subprocess.run([*samba_cmd(), "adr", "--help"],
                         capture_output=True, text=True)
    assert res.returncode == 0
    for verb in ("list", "show", "accept", "reject", "supersede"):
        assert verb in res.stdout


def test_default_allow_has_read_commands_only(sb: Sandbox) -> None:
    sb.add_task("w1", state="work-todo")
    sb.add_task("p1", state="plan-todo")
    sb.run_idle()
    for tid in ("w1", "p1"):
        argv = sb.calls(tid)[0]
        allow = argv[argv.index("--allowedTools") + 1:]
        assert "Bash(samba adr list:*)" in allow and "Bash(samba adr show:*)" in allow
        assert not any("adr accept" in a or "adr reject" in a or "adr supersede" in a
                       or a == "Bash(samba adr:*)" for a in allow)
        system = flag(argv, "--append-system-prompt") or ""
        assert "samba adr list" in system and "samba adr show" in system
