"""Pytest configuration: ensure src/ and tests/ are importable."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_TESTS = Path(__file__).resolve().parent
_SRC = _ROOT / "src"

for path in (_SRC, _TESTS):
    p = str(path)
    if p not in sys.path:
        sys.path.insert(0, p)
