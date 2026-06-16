# this_file: vexy-lines-apy/tests/test_interpolation.py
"""Tests for explicit .lines interpolation APIs."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from subprocess import CompletedProcess
from typing import Self

import pytest
from PIL import Image as PILImage

import vexy_lines_api.interpolation as interpolation_module
from vexy_lines_api.interpolation import (
    InterpolationVideoResult,
    ScreenRecordingResult,
    _assemble_pngs_to_mp4,
    _default_screenshot,
    _default_zoom,
    interpolate_lines,
    record_interpolation_screen,
    render_interpolation_video,
)

START_XML = """\
<Project caption="Start" version="2.1" dpi="300">
  <Document width_mm="100" height_mm="100" dpi="300"
            thicknessMin="0.1" thicknessMax="1.0"
            intervalMin="1.0" intervalMax="10.0"/>
  <Objects>
    <FreeMesh caption="Layer" object_id="10">
      <Objects>
        <LinearStrokesTmpl caption="Lines" object_id="11" color_name="#ff0000"
            interval="10" angle="0" smoothness="0">
          <image_filters>
            <filter type="0" value="0"/>
            <filter type="4" left="10" right="200"/>
          </image_filters>
        </LinearStrokesTmpl>
      </Objects>
    </FreeMesh>
  </Objects>
</Project>
"""

END_XML = """\
<Project caption="End" version="2.1" dpi="300">
  <Document width_mm="200" height_mm="100" dpi="300"
            thicknessMin="0.5" thicknessMax="3.0"
            intervalMin="2.0" intervalMax="20.0"/>
  <Objects>
    <FreeMesh caption="Layer" object_id="10">
      <Objects>
        <LinearStrokesTmpl caption="Lines" object_id="11" color_name="#0000ff"
            interval="30" angle="90" smoothness="1">
          <image_filters>
            <filter type="0" value="100"/>
            <filter type="4" left="20" right="240"/>
          </image_filters>
        </LinearStrokesTmpl>
      </Objects>
    </FreeMesh>
  </Objects>
</Project>
"""

INCOMPATIBLE_XML = """\
<Project caption="Other" version="2.1" dpi="300">
  <Objects>
    <FreeMesh caption="Layer" object_id="10">
      <Objects>
        <CircleStrokesTmpl caption="Circles" object_id="11" color_name="#0000ff"/>
      </Objects>
    </FreeMesh>
  </Objects>
</Project>
"""


class FakeClient:
    def __init__(self, *, render_success: bool = True) -> None:
        self.opened: list[str] = []
        self.render_timeouts: list[float] = []
        self.exported_pngs: list[str] = []
        self.render_success = render_success
        self.svg_calls = 0

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def open_document(self, path: str) -> str:
        self.opened.append(path)
        return "opened"

    def render(self, timeout: float = 120.0) -> bool:
        self.render_timeouts.append(timeout)
        return self.render_success

    def export_png(self, path: str, *, dpi: int | None = None) -> Path:
        _ = dpi
        output = Path(path)
        output.write_bytes(b"PNG")
        self.exported_pngs.append(str(output))
        return output

    def svg(self) -> str:
        self.svg_calls += 1
        return """\
<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4" viewBox="0 0 4 4">
  <rect width="4" height="4" fill="#ffffff"/>
