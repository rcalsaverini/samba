"""Folder-based task store and orchestrator sidecar state (SPEC §3, §4)."""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Literal, cast

from symphony.config import ConfigError, split_front_matter

State = Literal["plan-todo", "plan-running", "plan-review", "work-todo", "work-running",
                "work-review", "question", "stuck", "done", "discarded"]
STATES: tuple[State, ...] = ("plan-todo", "plan-running", "plan-review", "work-todo",
                             "work-running", "work-review", "question", "stuck", "done",
                             "discarded")
Stage = Literal["plan", "work"]
# Folders of the pre-stage layout (SPEC §5.1 refuses to start while they hold task files).
LEGACY_STATES: tuple[str, ...] = ("plan", "todo", "running", "review", "blocked")

# Values of Sidecar.blocked_cause. Plain strings, not a closed type: more are added later.
CAUSE_QUESTION = "question"
CAUSE_BUDGET = "budget"
CAUSE_GAVE_UP = "gave_up"


def todo_of(stage: Stage) -> State:
    return "plan-todo" if stage == "plan" else "work-todo"


def running_of(stage: Stage) -> State:
    return "plan-running" if stage == "plan" else "work-running"
ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True)
class Task:
    id: str
    state: State
    path: Path
    title: str
    body: str
    priority: int | None
    mtime: float


def is_valid_id(task_id: str) -> bool:
    return bool(ID_RE.match(task_id)) and task_id not in (".", "..")


def parse_task(task_id: str, state: State, path: Path) -> Task:
    text = path.read_text()
    try:
        front, body = split_front_matter(text)
    except ConfigError:
        front, body = {}, text
    priority_raw = front.get("priority")
    priority = priority_raw if isinstance(priority_raw, int) and not isinstance(priority_raw, bool) else None
    title = task_id
    for line in body.splitlines():
        if line.startswith("# "):
            title = line[2:].strip() or task_id
            break
    return Task(id=task_id, state=state, path=path, title=title, body=body.strip(),
                priority=priority, mtime=path.stat().st_mtime)


class TaskStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def ensure(self) -> None:
        for s in STATES:
            (self.root / s).mkdir(parents=True, exist_ok=True)

    def legacy_nonempty(self) -> list[str]:
        """Old-layout folders that still hold task files."""
        return [s for s in LEGACY_STATES
                if (self.root / s).is_dir() and any((self.root / s).glob("*.md"))]

    def path(self, task_id: str, state: State) -> Path:
        return self.root / state / f"{task_id}.md"

    def list(self, state: State) -> list[Task]:
        """Valid tasks in a state. Invalid file names are skipped (see invalid_names)."""
        d = self.root / state
        tasks: list[Task] = []
        if not d.is_dir():
            return tasks
        for p in sorted(d.glob("*.md")):
            if is_valid_id(p.stem):
                try:
                    tasks.append(parse_task(p.stem, state, p))
                except OSError:
                    continue  # moved or deleted while listing
        return tasks

    def invalid_names(self, state: State) -> list[str]:
        d = self.root / state
        return [p.name for p in d.glob("*.md") if not is_valid_id(p.stem)] if d.is_dir() else []

    def state_of(self, task_id: str) -> State | None:
        for s in STATES:
            if self.path(task_id, s).exists():
                return s
        return None

    def find(self, task_id: str) -> Task | None:
        state = self.state_of(task_id)
        if state is None:
            return None
        try:
            return parse_task(task_id, state, self.path(task_id, state))
        except OSError:
            return None

    def move(self, task_id: str, src: State, dst: State) -> bool:
        """Atomic rename. Returns False if the file is no longer in `src`."""
        try:
            os.rename(self.path(task_id, src), self.path(task_id, dst))
            return True
        except FileNotFoundError:
            return False

    def append_log(self, task_id: str, line: str) -> None:
        state = self.state_of(task_id)
        if state is None:
            return
        p = self.path(task_id, state)
        p.write_text(append_to_log_section(p.read_text(), line))

    def set_section(self, task_id: str, heading: str, content: str) -> None:
        state = self.state_of(task_id)
        if state is None:
            return
        p = self.path(task_id, state)
        p.write_text(replace_section(p.read_text(), heading, content))


def _demote(content: str) -> str:
    """Turn `#` and `##` headings into `###` so they cannot be mistaken for task sections."""
    out: list[str] = []
    for ln in content.strip().splitlines():
        if ln.startswith("# ") or ln.startswith("## "):
            ln = "### " + ln.split(" ", 1)[1]
        out.append(ln)
    return "\n".join(out)


def replace_section(text: str, heading: str, content: str) -> str:
    """Replace the `## <heading>` section with `content` (never duplicates it).

    A missing section is created before `## Log` if present, else at the end.
    """
    lines = text.splitlines()
    block = [f"## {heading}", *_demote(content).splitlines(), ""]
    start = next((i for i, ln in enumerate(lines) if ln.strip() == f"## {heading}"), None)
    if start is not None:
        end = len(lines)
        for i in range(start + 1, len(lines)):
            if lines[i].startswith("## "):
                end = i
                break
        lines[start:end] = block
    else:
        log_at = next((i for i, ln in enumerate(lines) if ln.strip() == "## Log"), None)
        if log_at is None:
            while lines and not lines[-1].strip():
                lines.pop()
            lines += ["", *block]
        else:
            lines[log_at:log_at] = block
    return "\n".join(lines).rstrip("\n") + "\n"


def append_to_log_section(text: str, line: str) -> str:
    """Append `line` at the end of the `## Log` section, creating the section if missing."""
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.strip() == "## Log"), None)
    if start is None:
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ["", "## Log", line]
        return "\n".join(lines) + "\n"
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## "):
            end = i
            break
    insert_at = end
    while insert_at > start + 1 and not lines[insert_at - 1].strip():
        insert_at -= 1
    lines.insert(insert_at, line)
    following = insert_at + 1
    if following < len(lines) and lines[following].startswith("## "):
        lines.insert(following, "")
    return "\n".join(lines) + "\n"


@dataclass
class Sidecar:
    session_id: str | None = None
    last_stage: str | None = None  # "plan" | "work", set at dispatch (SPEC §4.2)
    blocked_cause: str | None = None  # why the task is in question/stuck (CAUSE_*)
    plan_session_id: str | None = None
    plan_approved: bool = False
    attempts: int = 0
    not_before: float | None = None  # unix timestamp
    last_error: str | None = None
    last_outcome: str | None = None
    turns_total: int = 0
    cost_usd_total: float = 0.0
    input_tokens_total: int = 0
    output_tokens_total: int = 0
    branch: str | None = None
    workspace: str | None = None
    first_dispatched_at: float | None = None
    updated_at: float | None = None


class SidecarStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def load(self, task_id: str) -> Sidecar:
        p = self.root / f"{task_id}.json"
        try:
            raw: Any = json.loads(p.read_text())
        except (OSError, ValueError):
            return Sidecar()
        if not isinstance(raw, dict):
            return Sidecar()
        data = cast(dict[str, Any], raw)
        known = {f.name for f in fields(Sidecar)}
        try:
            return Sidecar(**{k: v for k, v in data.items() if k in known})
        except TypeError:
            return Sidecar()

    def save(self, task_id: str, sidecar: Sidecar) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        sidecar.updated_at = time.time()
        p = self.root / f"{task_id}.json"
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(sidecar), indent=2) + "\n")
        os.replace(tmp, p)
