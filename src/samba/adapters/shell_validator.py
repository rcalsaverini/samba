"""`ShellValidator`: the `Validator` port over the configured shell command."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from samba.domain.validation import ValidationResult
from samba.adapters.process import run_shell


@dataclass(frozen=True)
class ValidatorSettings:
    """The `validate.*` keys and `shell` of `WORKFLOW.md`."""

    command: str | None
    shell: tuple[str, ...]
    timeout_s: float
    tail_lines: int


class ShellValidator:
    def __init__(self, settings: ValidatorSettings, runs_dir: Path) -> None:
        self.validation = settings
        self.runs_dir = runs_dir

    async def run(self, location: str, log_name: str) -> ValidationResult:
        val = self.validation
        assert val.command
        res = await run_shell(val.shell, val.command, Path(location), val.timeout_s)
        log = self.runs_dir / log_name
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(res.output)
        return ValidationResult(ok=res.ok, timed_out=res.timed_out, code=res.code,
                                output=res.output, timeout_s=val.timeout_s,
                                tail_lines=val.tail_lines, log_location=str(log))