</svg>
"""


def _write_pair(tmp_path: Path) -> tuple[Path, Path]:
    start = tmp_path / "start.lines"
    end = tmp_path / "end.lines"
    start.write_text(START_XML, encoding="utf-8")
    end.write_text(END_XML, encoding="utf-8")
    return start, end


def test_interpolate_lines_writes_midpoint_lines_file(tmp_path: Path) -> None:
    start, end = _write_pair(tmp_path)
    output = tmp_path / "mid.lines"

    result = interpolate_lines(start, end, output, t=0.25)

    assert result == output
    fill = ET.parse(output).getroot().find(".//LinearStrokesTmpl")  # noqa: S314
    assert fill is not None
    assert fill.get("interval") == "15"
    assert fill.get("angle") == "22.5"
    assert fill.get("smoothness") == "0.25"
    assert fill.get("color_name") == "#bf0040"
    filters = fill.find("image_filters")
    assert filters is not None
    assert filters[0].get("value") == "25"
    assert filters[1].get("left") == "12"
    assert filters[1].get("right") == "210"


def test_interpolate_lines_interpolates_arbitrary_numeric_xml_attributes(tmp_path: Path) -> None:
    start_xml = START_XML.replace(
        'smoothness="0"',
        'smoothness="0" cell_size="10" cell_height="20" cx="100" cy="50" period="30"',
    )
    end_xml = END_XML.replace(
        'smoothness="1"',
        'smoothness="1" cell_size="20" cell_height="40" cx="200" cy="150" period="90"',
    )
    start = tmp_path / "start.lines"
    end = tmp_path / "end.lines"
    output = tmp_path / "mid.lines"
    start.write_text(start_xml, encoding="utf-8")
    end.write_text(end_xml, encoding="utf-8")

    interpolate_lines(start, end, output, t=0.25)

    fill = ET.parse(output).getroot().find(".//LinearStrokesTmpl")  # noqa: S314
    assert fill is not None
    assert fill.get("cell_size") == "12.5"
    assert fill.get("cell_height") == "25"
    assert fill.get("cx") == "125"
    assert fill.get("cy") == "75"
    assert fill.get("period") == "45"
    assert fill.get("object_id") == "11"


def test_interpolate_lines_preserves_native_argb_color_format(tmp_path: Path) -> None:
    start_xml = START_XML.replace('color_name="#ff0000"', 'color_name="#80ff0000"')
    end_xml = END_XML.replace('color_name="#0000ff"', 'color_name="#400000ff"')
    start = tmp_path / "start.lines"
    end = tmp_path / "end.lines"
    midpoint = tmp_path / "mid.lines"
    final = tmp_path / "final.lines"
    start.write_text(start_xml, encoding="utf-8")
    end.write_text(end_xml, encoding="utf-8")

    interpolate_lines(start, end, midpoint, t=0.5)
    interpolate_lines(start, end, final, t=1.0)

    midpoint_fill = ET.parse(midpoint).getroot().find(".//LinearStrokesTmpl")  # noqa: S314
    final_fill = ET.parse(final).getroot().find(".//LinearStrokesTmpl")  # noqa: S314
    assert midpoint_fill is not None
    assert final_fill is not None
    assert midpoint_fill.get("color_name") == "#60800080"
    assert final_fill.get("color_name") == "#400000ff"


def test_interpolate_lines_rejects_different_structures(tmp_path: Path) -> None:
    start, _end = _write_pair(tmp_path)
    incompatible = tmp_path / "incompatible.lines"
    incompatible.write_text(INCOMPATIBLE_XML, encoding="utf-8")

    with pytest.raises(ValueError, match="same structure"):
        interpolate_lines(start, incompatible, tmp_path / "out.lines", t=0.5)


def test_interpolate_lines_allows_unmatched_optional_layer_children(tmp_path: Path) -> None:
    start_xml = START_XML.replace(
        "</FreeMesh>",
        '<MaskData mask_type="1" tolerance="0"/></FreeMesh>',
    )
    start = tmp_path / "start.lines"
    end = tmp_path / "end.lines"
    output = tmp_path / "mid.lines"
    start.write_text(start_xml, encoding="utf-8")
    end.write_text(END_XML, encoding="utf-8")

    interpolate_lines(start, end, output, t=0.5)

    fill = ET.parse(output).getroot().find(".//LinearStrokesTmpl")  # noqa: S314
    assert fill is not None
    assert fill.get("interval") == "20"


def test_render_interpolation_video_uses_requested_frame_count_and_fps(tmp_path: Path) -> None:
    start, end = _write_pair(tmp_path)
    fake = FakeClient()
    assembled: dict[str, object] = {}

    def assemble(frame_paths: list[Path], output_path: Path, fps: float) -> None:
        assembled["frame_paths"] = frame_paths
        assembled["output_path"] = output_path
        assembled["fps"] = fps
        output_path.write_bytes(b"MP4")

    result = render_interpolation_video(
        start,
        end,
        tmp_path / "interp.mp4",
        frames=4,
        fps=12.5,
        work_dir=tmp_path / "work",
        client_factory=lambda: fake,
        assemble_video=assemble,
    )

    assert isinstance(result, InterpolationVideoResult)
    assert result.output_path == tmp_path / "interp.mp4"
    assert len(result.lines_paths) == 4
    assert len(result.frame_paths) == 4
    assert assembled["fps"] == 12.5
    assert assembled["frame_paths"] == result.frame_paths
    assert fake.opened == [str(path) for path in result.lines_paths]
    assert fake.svg_calls == 4
    assert fake.exported_pngs == []


def test_render_interpolation_video_raises_when_render_times_out(tmp_path: Path) -> None:
    start, end = _write_pair(tmp_path)
    fake = FakeClient(render_success=False)

    with pytest.raises(TimeoutError, match="Timed out rendering"):
        render_interpolation_video(
            start,
            end,
            tmp_path / "interp.mp4",
            frames=1,
            fps=12.5,
            work_dir=tmp_path / "work",
            client_factory=lambda: fake,
        )

    assert fake.svg_calls == 0


def test_render_interpolation_video_with_auto_work_does_not_return_deleted_paths(tmp_path: Path) -> None:
    start, end = _write_pair(tmp_path)
    fake = FakeClient()

    def assemble(frame_paths: list[Path], output_path: Path, fps: float) -> None:
        assert frame_paths
        assert fps == 12.5
        output_path.write_bytes(b"MP4")

    result = render_interpolation_video(
        start,
        end,
        tmp_path / "interp.mp4",
        frames=2,
        fps=12.5,
        client_factory=lambda: fake,
        assemble_video=assemble,
    )

    assert result.frame_paths == []
    assert result.lines_paths == []


def test_assemble_pngs_to_mp4_resizes_mismatched_frames(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    PILImage.new("RGB", (4, 4), "white").save(first)
    PILImage.new("RGB", (8, 8), "black").save(second)
    frame_shapes: list[tuple[int, int, int]] = []

    class FakeWriter:
        def write(self, frame: object) -> None:
            frame_shapes.append(frame.shape)  # type: ignore[attr-defined]

        def release(self) -> None:
            return None

    def fake_create_video_writer(_path: str, _fps: float, _width: int, _height: int) -> FakeWriter:
        return FakeWriter()

    monkeypatch.setattr(interpolation_module, "_create_video_writer", fake_create_video_writer)

    _assemble_pngs_to_mp4([first, second], tmp_path / "out.mp4", fps=24)

    assert frame_shapes == [(4, 4, 3), (4, 4, 3)]


def test_record_interpolation_screen_loads_start_applies_zoom_and_captures_frames(tmp_path: Path) -> None:
    start, end = _write_pair(tmp_path)
    fake = FakeClient()
    zoom_calls: list[int] = []

    def screenshot(path: Path) -> Path:
        path.write_bytes(b"SCREEN")
        return path

    result = record_interpolation_screen(
        start,
        end,
        tmp_path / "screens",
        frames=3,
        fps=8,
        zoom_steps=2,
        work_dir=tmp_path / "work",
        client_factory=lambda: fake,
        screenshot_func=screenshot,
        zoom_func=zoom_calls.append,
    )

    assert isinstance(result, ScreenRecordingResult)
    assert result.output_path == tmp_path / "screens"
    assert result.video_path is None
    assert len(result.frame_paths) == 3
    assert [path.read_bytes() for path in result.frame_paths] == [b"SCREEN", b"SCREEN", b"SCREEN"]
    assert zoom_calls == [2]
    assert fake.opened[0] == str(start)
    assert fake.opened[1:] == [str(path) for path in result.lines_paths[1:]]


def test_record_interpolation_screen_raises_when_render_times_out(tmp_path: Path) -> None:
    start, end = _write_pair(tmp_path)
    fake = FakeClient(render_success=False)

    with pytest.raises(TimeoutError, match="Timed out rendering"):
        record_interpolation_screen(
            start,
            end,
            tmp_path / "screens",
            frames=1,
            fps=8,
            client_factory=lambda: fake,
            screenshot_func=lambda path: path,
        )


def test_record_interpolation_screen_with_auto_work_keeps_only_existing_lines_path(tmp_path: Path) -> None:
    start, end = _write_pair(tmp_path)
    fake = FakeClient()

    def screenshot(path: Path) -> Path:
        path.write_bytes(b"SCREEN")
        return path

    result = record_interpolation_screen(
        start,
        end,
        tmp_path / "screens",
        frames=2,
        fps=8,
        client_factory=lambda: fake,
        screenshot_func=screenshot,
    )

    assert result.lines_paths == [start]
    assert len(result.frame_paths) == 2
    assert all(path.exists() for path in result.frame_paths)


def test_default_screenshot_captures_vexy_lines_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: object) -> CompletedProcess[str]:
        commands.append(args)
        if args[0] == "/usr/bin/osascript" and "id of window" in args[-1]:
            return CompletedProcess(args, 0, stdout="12345\n")
        if args[0] == "/usr/sbin/screencapture":
            Path(args[-1]).write_bytes(b"SCREEN")
        return CompletedProcess(args, 0, stdout="")

    monkeypatch.setattr(interpolation_module.sys, "platform", "darwin")
    monkeypatch.setattr(interpolation_module.subprocess, "run", fake_run)
    monkeypatch.setattr(interpolation_module, "_quartz_vexy_lines_window_id", lambda: None)

    output = _default_screenshot(tmp_path / "window.png")

    assert output.read_bytes() == b"SCREEN"
    assert ["/usr/sbin/screencapture", "-x", "-o", "-l", "12345", str(output)] in commands


def test_default_zoom_activates_app_before_keystrokes(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: object) -> CompletedProcess[str]:
        commands.append(args)
        return CompletedProcess(args, 0, stdout="")

    monkeypatch.setattr(interpolation_module.sys, "platform", "darwin")
    monkeypatch.setattr(interpolation_module.subprocess, "run", fake_run)

    _default_zoom(1)

    assert 'tell application "Vexy Lines" to activate' in commands[0]
    assert 'tell application "System Events" to keystroke "=" using command down' in commands[1]
