"""Every command binding reaches its use case: one run of each through the real command line."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from e2e_box import Box

ADR = ("---\nstatus: {status}\ndate: 2026-11-08\nsupersedes: []\n---\n\n# {n:04d}: Title {n}\n\n"
       "## Context\n\nWhy.\n\n## Decision\n\n- Decide {n}.\n\n## Consequences\n\n- Some.\n")


def adr(box: Box, n: int, status: str) -> Path:
    d = box.repo / "docs" / "adr"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{n:04d}-title-{n}.md"
    p.write_text(ADR.format(status=status, n=n))
    return p


@pytest.fixture
def ready(box: Box) -> Box:
    """A plan in review, work in review, a question, and ADRs in each status."""
    box.new_task("Planned")
    box.new_task("Worked", "--skip-plan")
    box.new_task("Asking", "--skip-plan")
    box.steps("asking", {"outcome": "blocked", "summary": "need input",
                         "questions": [{"text": "Which db?", "context": "storage"}]})
    box.run_idle()
    assert [box.state_of(t) for t in ("planned", "worked", "asking")] == [
        "plan-review", "work-review", "question"]
    for n, status in ((1, "accepted"), (2, "proposed"), (3, "proposed"), (4, "accepted")):
        adr(box, n, status)
    return box


CASES: dict[str, tuple[tuple[str, ...], Callable[[Box, str], bool]]] = {
    "task show": (("task", "show", "plan"), lambda b, out: "state: plan-review" in out),
    "plan reject": (("plan", "reject", "planned", "--feedback", "Split it."),
                    lambda b, out: b.state_of("planned") == "plan-todo"
                    and "Split it." in b.task_text("planned")),
    "work reject": (("work", "reject", "worked", "--feedback", "Add tests.", "--fresh"),
                    lambda b, out: b.state_of("worked") == "work-todo"),
    "question show": (("question", "show", "asking/q1"),
                      lambda b, out: "Which db?" in out and "Context: storage" in out),
    "adr show": (("adr", "show", "1"), lambda b, out: out.startswith("---\nstatus: accepted")),
    "adr accept": (("adr", "accept", "2"),
                   lambda b, out: "status: accepted" in Path(out.strip()).read_text()),
    "adr reject": (("adr", "reject", "3"),
                   lambda b, out: "status: rejected" in Path(out.strip()).read_text()),
    "adr supersede": (("adr", "supersede", "1", "4"),
                      lambda b, out: "status: superseded" in adr_text(b, 1)),
}


def adr_text(box: Box, n: int) -> str:
    return next((box.repo / "docs" / "adr").glob(f"{n:04d}-*")).read_text()


@pytest.mark.parametrize("name", sorted(CASES))
def test_each_command_runs_its_use_case_and_prints_its_result(ready: Box, name: str) -> None:
    """The binding from words to a use case exists only in the command line."""
    words, check = CASES[name]
    res = ready.run(*words)
    assert res.returncode == 0, (name, res.stderr)
    assert check(ready, res.stdout), (name, res.stdout)
