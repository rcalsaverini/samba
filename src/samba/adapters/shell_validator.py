"""`ShellValidator`: the `Validator` port over the configured shell command."""

from __future__ import annotations

from pathlib import Path

from samba.config import Validation
from samba.domain.validation import ValidationResult
from samba.adapters.process import run_shell


class ShellValidator:
    def __init__(self, validation: Validation, runs_dir: Path) -> None:
        self.validation = validation
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
