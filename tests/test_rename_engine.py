# this_file: vexy-lines-apy/tests/test_rename_engine.py
"""Tests for vexy_lines_api.rename.engine (file-based per-fill rendering)."""

from __future__ import annotations

import io
import textwrap
from typing import TYPE_CHECKING
from xml.etree import ElementTree as ET

import pytest
from PIL import Image

from vexy_lines import GroupInfo, LayerInfo, parse
from vexy_lines_api.rename import engine

if TYPE_CHECKING:
    from pathlib import Path

# group "Group A" id=1
#   layer "Layer 1" id=10 -> fill id=100 (linear), fill id=101 (circular)
#   layer "Layer 2" id=11 -> fill id=102 (linear)
_LINES_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <Project caption="Demo" version="2.1" dpi="150">
      <Document width_mm="100.0" height_mm="100.0" dpi="300"/>
      <Objects>
        <LrSection caption="Group A" object_id="1" expanded="1">
          <Objects>
            <FreeMesh caption="Layer 1" object_id="10" visible="1">
              <Objects>
                <LinearStrokesTmpl caption="L1" object_id="100" color_name="#000000"/>
                <CircleStrokesTmpl caption="C1" object_id="101" color_name="#000000"/>
              </Objects>
            </FreeMesh>
            <FreeMesh caption="Layer 2" object_id="11" visible="1">
              <Objects>
                <LinearStrokesTmpl caption="L2" object_id="102" color_name="#000000"/>
              </Objects>
            </FreeMesh>
          </Objects>
        </LrSection>
      </Objects>
    </Project>
""")


class FakeClient:
    """Stand-in MCP client; the injected renderer does all the work."""

    def open_document(self, _path: str) -> str:
        return "ok"


def _png() -> bytes:
    img = Image.new("RGB", (40, 40), (255, 255, 255))
    # draw a small block so make_inspection_image finds content
    for x in range(5, 15):
        for y in range(5, 15):
            img.putpixel((x, y), (0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _doc_order_describe(phrases_by_fid: dict[int, str]):
    """A describe() that returns phrases in document fill order (100, 101, 102)."""
    order = [100, 101, 102]
    idx = {"i": 0}

    def describe(_inspection_png: bytes) -> str:
        fid = order[idx["i"]]
        idx["i"] += 1
        return phrases_by_fid[fid]

    return describe


@pytest.fixture
def lines_file(tmp_path: Path) -> Path:
    p = tmp_path / "demo.lines"
    p.write_text(_LINES_XML, encoding="utf-8")
    return p


def test_build_rename_plan_produces_fill_and_layer_renames(lines_file: Path, tmp_path: Path):
    phrases = {100: "top left lines", 101: "center round dots", 102: "bottom hatching"}

    plan = engine.build_rename_plan(
        lines_file,
        FakeClient(),
        work_dir=tmp_path / "work",
        render_lines_png=lambda _client, _path: _png(),
        describe=_doc_order_describe(phrases),
        suggest=lambda items: "layer " + (items[0] if items else "empty"),
        save_artifacts=True,
    )

    assert {f.object_id for f in plan.fills} == {100, 101, 102}
    by_id = {f.object_id: f for f in plan.fills}
    assert by_id[100].new_caption == "top-left-lines"
    assert by_id[101].new_caption == "center-round-dots"
    assert by_id[102].new_caption == "bottom-hatching"
    assert by_id[100].layer_id == 10
    assert by_id[102].layer_id == 11

    assert {le.object_id for le in plan.layers} == {10, 11}
    layer_by_id = {le.object_id: le for le in plan.layers}
    assert layer_by_id[10].new_caption.startswith("layer-top-left")
    assert layer_by_id[10].fill_ids == [100, 101]

    work = tmp_path / "work"
    assert (work / "_full.png").is_file()
    assert (work / "fill_100_inspect.png").is_file()
    assert (work / "rename-plan.json").is_file()


def test_build_rename_plan_bakes_per_fill_visibility_into_files(lines_file: Path, tmp_path: Path):
    """Each per-fill render must target a file with only that fill visible."""
    captured: list[tuple[str, dict[int, str | None]]] = []

    def recording_render(_client, path):
        path_str = str(path)
        if path_str.endswith("demo.lines"):  # the full render targets the source
            captured.append(("full", {}))
            return _png()
        root = ET.parse(path).getroot()  # noqa: S314
        vis = {
            int(e.get("object_id")): e.get("visible")
            for e in root.iter()
            if e.get("object_id") is not None and e.tag.endswith("StrokesTmpl")
        }
        captured.append((path_str, vis))
        return _png()

    engine.build_rename_plan(
        lines_file,
        FakeClient(),
        work_dir=tmp_path / "work",
        render_lines_png=recording_render,
        describe=lambda _png: "a b c",
        suggest=lambda _items: "lyr",
        save_artifacts=False,
    )

    # First render is the full source; then one variant per fill.
    assert captured[0][0] == "full"
    variants = [v for name, v in captured[1:]]
    assert len(variants) == 3
    # In each variant exactly one fill is visible="1" and the rest are "0".
    for vis in variants:
        shown = [fid for fid, val in vis.items() if val == "1"]
        hidden = [fid for fid, val in vis.items() if val == "0"]
        assert len(shown) == 1
        assert set(hidden) == {100, 101, 102} - set(shown)


def test_as_renames_merges_layers_and_fills(lines_file: Path, tmp_path: Path):
    plan = engine.build_rename_plan(
        lines_file,
        FakeClient(),
        work_dir=tmp_path / "work",
        render_lines_png=lambda _client, _path: _png(),
        describe=lambda _png: "x y z",
        suggest=lambda _items: "lyr",
        save_artifacts=False,
    )
    assert set(plan.as_renames()) == {100, 101, 102, 10, 11}


def test_apply_rename_plan_writes_file(lines_file: Path, tmp_path: Path):
    plan = engine.build_rename_plan(
        lines_file,
        FakeClient(),
        work_dir=tmp_path / "work",
        render_lines_png=lambda _client, _path: _png(),
        describe=lambda _png: "red marks here",
        suggest=lambda _items: "the layer",
        save_artifacts=False,
    )
    out = tmp_path / "out.lines"
    count = engine.apply_rename_plan(plan, out)
    assert count == 5
    doc = parse(out)
    group = doc.groups[0]
    assert isinstance(group, GroupInfo)
    layer1 = group.children[0]
    assert isinstance(layer1, LayerInfo)
    assert layer1.fills[0].caption == "red-marks-here"


def test_dedupe_makes_unique():
    assert engine._dedupe(["a", "a", "b", "a"]) == ["a", "a-2", "b", "a-3"]


def test_rename_lines_dry_run_does_not_write(lines_file: Path, tmp_path: Path):
    plan = engine.rename_lines(
        lines_file,
        client=FakeClient(),
        work_dir=tmp_path / "work",
        dry_run=True,
        render_lines_png=lambda _client, _path: _png(),
        describe=lambda _png: "a b c",
        suggest=lambda _items: "l",
        save_artifacts=False,
    )
    assert len(plan.fills) == 3
    assert not (lines_file.with_name("demo-renamed.lines")).exists()


def test_rename_lines_writes_default_output(lines_file: Path, tmp_path: Path):
    engine.rename_lines(
        lines_file,
        client=FakeClient(),
        work_dir=tmp_path / "work",
        render_lines_png=lambda _client, _path: _png(),
        describe=lambda _png: "a b c",
        suggest=lambda _items: "l",
        save_artifacts=False,
    )
    assert lines_file.with_name("demo-renamed.lines").is_file()
