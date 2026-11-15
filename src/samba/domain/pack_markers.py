"""The two markers of a method pack, filled by a pure function (spec: packs, Markers).

`@@DATE@@` is replaced anywhere by the date. A line that holds only `@@VALIDATE@@` becomes the
`validate:` block of `WORKFLOW.md`, or its commented form. Nothing else is touched, so the
`{{ ... }}` of Samba's own prompt rendering passes through.
"""

from __future__ import annotations

import json

DATE_MARKER = "@@DATE@@"
VALIDATE_MARKER = "@@VALIDATE@@"

VALIDATE_SET = ("validate:", "  command: {command}")
VALIDATE_UNSET = ("# validate:", "#   command: set your validation command here")


def validate_block(command: str | None) -> list[str]:
    """The lines that replace the validate marker. The command is quoted as a JSON string, which
    is valid YAML for any text."""
    if command is None:
        return list(VALIDATE_UNSET)
    return [VALIDATE_SET[0], VALIDATE_SET[1].format(command=json.dumps(command))]


def fill_markers(text: str, date: str, validate: str | None) -> str:
    """`date` is `YYYY-MM-DD`; `validate` is the command, or None for the commented form."""
    out: list[str] = []
    for line in text.split("\n"):
        if line == VALIDATE_MARKER:
            out.extend(validate_block(validate))
        else:
            out.append(line.replace(DATE_MARKER, date))
    return "\n".join(out)
