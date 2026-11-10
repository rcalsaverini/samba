"""System adapters: the real clock and the real id generator."""

from __future__ import annotations

import time
import uuid
from datetime import datetime


class SystemClock:
    def time(self) -> float:
        return time.time()

    def monotonic(self) -> float:
        return time.monotonic()

    def iso_seconds(self) -> str:
        return datetime.fromtimestamp(self.time()).astimezone().isoformat(timespec="seconds")

    def log_stamp(self) -> str:
        return datetime.fromtimestamp(self.time()).strftime("%Y-%m-%d %H:%M")


class UuidGenerator:
    def new_session_id(self) -> str:
        return str(uuid.uuid4())
