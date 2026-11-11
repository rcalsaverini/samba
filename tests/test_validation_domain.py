"""Unit tests of the two validation tail formats (they must match the old output byte for byte)."""

from __future__ import annotations

from samba.domain.validation import ValidationResult, accept_tail, agent_tail


def result(output: str, *, timed_out: bool = False, timeout_s: float = 60.0,
           tail_lines: int = 3) -> ValidationResult:
    return ValidationResult(ok=False, timed_out=timed_out, code=None if timed_out else 1,
                            output=output, timeout_s=timeout_s, tail_lines=tail_lines)


def test_agent_tail_keeps_the_last_lines_and_blank_lines_inside() -> None:
    assert agent_tail(result("a\nb\n\nc\nd\n\n\n")) == "\nc\nd"


def test_agent_tail_timeout_note_uses_the_plain_number() -> None:
    assert agent_tail(result("a\nb", timed_out=True)) == "a\nb\n(timed out after 60.0s)"
    assert agent_tail(result("", timed_out=True, timeout_s=5)) == "(timed out after 5s)"


def test_agent_tail_of_nothing_is_empty() -> None:
    assert agent_tail(result("")) == ""


def test_accept_tail_drops_blank_lines_strips_and_joins_with_bars() -> None:
    assert accept_tail(result("  a \n\n b\n\n c\nd\n")) == "b | c | d"


def test_accept_tail_caps_at_ten_lines() -> None:
    out = "\n".join(str(i) for i in range(30))
    assert accept_tail(result(out, tail_lines=50)) == " | ".join(str(i) for i in range(20, 30))


def test_accept_tail_always_shows_at_least_one_line() -> None:
    assert accept_tail(result("a\nb", tail_lines=0)) == "b"


def test_accept_tail_timeout_note_uses_the_g_format() -> None:
    assert accept_tail(result("a", timed_out=True)) == "a (timed out after 60s)"
    assert accept_tail(result("", timed_out=True, timeout_s=2.5)) == "(timed out after 2.5s)"


def test_accept_tail_without_output() -> None:
    assert accept_tail(result("\n  \n")) == "(no output)"
