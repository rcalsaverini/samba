"""In-memory fake of the AgentRunner port: scripted reports, recorded requests.

Standard library plus the pure domain only. Never imports an adapter.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from samba.domain.agent import AgentReport, AgentRequest, Readiness


class FakeAgentRunner:
    def __init__(self, script: Sequence[AgentReport] | Callable[[AgentRequest], AgentReport],
                 readiness: Readiness | None = None) -> None:
        self._script = script
        self._next = 0
        self._readiness = readiness or Readiness(ok=True, detail="")
        self.requests: list[AgentRequest] = []

    async def run(self, request: AgentRequest) -> AgentReport:
        self.requests.append(request)
        if callable(self._script):
            return self._script(request)
        report = self._script[self._next]
        self._next += 1
        return report

    async def ready(self) -> Readiness:
        return self._readiness
