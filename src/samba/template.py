"""Strict `{{ name }}` template rendering (spec: prompts, Template rendering)."""

from __future__ import annotations

import re

_VAR = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\}\}")


class TemplateError(Exception):
    pass


def render(template: str, variables: dict[str, str]) -> str:
    missing = sorted({m.group(1) for m in _VAR.finditer(template) if m.group(1) not in variables})
    if missing:
        raise TemplateError(f"unknown template variable(s): {', '.join(missing)}")
    return _VAR.sub(lambda m: variables[m.group(1)], template)
