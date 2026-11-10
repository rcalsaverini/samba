"""System adapters: the real clock and the real id generator."""

from __future__ import annotations

import time
import uuid


class SystemClock:
    def time(self) -> float:
        return time.time()

    def monotonic(self) -> float:
        return time.monotonic()


class UuidGenerator:
    def new_session_id(self) -> str:
        return str(uuid.uuid4())
