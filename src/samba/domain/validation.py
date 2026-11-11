"""The result of one validation run and its two tail formats (spec: workspaces, Validation)."""

from __future__ import annotations

from dataclasses import dataclass

MAX_ACCEPT_TAIL_LINES = 10


@dataclass(frozen=True)
class ValidationResult:
    """What `Validator.run` returns. `output` is the full text; `tail_lines` and `timeout_s` are the
    configured limits the two tail helpers need; `log_location` is where the full output was
    stored, as opaque text."""

    ok: bool
    timed_out: bool
    code: int | None
    output: str
    timeout_s: float
    tail_lines: int
    log_location: str | None = None


def agent_tail(result: ValidationResult) -> str:
    """The tail fed back to the agent: the last `tail_lines` lines, plus a timeout line."""
    lines = result.output.rstrip().splitlines()
    tail = "\n".join(lines[-result.tail_lines:])
    if result.timed_out:
        tail = (tail + "\n" if tail else "") + f"(timed out after {result.timeout_s}s)"
    return tail


def accept_tail(result: ValidationResult) -> str:
    """The one-line tail shown by `work accept`: non-blank stripped lines joined by ` | `."""
    n = max(1, min(MAX_ACCEPT_TAIL_LINES, result.tail_lines))
    lines = [ln.strip() for ln in result.output.splitlines() if ln.strip()][-n:]
    text = " | ".join(lines)
    if result.timed_out:
        note = f"(timed out after {result.timeout_s:g}s)"
        text = f"{text} {note}".strip()
    return text or "(no output)"
