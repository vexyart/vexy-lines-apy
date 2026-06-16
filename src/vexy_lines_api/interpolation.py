# this_file: vexy-lines-apy/src/vexy_lines_api/interpolation.py
"""Explicit interpolation helpers for pairs of compatible ``.lines`` files."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from vexy_lines.types import FILL_TAGS, NUMERIC_PARAMS
from vexy_lines_api.client import MCPClient
from vexy_lines_api.export.io import save_svg_as_image
from vexy_lines_api.style import _lerp, extract_style, styles_compatible
from vexy_lines_api.video import _create_video_writer

VideoAssembler = Callable[[list[Path], Path, float], None]
ClientFactory = Callable[[], AbstractContextManager[MCPClient]]
ScreenshotFunc = Callable[[Path], Path]
ZoomFunc = Callable[[int], None]

_NON_INTERPOLATED_ATTRS: frozenset[str] = frozenset(
    {
        "__uid",
        "caption",
        "expanded",
        "font_name",
        "href_id",
        "locked",
        "object_id",
        "selected",
        "text",
        "tmplUID",
        "type",
        "version",
        "visible",
    }
)
_NON_INTERPOLATED_PREFIXES: tuple[str, ...] = ("enbl_", "invert_", "is_")
_NON_INTERPOLATED_SUFFIXES: tuple[str, ...] = ("_mode",)
_INTEGER_ATTRS: frozenset[str] = frozenset({"dpi", "direction", "left", "right"})
_HEX_COLOR_DIGITS = frozenset("0123456789abcdefABCDEF")
_RGB_HEX_LEN = 6
_ARGB_HEX_LEN = 8
_HEX_BYTE_LEN = 2
_CG_NORMAL_WINDOW_LAYER = 0
_VEXY_LINES_APP_NAME = "Vexy Lines"


@dataclass(frozen=True)
class InterpolationVideoResult:
    """Artifacts produced by :func:`render_interpolation_video`."""

    output_path: Path
    frame_paths: list[Path]
    lines_paths: list[Path]
    fps: float


@dataclass(frozen=True)
class ScreenRecordingResult:
    """Artifacts produced by :func:`record_interpolation_screen`."""

    output_path: Path
    frame_paths: list[Path]
    lines_paths: list[Path]
    fps: float
    video_path: Path | None = None


def _clamp_t(t: float) -> float:
    return max(0.0, min(1.0, float(t)))


def _as_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_number(value: float, *, force_int: bool = False) -> str:
    if force_int:
        return str(round(value))
    if value.is_integer():
        return str(int(value))
    return f"{value:.12g}"


def _is_hex_color(value: str) -> bool:
    if not value.startswith("#"):
        return False
    hex_part = value[1:]
    return len(hex_part) in (6, 8) and all(char in _HEX_COLOR_DIGITS for char in hex_part)


def _parse_lines_color(value: str) -> tuple[str, tuple[int, int, int, int]] | None:
    """Parse native ``.lines`` colour as ``(format, (a, r, g, b))``."""
    if not _is_hex_color(value):
        return None
    hex_part = value[1:]
    if len(hex_part) == _RGB_HEX_LEN:
        r, g, b = (
            int(hex_part[index : index + _HEX_BYTE_LEN], 16)
            for index in range(0, _RGB_HEX_LEN, _HEX_BYTE_LEN)
        )
        return "rgb", (255, r, g, b)
    a, r, g, b = (
        int(hex_part[index : index + _HEX_BYTE_LEN], 16)
        for index in range(0, _ARGB_HEX_LEN, _HEX_BYTE_LEN)
    )
    return "argb", (a, r, g, b)


def _format_lines_color(color_format: str, channels: tuple[int, int, int, int]) -> str:
    a, r, g, b = channels
    if color_format == "rgb":
        return f"#{r:02x}{g:02x}{b:02x}"
    return f"#{a:02x}{r:02x}{g:02x}{b:02x}"


def _interpolate_lines_color(start: str, end: str, t: float) -> str:
    if t <= 0:
        return start
    if t >= 1:
        return end

    parsed_start = _parse_lines_color(start)
    parsed_end = _parse_lines_color(end)
    if parsed_start is None or parsed_end is None:
        return start

    start_format, start_channels = parsed_start
    end_format, end_channels = parsed_end
    output_format = "argb" if "argb" in (start_format, end_format) else "rgb"
    channels = tuple(
        max(0, min(255, round(_lerp(float(start_channel), float(end_channel), t))))
        for start_channel, end_channel in zip(start_channels, end_channels, strict=True)
    )
    return _format_lines_color(output_format, channels)


def _is_interpolatable_numeric_attr(attr: str, start_value: str, end_value: str) -> bool:
    if attr in _NON_INTERPOLATED_ATTRS:
        return False
    if attr.startswith(_NON_INTERPOLATED_PREFIXES) or attr.endswith(_NON_INTERPOLATED_SUFFIXES):
        return False
    try:
        float(start_value)
        float(end_value)
    except (TypeError, ValueError):
        return False
    return not (attr not in NUMERIC_PARAMS and {start_value, end_value} <= {"0", "1"})


def _interpolate_xml_attr(output_elem: ET.Element, attr: str, start_value: str, end_value: str, t: float) -> None:
    if attr == "color_name":
        output_elem.set(attr, _interpolate_lines_color(start_value, end_value, t))
        return
    if not _is_interpolatable_numeric_attr(attr, start_value, end_value):
        return

    interpolated = _lerp(float(start_value), float(end_value), t)
    output_elem.set(attr, _format_number(interpolated, force_int=attr in _INTEGER_ATTRS))


def _interpolate_matching_element_attrs(
    output_elem: ET.Element,
    start_elem: ET.Element,
    end_elem: ET.Element,
    t: float,
) -> None:
    if output_elem.tag != start_elem.tag or start_elem.tag != end_elem.tag:
        msg = "interpolate_lines requires two .lines files with the same structure"
        raise ValueError(msg)

    for attr, start_value in start_elem.attrib.items():
        if attr in end_elem.attrib:
            _interpolate_xml_attr(output_elem, attr, start_value, end_elem.attrib[attr], t)


def _non_reference_elements(root: ET.Element, tags: frozenset[str]) -> list[ET.Element]:
    return [elem for elem in root.iter() if elem.tag in tags and "href_id" not in elem.attrib]


def _interpolate_element_sequences(
    output_elements: list[ET.Element],
    start_elements: list[ET.Element],
    end_elements: list[ET.Element],
    t: float,
    *,
    required: bool,
) -> None:
    if len(output_elements) != len(start_elements) or len(start_elements) != len(end_elements):
        if not required:
            return
        msg = "interpolate_lines requires two .lines files with the same structure"
        raise ValueError(msg)

    for output_elem, start_elem, end_elem in zip(output_elements, start_elements, end_elements, strict=True):
        _interpolate_matching_element_attrs(output_elem, start_elem, end_elem, t)


def _interpolate_known_matching_elements(
    output_root: ET.Element,
    start_root: ET.Element,
    end_root: ET.Element,
    t: float,
) -> None:
    _interpolate_matching_element_attrs(output_root, start_root, end_root, t)

    output_doc = output_root.find("Document")
    start_doc = start_root.find("Document")
    end_doc = end_root.find("Document")
    if output_doc is not None and start_doc is not None and end_doc is not None:
        _interpolate_matching_element_attrs(output_doc, start_doc, end_doc, t)

    required_tag_sets = (
        frozenset({"LrSection", "FreeMesh"}),
        FILL_TAGS,
        frozenset({"filter"}),
    )
    for tag_set in required_tag_sets:
        _interpolate_element_sequences(
            _non_reference_elements(output_root, tag_set),
            _non_reference_elements(start_root, tag_set),
            _non_reference_elements(end_root, tag_set),
            t,
            required=True,
        )

    optional_tag_sets = (
        frozenset({"MaskData"}),
        frozenset({"row_grid_edge"}),
        frozenset({"col_grid_edge"}),
    )
    for tag_set in optional_tag_sets:
        _interpolate_element_sequences(
            _non_reference_elements(output_root, tag_set),
            _non_reference_elements(start_root, tag_set),
            _non_reference_elements(end_root, tag_set),
            t,
            required=False,
        )


def _canonical_fill_elements(root: ET.Element) -> list[ET.Element]:
    return [elem for elem in root.iter() if elem.tag in FILL_TAGS and "href_id" not in elem.attrib]


def interpolate_lines(
    start_path: str | Path,
    end_path: str | Path,
    output_path: str | Path,
    *,
    t: float,
) -> Path:
    """Write one interpolated ``.lines`` file between two compatible inputs.

    The output keeps the XML structure and embedded images from *start_path*
    and rewrites interpolatable fill/document attributes to the value at *t*.
    Both inputs must have the same parsed style structure.
    """
    start = Path(start_path)
    end = Path(end_path)
    output = Path(output_path)
    mix = _clamp_t(t)

    start_style = extract_style(start)
    end_style = extract_style(end)
    if not styles_compatible(start_style, end_style):
        msg = "interpolate_lines requires two .lines files with the same structure"
        raise ValueError(msg)

    start_tree = ET.parse(start)  # noqa: S314
    end_tree = ET.parse(end)  # noqa: S314
    output_tree = ET.parse(start)  # noqa: S314
    start_root = start_tree.getroot()
    end_root = end_tree.getroot()
    output_root = output_tree.getroot()

    start_fills = _canonical_fill_elements(start_root)
    end_fills = _canonical_fill_elements(end_root)
    output_fills = _canonical_fill_elements(output_root)
    if len(start_fills) != len(end_fills) or len(start_fills) != len(output_fills):
        msg = "interpolate_lines requires two .lines files with the same structure"
        raise ValueError(msg)

    _interpolate_known_matching_elements(output_root, start_root, end_root, mix)

    output.parent.mkdir(parents=True, exist_ok=True)
    output_tree.write(output, encoding="unicode", xml_declaration=False)
    return output


def _frame_t(index: int, frames: int) -> float:
    if frames <= 1:
        return 0.0
    return index / (frames - 1)


def _validate_timeline(frames: int, fps: float) -> None:
    if frames < 1:
        msg = "frames must be at least 1"
        raise ValueError(msg)
    if fps <= 0:
        msg = "fps must be greater than 0"
        raise ValueError(msg)


def _assemble_pngs_to_mp4(frame_paths: list[Path], output_path: Path, fps: float) -> None:
    if not frame_paths:
        msg = "no frames to assemble"
        raise ValueError(msg)

    import cv2  # type: ignore[import-untyped]  # noqa: PLC0415
    import numpy as np  # type: ignore[import-untyped]  # noqa: PLC0415
    from PIL import Image as PILImage  # noqa: PLC0415

    with PILImage.open(frame_paths[0]) as first:
        width, height = first.size

    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = _create_video_writer(str(output_path), fps, width, height)
    try:
        for frame_path in frame_paths:
            with PILImage.open(frame_path) as image:
                rgb = image.convert("RGB")
                if rgb.size != (width, height):
                    rgb = rgb.resize((width, height), PILImage.Resampling.LANCZOS)
                writer.write(cv2.cvtColor(np.array(rgb), cv2.COLOR_RGB2BGR))
    finally:
        writer.release()


def _render_or_raise(client: MCPClient, timeout: float, lines_path: Path) -> None:
    if not client.render(timeout=timeout):
        msg = f"Timed out rendering {lines_path}"
        raise TimeoutError(msg)


def _save_rendered_png_from_svg(client: MCPClient, frame_path: Path) -> Path:
    save_svg_as_image(client.svg(), frame_path, "PNG")
    return frame_path


def render_interpolation_video(
    start_path: str | Path,
    end_path: str | Path,
    output_path: str | Path,
    *,
    frames: int = 60,
    fps: float = 24.0,
    work_dir: str | Path | None = None,
    keep_work: bool = False,
    render_timeout: float = 300.0,
    client_factory: ClientFactory | None = None,
    assemble_video: VideoAssembler = _assemble_pngs_to_mp4,
) -> InterpolationVideoResult:
    """Render a full interpolation between two ``.lines`` files to MP4."""
    _validate_timeline(frames, fps)
    start = Path(start_path)
    end = Path(end_path)
    output = Path(output_path)
    auto_work = work_dir is None
    workspace = Path(tempfile.mkdtemp(prefix="vexy_lines_interp_")) if auto_work else Path(work_dir)
    workspace.mkdir(parents=True, exist_ok=True)
    client_factory = client_factory or MCPClient

    lines_paths: list[Path] = []
    frame_paths: list[Path] = []
    try:
        for index in range(frames):
            lines_path = workspace / f"interpolation-{index + 1:04d}.lines"
            interpolate_lines(start, end, lines_path, t=_frame_t(index, frames))
            lines_paths.append(lines_path)

        with client_factory() as client:
            for index, lines_path in enumerate(lines_paths, start=1):
                frame_path = workspace / f"interpolation-{index:04d}.png"
                client.open_document(str(lines_path))
                _render_or_raise(client, render_timeout, lines_path)
                frame_paths.append(_save_rendered_png_from_svg(client, frame_path))

        assemble_video(frame_paths, output, fps)
        returned_frame_paths = [] if auto_work and not keep_work else frame_paths
        returned_lines_paths = [] if auto_work and not keep_work else lines_paths
        return InterpolationVideoResult(
            output_path=output,
            frame_paths=returned_frame_paths,
            lines_paths=returned_lines_paths,
            fps=fps,
        )
    finally:
        if auto_work and not keep_work:
            shutil.rmtree(workspace, ignore_errors=True)


def _run_osascript(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["/usr/bin/osascript", "-e", script],
        capture_output=True,
        check=False,
        text=True,
    )


def _activate_vexy_lines() -> None:
    _run_osascript(f'tell application "{_VEXY_LINES_APP_NAME}" to activate')
    time.sleep(0.2)


def _quartz_vexy_lines_window_id() -> str | None:
    try:
        import Quartz  # type: ignore[import-not-found]  # noqa: PLC0415
    except ImportError:
        return None

    windows = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID)
    if not windows:
        return None

    for window in windows:
        if window.get("kCGWindowOwnerName") != _VEXY_LINES_APP_NAME:
            continue
        if window.get("kCGWindowLayer", _CG_NORMAL_WINDOW_LAYER) != _CG_NORMAL_WINDOW_LAYER:
            continue
        window_id = window.get("kCGWindowNumber")
        if window_id is not None:
            return str(window_id)
    return None


def _vexy_lines_window_id() -> str:
    quartz_window_id = _quartz_vexy_lines_window_id()
    if quartz_window_id is not None:
        return quartz_window_id

    result = _run_osascript(
        f'tell application "System Events" to get the id of window 1 of process "{_VEXY_LINES_APP_NAME}"'
    )
    window_id = result.stdout.strip()
    if result.returncode != 0 or not window_id:
        msg = "Could not get the Vexy Lines window id for screenshot capture"
        raise RuntimeError(msg)
    return window_id


def _default_zoom(steps: int) -> None:
    if steps == 0:
        return
    if sys.platform != "darwin":
        logger.warning("GUI zoom automation is only implemented on macOS")
        return
    _activate_vexy_lines()
    key = "=" if steps > 0 else "-"
    for _ in range(abs(steps)):
        _run_osascript(f'tell application "System Events" to keystroke "{key}" using command down')


def _default_screenshot(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "darwin":
        _activate_vexy_lines()
        window_id = _vexy_lines_window_id()
        subprocess.run(["/usr/sbin/screencapture", "-x", "-o", "-l", window_id, str(path)], check=True)  # noqa: S603
        return path
    msg = "screen recording requires macOS screencapture or a custom screenshot_func"
    raise RuntimeError(msg)


def record_interpolation_screen(
    start_path: str | Path,
    end_path: str | Path,
    output_path: str | Path,
    *,
    frames: int = 60,
    fps: float = 24.0,
    zoom_steps: int = 0,
    video_path: str | Path | None = None,
    work_dir: str | Path | None = None,
    keep_work: bool = False,
    render_timeout: float = 300.0,
    client_factory: ClientFactory | None = None,
    screenshot_func: ScreenshotFunc = _default_screenshot,
    zoom_func: ZoomFunc = _default_zoom,
    assemble_video: VideoAssembler = _assemble_pngs_to_mp4,
) -> ScreenRecordingResult:
    """Capture the Vexy Lines app window through a generated interpolation timeline."""
    _validate_timeline(frames, fps)
    start = Path(start_path)
    end = Path(end_path)
    output = Path(output_path)
    output.mkdir(parents=True, exist_ok=True)
    auto_work = work_dir is None
    workspace = Path(tempfile.mkdtemp(prefix="vexy_lines_screen_")) if auto_work else Path(work_dir)
    workspace.mkdir(parents=True, exist_ok=True)
    client_factory = client_factory or MCPClient

    lines_paths: list[Path] = [start]
    frame_paths: list[Path] = []
    final_video = Path(video_path) if video_path is not None else None
    try:
        for index in range(1, frames):
            lines_path = workspace / f"screen-interpolation-{index + 1:04d}.lines"
            interpolate_lines(start, end, lines_path, t=_frame_t(index, frames))
            lines_paths.append(lines_path)

        with client_factory() as client:
            client.open_document(str(start))
            _render_or_raise(client, render_timeout, start)
            zoom_func(zoom_steps)
            first_frame = output / "screen-001.png"
            frame_paths.append(screenshot_func(first_frame))

            for index, lines_path in enumerate(lines_paths[1:], start=2):
                client.open_document(str(lines_path))
                _render_or_raise(client, render_timeout, lines_path)
                frame_path = output / f"screen-{index:03d}.png"
                frame_paths.append(screenshot_func(frame_path))

        if final_video is not None:
            assemble_video(frame_paths, final_video, fps)

        returned_lines_paths = [start] if auto_work and not keep_work else lines_paths
        return ScreenRecordingResult(
            output_path=output,
            frame_paths=frame_paths,
            lines_paths=returned_lines_paths,
            fps=fps,
            video_path=final_video,
        )
    finally:
        if auto_work and not keep_work:
            shutil.rmtree(workspace, ignore_errors=True)
