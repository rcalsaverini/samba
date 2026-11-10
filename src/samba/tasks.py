"""Folder-based task store and orchestrator sidecar state (spec: task-files, states)."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast

from samba.adapters.system import SystemClock
from samba.config import ConfigError, split_front_matter
from samba.ports import Clock

State = Literal["plan-todo", "plan-running", "plan-review", "work-todo", "work-running",
                "work-review", "question", "stuck", "done", "discarded"]
STATES: tuple[State, ...] = ("plan-todo", "plan-running", "plan-review", "work-todo",
                             "work-running", "work-review", "question", "stuck", "done",
                             "discarded")
Stage = Literal["plan", "work"]
# Folders of the pre-stage layout (spec: orchestrator, Startup, refuses to start while they hold task files).
LEGACY_STATES: tuple[str, ...] = ("plan", "todo", "running", "review", "blocked")

# Values of Sidecar.blocked_cause. Plain strings, not a closed type: more are added later.
CAUSE_QUESTION = "question"
CAUSE_BUDGET = "budget"
CAUSE_GAVE_UP = "gave_up"
CAUSE_STOPPED = "stopped"
CAUSE_DEPENDENCY_DISCARDED = "dependency_discarded"
CAUSE_DEPENDENCY_CYCLE = "dependency_cycle"


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


# ---- question records (spec: states, Sidecar state and Questions) -----------------------------------------------------

Question = dict[str, object]


def now_iso(clock: Clock) -> str:
    return datetime.fromtimestamp(clock.time()).astimezone().isoformat(timespec="seconds")


def qint(q: Question, key: str) -> int:
    v = q.get(key)
    return v if isinstance(v, int) else 0


def qstr(q: Question, key: str) -> str:
    v = q.get(key)
    return v if isinstance(v, str) else ""


def question_number(q: Question) -> int:
    qid = qstr(q, "id")
    return int(qid[1:]) if qid[1:].isdigit() else 0


def latest_round(questions: list[Question]) -> int:
    return max((qint(q, "round") for q in questions), default=0)


def round_questions(questions: list[Question]) -> list[Question]:
    """The questions of the latest blocking round."""
    n = latest_round(questions)
    return [q for q in questions if qint(q, "round") == n] if n else []


def open_questions(questions: list[Question]) -> list[Question]:
    return [q for q in questions if q.get("status") == "open"]


def add_questions(questions: list[Question], stage: str, items: list[tuple[str, str]],
                  clock: Clock) -> None:
    """Append open records for one blocking event: ids continue after the highest ever used,
    the round is one more than the latest."""
    n = max((question_number(q) for q in questions), default=0)
    rnd = latest_round(questions) + 1
    for text, context in items:
        n += 1
        questions.append({"id": f"q{n}", "round": rnd, "stage": stage, "status": "open",
                          "text": text, "context": context, "asked_at": now_iso(clock),
                          "answer": None, "answered_at": None})


def answer_question(q: Question, text: str, clock: Clock) -> None:
    q["status"], q["answer"], q["answered_at"] = "answered", text, now_iso(clock)


def dismiss_open(questions: list[Question], clock: Clock) -> None:
    for q in open_questions(questions):
        q["status"], q["answered_at"] = "dismissed", now_iso(clock)


def render_questions(questions: list[Question]) -> str:
    blocks: list[str] = []
    for q in questions:
        parts = [f"### {qstr(q, 'id')} (round {qint(q, 'round')}, {qstr(q, 'status')})",
                 qstr(q, "text").strip()]
        if qstr(q, "context").strip():
            parts.append("Context: " + qstr(q, "context").strip())
        if q.get("status") == "answered":
            parts.append("Answer: " + qstr(q, "answer").strip())
        blocks.append("\n\n".join(parts))
    return "\n\n".join(blocks)


def round_pairs(questions: list[Question]) -> str:
    """The latest round as question and answer pairs, for the resume prompt (spec: prompts, Which prompt is sent)."""
    out: list[str] = []
    for q in round_questions(questions):
        status = qstr(q, "status")
        out.append(f"{qstr(q, 'id')} ({status}): {qstr(q, 'text').strip()}")
        if status == "answered":
            out.append(f"Answer: {qstr(q, 'answer').strip()}")
        elif status == "dismissed":
            out.append("The human dismissed this question without answering.")
        out.append("")
    return "\n".join(out).strip()


@dataclass
class Sidecar:
    state: str | None = None  # last known folder, for observed hand moves (spec: states)
    session_id: str | None = None
    last_stage: str | None = None  # "plan" | "work", set at dispatch (spec: states, Sidecar state)
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
    questions: list[dict[str, object]] = field(default_factory=lambda: [])  # spec: states, Sidecar state


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
