"""`LogJournal`, the `Journal` port over `logging`, and `NullJournal`, which records nothing."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from samba.logfmt import kv


class LogJournal:
    """`samba.log` in `samba_dir` at DEBUG and stderr at INFO, `<time> <LEVEL> key=value ...`."""

    def __init__(self, samba_dir: Path) -> None:
        samba_dir.mkdir(parents=True, exist_ok=True)
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        self._log = logging.getLogger("samba")
        self._log.setLevel(logging.DEBUG)
        file_handler = logging.FileHandler(samba_dir / "samba.log")
        file_handler.setFormatter(fmt)
        file_handler.setLevel(logging.DEBUG)
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(fmt)
        console.setLevel(logging.INFO)
        self._handlers: list[logging.Handler] = [file_handler, console]
        for handler in self._handlers:
            self._log.addHandler(handler)

    def close(self) -> None:
        """Detach and close the handlers this journal added."""
        for handler in self._handlers:
            self._log.removeHandler(handler)
            handler.close()
        self._handlers = []

    def debug(self, event: str, **fields: object) -> None:
        self._log.debug(kv(event, **fields))

    def info(self, event: str, **fields: object) -> None:
        self._log.info(kv(event, **fields))

    def warning(self, event: str, **fields: object) -> None:
        self._log.warning(kv(event, **fields))

    def exception(self, event: str, **fields: object) -> None:
        self._log.exception(kv(event, **fields))


class NullJournal:
    """For commands that never wrote a log."""

    def debug(self, event: str, **fields: object) -> None:
        pass

    def info(self, event: str, **fields: object) -> None:
        pass

    def warning(self, event: str, **fields: object) -> None:
        pass

    def exception(self, event: str, **fields: object) -> None:
        pass
