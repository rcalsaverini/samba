"""The `key=value` log line format (spec: observability)."""

from __future__ import annotations


def kv(event: str, **fields: object) -> str:
    parts = [f"event={event}"]
    for k, v in fields.items():
        if v is None:
            continue
        s = str(v)
        if any(c.isspace() for c in s) or "=" in s or '"' in s:
            s = '"' + s.replace('"', "'") + '"'
        parts.append(f"{k}={s}")
    return " ".join(parts)
