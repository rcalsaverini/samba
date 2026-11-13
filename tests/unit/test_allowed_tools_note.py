"""What the protocol prompt says about the agent's tools, from a `ToolAccess` (spec: prompts)."""

from __future__ import annotations

from samba.domain.prompts import allowed_tools_note
from samba.domain.settings import ToolAccess


def test_unrestricted_access_says_all_tools() -> None:
    access = ToolAccess(allowed=("Edit",), unrestricted=True)
    assert allowed_tools_note(access) == "all tools (permissions are bypassed)"


def test_no_allowed_rules_say_read_only() -> None:
    assert allowed_tools_note(ToolAccess(allowed=(), unrestricted=False)) == "read-only tools only"


def test_allowed_rules_are_listed_with_the_read_only_note() -> None:
    access = ToolAccess(allowed=("Edit", "Bash(git add:*)"), unrestricted=False)
    assert allowed_tools_note(access) == "`Edit`, `Bash(git add:*)` (plus read-only tools)"
