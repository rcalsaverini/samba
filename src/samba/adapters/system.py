"""System adapters: the real clock and the real id generator."""

from __future__ import annotations

import time
import uuid
from datetime import datetime

from samba.domain.now import Now


class SystemClock:
    def time(self) -> float:
        return time.time()

    def monotonic(self) -> float:
        return time.monotonic()

    def now(self) -> Now:
        t = self.time()
        return Now(
            time=t,
            iso_seconds=datetime.fromtimestamp(t).astimezone().isoformat(timespec="seconds"),
            log_stamp=datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M"),
        )


class UuidGenerator:
    def new_session_id(self) -> str:
        return str(uuid.uuid4())
