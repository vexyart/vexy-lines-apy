# this_file: vexy-lines-apy/src/vexy_lines_api/export/models.py
"""Typed request models for the shared export pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ExportMode = Literal["lines", "images", "video"]
ExportFormat = Literal["LINES", "SVG", "PNG", "JPG", "MP4"]


@dataclass(frozen=True)
class ExportRequest:
    """Canonical export request used by GUI and CLI frontends."""

    mode: ExportMode
    input_paths: list[str]
    style_path: str | None
    end_style_path: str | None
    output_path: str
    format: ExportFormat
    size: str
    audio: bool = True
    frame_range: tuple[int, int] | None = None
    relative_style: bool = False
    style_mode: str = "fast"
