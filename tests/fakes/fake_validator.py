"""Scripted `Validator`: returns the given results in order (the last repeats), records calls."""

from __future__ import annotations

from samba.domain.validation import ValidationResult


def passing(output: str = "ok\n") -> ValidationResult:
    return ValidationResult(ok=True, timed_out=False, code=0, output=output, timeout_s=60.0,
                            tail_lines=20)


def failing(output: str = "FAILED\n", *, code: int | None = 1,
            timed_out: bool = False) -> ValidationResult:
    return ValidationResult(ok=False, timed_out=timed_out, code=code, output=output,
                            timeout_s=60.0, tail_lines=20)


class FakeValidator:
    def __init__(self, *results: ValidationResult) -> None:
        self.results = list(results) or [passing()]
        self.calls: list[tuple[str, str]] = []

    async def run(self, location: str, log_name: str) -> ValidationResult:
        self.calls.append((location, log_name))
        res = self.results[min(len(self.calls), len(self.results)) - 1]
        return ValidationResult(res.ok, res.timed_out, res.code, res.output, res.timeout_s,
                                res.tail_lines, f"runs/{log_name}")
