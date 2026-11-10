"""Folder-based task store and orchestrator sidecar state (spec: task-files, states)."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, cast

from samba.adapters.system import SystemClock
from samba.config import ConfigError, split_front_matter
from samba.domain.deps import TaskRef
from samba.domain.questions import render_questions
from samba.domain.sidecar import Sidecar
from samba.domain.states import STATES, State
from samba.ports import Clock

# Folders of the pre-stage layout (spec: orchestrator, Startup, refuses to start while they hold task files).
LEGACY_STATES: tuple[str, ...] = ("plan", "todo", "running", "review", "blocked")

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
    depends_on: tuple[str, ...] = ()


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
    deps_raw = front.get("depends_on")
    depends_on: tuple[str, ...] = ()
    if isinstance(deps_raw, list):
        items = cast(list[object], deps_raw)
        if all(isinstance(d, str) for d in items):
            depends_on = tuple(cast(list[str], items))
    title = task_id
    for line in body.splitlines():
        if line.startswith("# "):
            title = line[2:].strip() or task_id
            break
    return Task(id=task_id, state=state, path=path, title=title, body=body.strip(),
                priority=priority, mtime=path.stat().st_mtime, depends_on=depends_on)


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

    def ids(self, state: State) -> list[str]:
        """Valid task ids in a state, without reading the files."""
        d = self.root / state
        return [p.stem for p in sorted(d.glob("*.md")) if is_valid_id(p.stem)] if d.is_dir() else []

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

    def deps_snapshot(self, task: Task) -> dict[str, TaskRef]:
        """The task and everything reachable through `depends_on`, for `domain.deps.evaluate`.
        Ids with no task file are left out (unknown). A done task's own dependencies are not
        followed: they cannot take part in a cycle."""
        snap: dict[str, TaskRef] = {task.id: TaskRef(task.id, task.state, task.depends_on)}
        stack = list(task.depends_on)
        while stack:
            dep_id = stack.pop()
            if dep_id in snap:
                continue
            dep = self.find(dep_id)
            if dep is None:
                continue
            snap[dep_id] = TaskRef(dep.id, dep.state, dep.depends_on)
            if dep.state != "done":
                stack.extend(dep.depends_on)
        return snap

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

    def append_feedback(self, task_id: str, text: str) -> int | None:
        """Append `text` as a new round of `## Feedback`. Returns the round number, or None if
        the task does not exist."""
        state = self.state_of(task_id)
        if state is None:
            return None
        p = self.path(task_id, state)
        new_text, n = append_to_feedback_section(p.read_text(), text)
        p.write_text(new_text)
        return n

    def render_questions(self, task_id: str, questions: list[dict[str, object]]) -> None:
        """Regenerate `## Questions` from the records (spec: task-files, Write discipline). No records: no section."""
        if questions:
            self.set_section(task_id, "Questions", render_questions(questions))

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


ROUND_RE = re.compile(r"^### Round (\d+)\s*$")


def append_to_feedback_section(text: str, feedback: str) -> tuple[str, int]:
    """Append `feedback` under a new `### Round N` heading at the end of `## Feedback`, creating
    the section (before `## Log`) if missing. Earlier rounds and prose are never rewritten.
    Returns the new text and N (one more than the highest existing round)."""
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.strip() == "## Feedback"), None)
    if start is None:
        return replace_section(text, "Feedback", f"### Round 1\n\n{_demote(feedback)}"), 1
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## "):
            end = i
            break
    rounds = [int(m.group(1)) for ln in lines[start + 1:end] if (m := ROUND_RE.match(ln))]
    n = max(rounds, default=0) + 1
    insert_at = end
    while insert_at > start + 1 and not lines[insert_at - 1].strip():
        insert_at -= 1
    block = ["", f"### Round {n}", "", *_demote(feedback).splitlines()]
    if end < len(lines):
        block.append("")
    lines[insert_at:end] = block
    return "\n".join(lines).rstrip("\n") + "\n", n


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


class SidecarStore:
    def __init__(self, root: Path, clock: Clock | None = None) -> None:
        self.root = root
        self.clock: Clock = clock or SystemClock()

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
        if not isinstance(data.get("questions", []), list):
            data.pop("questions")
        try:
            return Sidecar(**{k: v for k, v in data.items() if k in known})
        except TypeError:
            return Sidecar()

    def save(self, task_id: str, sidecar: Sidecar) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        sidecar.updated_at = self.clock.time()
        p = self.root / f"{task_id}.json"
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(sidecar), indent=2) + "\n")
        os.replace(tmp, p)
