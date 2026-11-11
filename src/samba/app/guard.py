"""`Guard`: the external guards of the transition table (spec: states, Guards)."""

from __future__ import annotations

from samba.domain.deps import deps_snapshot, evaluate
from samba.domain.ports import Tasks
from samba.domain.task import Task


class Guard:
    """Answers `plan_required` and `deps_met` for `Machine`; any other name does not hold."""

    def __init__(self, require_plan: bool, tasks: Tasks) -> None:
        self.require_plan = require_plan
        self.tasks = tasks

    def __call__(self, name: str, task: Task) -> bool:
        if name == "plan_required":
            return self.require_plan and not task.plan_approved
        if name == "deps_met":
            return evaluate(deps_snapshot(task, self.tasks.get), task.id).kind == "ready"
        return False
