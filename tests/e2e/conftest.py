"""The `box` fixture of the end-to-end suite (the sandbox lives in `e2e_box.py`)."""

from __future__ import annotations

from pathlib import Path

import pytest
from e2e_box import Box


@pytest.fixture
def box(tmp_path: Path) -> Box:
    return Box(tmp_path)
