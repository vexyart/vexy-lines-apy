# this_file: vexy-lines-apy/tests/conftest.py
"""Test path setup for local sibling packages in the monorepo workspace."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_PARSER_SRC = _ROOT / "vexy-lines-py" / "src"
_LOCAL_API_SRC = Path(__file__).resolve().parent.parent / "src"

for _path in (_LOCAL_PARSER_SRC, _LOCAL_API_SRC):
    if _path.is_dir():
        _path_str = str(_path)
        if _path_str not in sys.path:
            sys.path.insert(0, _path_str)
