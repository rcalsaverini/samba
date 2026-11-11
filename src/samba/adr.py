"""ADR files under `docs/adr/` (spec: cli, ADR commands; format: docs/adr/0001).

Plain files, no lock and no config. Only the front matter of ADR 0001 is parsed (`status`, `date`,
`supersedes`); status edits rewrite just the `status:` and `supersedes:` lines.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import yaml

from samba.ports import AdrError  # a refusal; `code` is the exit code (1 or 2)

ADR_DIR = Path("docs") / "adr"
FILE_RE = re.compile(r"^(\d+)-.*\.md$")
SENTENCE_END = re.compile(r"\.(?:\s+(?=[A-Z`])|$)")


@dataclass(frozen=True)
class Adr:
    number: int
    path: Path
    status: str
    supersedes: list[int]
    title: str
    summary: str
    text: str


def parse_number(text: str) -> int:
    """`3`, `03` and `0003` are the same ADR; anything but digits is a usage error."""
    if not re.fullmatch(r"\d+", text):
        raise AdrError(f"not an ADR number: {text!r} (use digits, e.g. 3 or 0003)", 2)
    return int(text)


def _split_front_matter(text: str) -> tuple[list[str], list[str]]:
    """The front matter lines (without the `---` fences) and the body lines."""
    lines = text.split("\n")
    if lines[0].strip() != "---":
        raise AdrError("no front matter", 1)
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[1:i], lines[i + 1:]
    raise AdrError("front matter is not closed", 1)


def summary_of(body: list[str]) -> str:
    """First sentence of the Decision section (a sentence ends at `.` followed by a capital
    letter, a backtick or the end of the first paragraph or bullet)."""
    block: list[str] = []
    in_decision = False
    for line in body:
        if line.startswith("## "):
            if in_decision:
                break
            in_decision = line.strip() == "## Decision"
            continue
        if not in_decision:
            continue
        stripped = line.strip()
        if not stripped:
            if block:
                break
            continue
        if block and re.match(r"(?:[-*]|\d+\.)\s", stripped):
            break
        block.append(re.sub(r"^[-*]\s+", "", stripped) if not block else stripped)
    text = " ".join(block)
    m = SENTENCE_END.search(text)
    return text[:m.end()].strip() if m else text


def parse(path: Path) -> Adr:
    m = FILE_RE.match(path.name)
    if not m:
        raise AdrError(f"{path.name} is not named NNNN-title.md", 1)
    text = path.read_text()
    try:
        front_lines, body = _split_front_matter(text)
        data = yaml.safe_load("\n".join(front_lines))
    except (AdrError, yaml.YAMLError) as e:
        raise AdrError(f"{path}: bad front matter: {e}", 1) from e
    front = cast(dict[str, object], data) if isinstance(data, dict) else {}
    status = front.get("status")
    if not isinstance(status, str):
        raise AdrError(f"{path}: front matter has no `status`", 1)
    sup = cast(object, front.get("supersedes") or [])
    supersedes = [x for x in cast(list[object], sup) if isinstance(x, int)] \
        if isinstance(sup, list) else []
    title = ""
    for line in body:
        if line.startswith("# "):
            title = re.sub(r"^\d+:\s*", "", line[2:].strip())
            break
    return Adr(int(m.group(1)), path, status.strip(), supersedes, title, summary_of(body), text)


def load_all(repo: Path) -> list[Adr]:
    folder = repo / ADR_DIR
    if not folder.is_dir():
        return []
    files = [p for p in folder.iterdir() if FILE_RE.match(p.name)]
    return sorted((parse(p) for p in files), key=lambda a: (a.number, a.path.name))


def find(repo: Path, number: int) -> Adr:
    for adr in load_all(repo):
        if adr.number == number:
            return adr
    raise AdrError(f"unknown ADR {number:04d}", 2)


def _replace_line(text: str, key: str, value: str) -> str:
    """Set `key: value` inside the front matter, adding the line if it is missing."""
    lines = text.split("\n")
    end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    for i in range(1, end):
        if re.match(rf"{key}\s*:", lines[i]):
            lines[i] = f"{key}: {value}"
            return "\n".join(lines)
    if key == "status":
        raise AdrError("front matter has no `status:` line", 1)
    lines.insert(end, f"{key}: {value}")
    return "\n".join(lines)


def _status_text(adr: Adr, status: str) -> str:
    return _replace_line(adr.text, "status", status)


def set_status(repo: Path, number: int, verb: str, allowed_from: str, status: str) -> list[Path]:
    """`accept` and `reject`: only from `proposed`. Returns the files written."""
    adr = find(repo, number)
    if adr.status != allowed_from:
        raise AdrError(f"ADR {number:04d} is {adr.status}; {verb} not allowed "
                       f"(only {allowed_from} can be {status})", 1)
    adr.path.write_text(_status_text(adr, status))
    return [adr.path]


def supersede(repo: Path, old_number: int, new_number: int) -> list[Path]:
    """Mark `old` superseded and list it in the `supersedes` of `new`. Both files are checked
    before either is written."""
    if old_number == new_number:
        raise AdrError("an ADR cannot supersede itself", 2)
    old = find(repo, old_number)
    new = find(repo, new_number)
    if old.status != "accepted":
        raise AdrError(f"ADR {old_number:04d} is {old.status}; supersede not allowed "
                       "(only accepted can be superseded)", 1)
    if new.status not in ("proposed", "accepted"):
        raise AdrError(f"ADR {new_number:04d} is {new.status}; it cannot supersede "
                       "(only proposed or accepted can)", 1)
    old_text = _status_text(old, "superseded")
    new_text = new.text
    if old_number not in new.supersedes:
        numbers = ", ".join(str(n) for n in [*new.supersedes, old_number])
        new_text = _replace_line(new.text, "supersedes", f"[{numbers}]")
    old.path.write_text(old_text)
    try:
        new.path.write_text(new_text)
    except OSError as e:
        raise AdrError(f"{old.path} was changed but {new.path} could not be written: {e}", 1) from e
    return [old.path, new.path]
