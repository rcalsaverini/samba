"""`Locations`: where things live, as real paths. A helper, not an adapter (ADR 0019)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Locations:
    """Where things live, as real paths: only the adapters that touch the disk receive it."""

    repo: Path
    samba_dir: Path
    workspaces_root: Path
