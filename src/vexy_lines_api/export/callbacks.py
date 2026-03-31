# this_file: vexy-lines-apy/src/vexy_lines_api/export/callbacks.py

from __future__ import annotations

import contextlib
from collections.abc import Callable

ProgressCallback = Callable[[int, int, str], None]
CompleteCallback = Callable[[str], None]
ErrorCallback = Callable[[str], None]
PreviewCallback = Callable[[bytes], None]


def report_progress(callback: ProgressCallback | None, current: int, total: int, message: str) -> None:
    if callback is not None:
        with contextlib.suppress(Exception):
            callback(current, total, message)


def report_complete(callback: CompleteCallback | None, message: str) -> None:
    if callback is not None:
        with contextlib.suppress(Exception):
            callback(message)


def report_error(callback: ErrorCallback | None, message: str) -> None:
    if callback is not None:
        with contextlib.suppress(Exception):
            callback(message)


def report_preview(callback: PreviewCallback | None, data: bytes) -> None:
    if callback is not None:
        with contextlib.suppress(Exception):
            callback(data)
