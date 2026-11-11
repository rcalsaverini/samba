"""Subprocess helpers: every child gets its own process group so it can be killed as a whole."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from dataclasses import dataclass
from pathlib import Path

KILL_GRACE_S = 5.0


@dataclass(frozen=True)
class CmdResult:
    code: int | None  # None when killed by timeout
    output: str
    timed_out: bool

    @property
    def ok(self) -> bool:
        return self.code == 0 and not self.timed_out


async def kill_group(proc: asyncio.subprocess.Process) -> None:
    """SIGTERM the process group, then SIGKILL after a grace period."""
    if proc.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGTERM)
    try:
        await asyncio.wait_for(proc.wait(), KILL_GRACE_S)
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signal.SIGKILL)
        await proc.wait()


async def run_cmd(argv: list[str], cwd: Path, timeout: float | None = None) -> CmdResult:
    """Run a command, capturing combined stdout+stderr. Killed (as a group) on timeout or cancel."""
    proc = await asyncio.create_subprocess_exec(
        *argv, cwd=cwd, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT, start_new_session=True)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
        return CmdResult(proc.returncode, out.decode(errors="replace"), False)
    except asyncio.TimeoutError:
        await kill_group(proc)
        return CmdResult(None, "", True)
    finally:
        await kill_group(proc)


async def run_shell(shell: list[str], script: str, cwd: Path,
                    timeout: float | None = None) -> CmdResult:
    return await run_cmd([*shell, script], cwd, timeout)


async def git(cwd: Path, *args: str) -> CmdResult:
    return await run_cmd(["git", *args], cwd, timeout=120)
