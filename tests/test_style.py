# this_file: vexy-lines-apy/tests/test_style.py
"""Tests for vexy_lines_api.style module.

Tests cover the style engine: extraction, compatibility checking,
interpolation, and internal helpers. All tests use synthetic data
and mock the parser / MCPClient as needed.
"""

from __future__ import annotations

import copy
from unittest.mock import MagicMock, patch

import pytest

from vexy_lines.types import (
    DocumentProps,
    FillNode,
    FillParams,
    GroupInfo,
    LayerInfo,
    LinesDocument,
)
from vexy_lines_api.style import (
    SPATIAL_PARAMS,
    Style,
    _compare_fills,
    _compare_structure,
    _compute_relative_scale,
    _fill_params_to_dict,
    _interpolate_doc_props,
    _interpolate_fill_params,
    _interpolate_group,
    _interpolate_layer,
    _lerp,
    _lerp_color,
    _scale_fill_params,
    _scale_style,
    apply_style,
    extract_style,
    interpolate_style,
    styles_compatible,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_fill(fill_type: str = "linear", color: str = "#000000", interval: float = 1.0) -> FillNode:
    """Create a FillNode with sensible defaults for testing."""
    return FillNode(
        xml_tag="LinearStrokesTmpl",
        caption=f"Test {fill_type}",
        params=FillParams(
            fill_type=fill_type,
            color=color,
            interval=interval,
            angle=45.0,
            thickness=1.0,
            smoothness=0.5,
            uplimit=200.0,
            downlimit=50.0,
            multiplier=1.0,
            base_width=0.5,
            dispersion=0.0,
            shear=0.0,
        ),
    )


def _make_layer(caption: str = "Layer", fills: list[FillNode] | None = None) -> LayerInfo:
    """Create a LayerInfo with one fill by default."""
    if fills is None:
        fills = [_make_fill()]
    return LayerInfo(caption=caption, fills=fills)


def _make_group(caption: str = "Group", children: list[GroupInfo | LayerInfo] | None = None) -> GroupInfo:
    """Create a GroupInfo with one layer by default."""
    if children is None:
        children = [_make_layer()]
    return GroupInfo(caption=caption, children=children)


def _make_props(
    width_mm: float = 210.0,
    height_mm: float = 297.0,
    dpi: int = 300,
    thickness_min: float = 0.1,
    thickness_max: float = 2.0,
    interval_min: float = 0.5,
    interval_max: float = 5.0,
) -> DocumentProps:
    """Create DocumentProps with sensible defaults."""
    return DocumentProps(
        width_mm=width_mm,
        height_mm=height_mm,
        dpi=dpi,
        thickness_min=thickness_min,
        thickness_max=thickness_max,
        interval_min=interval_min,
        interval_max=interval_max,
    )


def _make_style(
    groups: list[GroupInfo | LayerInfo] | None = None,
    props: DocumentProps | None = None,
    source_path: str | None = "/test/style.lines",
) -> Style:
    """Create a Style with sensible defaults."""
    if groups is None:
        groups = [_make_group()]
    if props is None:
        props = _make_props()
    return Style(groups=groups, props=props, source_path=source_path)


# ---------------------------------------------------------------------------
# Style dataclass
# ---------------------------------------------------------------------------


class TestStyle:
    """Tests for the Style dataclass."""

    def test_construction(self):
        groups = [_make_group()]
        props = _make_props()
        style = Style(groups=groups, props=props, source_path="/test.lines")
        assert style.source_path == "/test.lines"
        assert len(style.groups) == 1
        assert style.props.width_mm == 210.0

    def test_source_path_default_none(self):
        style = Style(groups=[], props=_make_props())
        assert style.source_path is None


# ---------------------------------------------------------------------------
# _lerp
# ---------------------------------------------------------------------------


class TestLerp:
    """Tests for the _lerp function."""

    def test_lerp_t0(self):
        assert _lerp(10.0, 20.0, 0.0) == 10.0

    def test_lerp_t1(self):
        assert _lerp(10.0, 20.0, 1.0) == 20.0

    def test_lerp_t05(self):
        assert _lerp(10.0, 20.0, 0.5) == 15.0

    def test_lerp_negative_values(self):
        assert _lerp(-10.0, 10.0, 0.5) == 0.0

    def test_lerp_same_values(self):
        assert _lerp(5.0, 5.0, 0.7) == 5.0


# ---------------------------------------------------------------------------
# _lerp_color
# ---------------------------------------------------------------------------


class TestLerpColor:
    """Tests for the _lerp_color function."""

    def test_rgb_t0(self):
        result = _lerp_color("#ff0000", "#0000ff", 0.0)
        assert result == "#ff0000"

    def test_rgb_t1(self):
        result = _lerp_color("#ff0000", "#0000ff", 1.0)
        assert result == "#0000ff"

    def test_rgb_t05(self):
        """Midpoint between red and blue."""
        result = _lerp_color("#ff0000", "#0000ff", 0.5)
        # R: 255->0 midpoint = 128, G: 0->0 = 0, B: 0->255 midpoint = 128
        assert result == "#800080"

    def test_rgba_preserves_alpha(self):
        result = _lerp_color("#ff0000ff", "#0000ff00", 0.5)
        # R: 128, G: 0, B: 128, A: 128
        assert result == "#80008080"

    def test_mixed_rgb_rgba(self):
        """When one colour has alpha and the other doesn't, output has alpha."""
        result = _lerp_color("#ff0000", "#0000ff80", 0.0)
        # a gets extended to #ff0000ff, so at t=0 result is #ff0000ff
        assert result == "#ff0000ff"

    def test_black_to_white(self):
        result = _lerp_color("#000000", "#ffffff", 0.5)
        assert result == "#808080"

    def test_same_color(self):
        result = _lerp_color("#abcdef", "#abcdef", 0.5)
        assert result == "#abcdef"


# ---------------------------------------------------------------------------
# _compare_structure and _compare_fills
# ---------------------------------------------------------------------------


class TestCompareStructure:
    """Tests for _compare_structure."""

    def test_identical_structures(self):
        a = [_make_group()]
        b = [_make_group()]
        assert _compare_structure(a, b) is True

    def test_different_length(self):
        a = [_make_group(), _make_group()]
        b = [_make_group()]
        assert _compare_structure(a, b) is False

    def test_different_types(self):
        a: list[GroupInfo | LayerInfo] = [_make_group()]
        b: list[GroupInfo | LayerInfo] = [_make_layer()]
        assert _compare_structure(a, b) is False

    def test_nested_mismatch(self):
        """Groups with different number of children don't match."""
        g1 = _make_group(children=[_make_layer(), _make_layer()])
        g2 = _make_group(children=[_make_layer()])
        assert _compare_structure([g1], [g2]) is False

    def test_empty_lists(self):
        assert _compare_structure([], []) is True

    def test_multiple_groups_match(self):
        a = [_make_group(caption="A"), _make_group(caption="B")]
        b = [_make_group(caption="X"), _make_group(caption="Y")]
        assert _compare_structure(a, b) is True


class TestCompareFills:
    """Tests for _compare_fills."""

    def test_matching_fills(self):
        a = [_make_fill("linear"), _make_fill("circular")]
        b = [_make_fill("linear"), _make_fill("circular")]
        assert _compare_fills(a, b) is True

    def test_different_fill_types(self):
        a = [_make_fill("linear")]
        b = [_make_fill("circular")]
        assert _compare_fills(a, b) is False

    def test_different_count(self):
        a = [_make_fill()]
        b = [_make_fill(), _make_fill()]
        assert _compare_fills(a, b) is False

    def test_empty_lists(self):
        assert _compare_fills([], []) is True


# ---------------------------------------------------------------------------
# styles_compatible
# ---------------------------------------------------------------------------


class TestStylesCompatible:
    """Tests for styles_compatible."""

    def test_compatible(self):
        a = _make_style()
        b = _make_style()
        assert styles_compatible(a, b) is True

    def test_incompatible_different_groups(self):
        a = _make_style(groups=[_make_group()])
        b = _make_style(groups=[_make_group(), _make_group()])
        assert styles_compatible(a, b) is False

    def test_incompatible_different_fill_types(self):
        a = _make_style(groups=[_make_group(children=[_make_layer(fills=[_make_fill("linear")])])])
        b = _make_style(groups=[_make_group(children=[_make_layer(fills=[_make_fill("circular")])])])
        assert styles_compatible(a, b) is False


# ---------------------------------------------------------------------------
# interpolate_style
# ---------------------------------------------------------------------------


class TestInterpolateStyle:
    """Tests for interpolate_style."""

    def test_t0_returns_style_a(self):
        a = _make_style()
        b = _make_style()
        result = interpolate_style(a, b, 0.0)
        fill_a = a.groups[0].children[0].fills[0].params  # type: ignore[union-attr]
        fill_r = result.groups[0].children[0].fills[0].params  # type: ignore[union-attr]
        assert fill_r.interval == fill_a.interval
        assert fill_r.angle == fill_a.angle

    def test_t1_returns_style_b(self):
        fill_b = _make_fill(interval=10.0)
        b = _make_style(groups=[_make_group(children=[_make_layer(fills=[fill_b])])])
        a = _make_style()
        result = interpolate_style(a, b, 1.0)
        fill_r = result.groups[0].children[0].fills[0].params  # type: ignore[union-attr]
        assert fill_r.interval == 10.0

    def test_t05_interpolates(self):
        fill_a = _make_fill(interval=0.0)
        fill_b = _make_fill(interval=10.0)
        a = _make_style(groups=[_make_group(children=[_make_layer(fills=[fill_a])])])
        b = _make_style(groups=[_make_group(children=[_make_layer(fills=[fill_b])])])
        result = interpolate_style(a, b, 0.5)
        fill_r = result.groups[0].children[0].fills[0].params  # type: ignore[union-attr]
        assert fill_r.interval == 5.0

    def test_incompatible_returns_copy_of_a(self):
        a = _make_style(groups=[_make_group()])
        b = _make_style(groups=[_make_group(), _make_group()])
        result = interpolate_style(a, b, 0.5)
        assert len(result.groups) == 1  # Same as a
        assert result.source_path == a.source_path

    def test_t_clamped_below_zero(self):
        a = _make_style()
        b = _make_style()
        result = interpolate_style(a, b, -0.5)
        # Should behave like t=0
        fill_a = a.groups[0].children[0].fills[0].params  # type: ignore[union-attr]
        fill_r = result.groups[0].children[0].fills[0].params  # type: ignore[union-attr]
        assert fill_r.interval == fill_a.interval

    def test_t_clamped_above_one(self):
        fill_b = _make_fill(interval=20.0)
        a = _make_style()
        b = _make_style(groups=[_make_group(children=[_make_layer(fills=[fill_b])])])
        result = interpolate_style(a, b, 1.5)
        fill_r = result.groups[0].children[0].fills[0].params  # type: ignore[union-attr]
        assert fill_r.interval == 20.0

    def test_source_path_is_none(self):
        a = _make_style(source_path="/a.lines")
        b = _make_style(source_path="/b.lines")
        result = interpolate_style(a, b, 0.5)
        assert result.source_path is None

    def test_doc_props_interpolated(self):
        props_a = _make_props(width_mm=100.0, thickness_min=0.0)
        props_b = _make_props(width_mm=200.0, thickness_min=2.0)
        a = _make_style(props=props_a)
        b = _make_style(props=props_b)
        result = interpolate_style(a, b, 0.5)
        assert result.props.width_mm == 150.0
        assert result.props.thickness_min == 1.0

    def test_dpi_kept_from_a(self):
        props_a = _make_props(dpi=72)
        props_b = _make_props(dpi=300)
        a = _make_style(props=props_a)
        b = _make_style(props=props_b)
        result = interpolate_style(a, b, 0.5)
        assert result.props.dpi == 72


# ---------------------------------------------------------------------------
# _interpolate_fill_params
# ---------------------------------------------------------------------------


class TestInterpolateFillParams:
    """Tests for _interpolate_fill_params."""

    def test_color_interpolation(self):
        a = FillParams(fill_type="linear", color="#ff0000", interval=1.0)
        b = FillParams(fill_type="linear", color="#0000ff", interval=1.0)
        result = _interpolate_fill_params(a, b, 0.5)
        assert result.color == "#800080"

    def test_no_color_interpolation_when_missing(self):
        a = FillParams(fill_type="linear", color="", interval=1.0)
        b = FillParams(fill_type="linear", color="#ff0000", interval=1.0)
        result = _interpolate_fill_params(a, b, 0.5)
        assert result.color == ""

    def test_numeric_params_interpolated(self):
        a = FillParams(fill_type="linear", color="#000000", interval=0.0, angle=0.0)
        b = FillParams(fill_type="linear", color="#000000", interval=10.0, angle=90.0)
        result = _interpolate_fill_params(a, b, 0.5)
        assert result.interval == 5.0
        assert result.angle == 45.0

    def test_original_not_mutated(self):
        a = FillParams(fill_type="linear", color="#ff0000", interval=1.0)
        b = FillParams(fill_type="linear", color="#0000ff", interval=2.0)
        a_copy = copy.deepcopy(a)
        _interpolate_fill_params(a, b, 0.5)
        assert a.interval == a_copy.interval
        assert a.color == a_copy.color


# ---------------------------------------------------------------------------
# _interpolate_doc_props
# ---------------------------------------------------------------------------


class TestInterpolateDocProps:
    """Tests for _interpolate_doc_props."""

    def test_width_height_interpolated(self):
        a = _make_props(width_mm=100.0, height_mm=100.0)
        b = _make_props(width_mm=200.0, height_mm=200.0)
        result = _interpolate_doc_props(a, b, 0.5)
        assert result.width_mm == 150.0
        assert result.height_mm == 150.0

    def test_dpi_kept_from_a(self):
        a = _make_props(dpi=72)
        b = _make_props(dpi=300)
        result = _interpolate_doc_props(a, b, 0.5)
        assert result.dpi == 72

    def test_thickness_range_interpolated(self):
        a = _make_props(thickness_min=0.0, thickness_max=1.0)
        b = _make_props(thickness_min=2.0, thickness_max=4.0)
        result = _interpolate_doc_props(a, b, 0.5)
        assert result.thickness_min == 1.0
        assert result.thickness_max == 2.5


# ---------------------------------------------------------------------------
# _fill_params_to_dict
# ---------------------------------------------------------------------------


class TestFillParamsToDict:
    """Tests for _fill_params_to_dict."""

    def test_extracts_numeric_params_with_mcp_names(self):
        params = FillParams(fill_type="linear", color="#000000", interval=2.0, angle=45.0, smoothness=0.0)
        result = _fill_params_to_dict(params)
        assert "interval" in result
        assert "angle" in result
        assert result["interval"] == 2.0

    def test_translates_parser_names_to_mcp_names(self):
        params = FillParams(fill_type="linear", color="", uplimit=200.0, downlimit=50.0, multiplier=1.5, smoothness=0.5)
        result = _fill_params_to_dict(params)
        assert "break_up" in result
        assert result["break_up"] == 200.0
        assert "break_down" in result
        assert result["break_down"] == 50.0
        # MCP "thickness" = FillParams.multiplier (XML multiplier)
        assert "thickness" in result
        assert result["thickness"] == 1.5
        # MCP "contrast" = FillParams.smoothness (XML smoothness)
        assert "contrast" in result
        assert result["contrast"] == 0.5
        # Parser field names should NOT appear as MCP keys
        assert "uplimit" not in result
        assert "downlimit" not in result
        assert "multiplier" not in result
        assert "smoothness" not in result

    def test_includes_color_when_set(self):
        params = FillParams(fill_type="linear", color="#ff0000")
        result = _fill_params_to_dict(params)
        assert result["color"] == "#ff0000"
        assert result["color_mode"] == 2

    def test_excludes_fill_type(self):
        params = FillParams(fill_type="linear", color="")
        result = _fill_params_to_dict(params)
        assert "fill_type" not in result


# ---------------------------------------------------------------------------
# extract_style (mocked parser)
# ---------------------------------------------------------------------------


class TestExtractStyle:
    """Tests for extract_style with a mocked parser."""

    def test_extract_style_returns_style(self):
        mock_doc = LinesDocument(
            caption="Test",
            version="1.0",
            dpi=300,
            props=_make_props(),
            groups=[_make_group()],
        )
        with patch("vexy_lines_api.style._parse_lines_file", return_value=mock_doc):
            style = extract_style("/fake/path.lines")
            assert isinstance(style, Style)
            assert style.source_path == "/fake/path.lines"
            assert len(style.groups) == 1

    def test_extract_style_deep_copies(self):
        """Modifying the extracted style shouldn't affect the original doc."""
        original_group = _make_group()
        mock_doc = LinesDocument(
            caption="Test",
            props=_make_props(),
            groups=[original_group],
        )
        with patch("vexy_lines_api.style._parse_lines_file", return_value=mock_doc):
            style = extract_style("/fake/path.lines")
            # Modify the extracted style
            style.groups.clear()
            # Original should be unchanged
            assert len(original_group.children) == 1


# ---------------------------------------------------------------------------
# apply_style (mocked client)
# ---------------------------------------------------------------------------


class TestApplyStyle:
    """Tests for apply_style with a mocked MCPClient."""

    def test_apply_style_creates_document_and_returns_svg(self):
        mock_client = MagicMock()
        mock_client.new_document.return_value = MagicMock(root_id=1, width=100, height=100, dpi=72)
        mock_client.add_group.return_value = {"id": 2}
        mock_client.add_layer.return_value = {"id": 3}
        mock_client.add_fill.return_value = {"id": 4}
        mock_client.render.return_value = True
        mock_client.svg.return_value = "<svg>test</svg>"

        style = _make_style()
        result = apply_style(mock_client, style, "/fake/image.png", dpi=72)

        assert result == "<svg>test</svg>"
        mock_client.new_document.assert_called_once()
        mock_client.render.assert_called_once()
        mock_client.svg.assert_called_once()

    def test_apply_style_replicates_tree(self):
        """apply_style creates groups, layers, and fills matching the style tree."""
        mock_client = MagicMock()
        mock_client.new_document.return_value = MagicMock(root_id=1, width=100, height=100, dpi=72)
        mock_client.add_group.return_value = {"id": 10}
        mock_client.add_layer.return_value = {"id": 20}
        mock_client.add_fill.return_value = {"id": 30}
        mock_client.render.return_value = True
        mock_client.svg.return_value = "<svg/>"

        # Style with 1 group containing 2 layers, each with 1 fill
        layer1 = _make_layer(caption="L1", fills=[_make_fill("linear")])
        layer2 = _make_layer(caption="L2", fills=[_make_fill("circular")])
        group = _make_group(children=[layer1, layer2])
        style = _make_style(groups=[group])

        apply_style(mock_client, style, "/fake.png")

        assert mock_client.add_group.call_count == 1
        assert mock_client.add_layer.call_count == 2
        assert mock_client.add_fill.call_count == 2


# ---------------------------------------------------------------------------
# _scale_fill_params
# ---------------------------------------------------------------------------


class TestScaleFillParams:
    """Tests for _scale_fill_params."""

    def test_scale_factor_1_returns_identical_copy(self):
        params = FillParams(fill_type="linear", color="#ff0000", interval=2.0, angle=45.0)
        result = _scale_fill_params(params, 1.0)
        assert result.interval == 2.0
        assert result.angle == 45.0
        assert result is not params  # must be a copy

    def test_spatial_params_scaled(self):
        params = FillParams(
            fill_type="linear",
            color="#000000",
            interval=4.0,
            thickness=2.0,
            base_width=1.0,
            dispersion=3.0,
        )
        result = _scale_fill_params(params, 2.0)
        assert result.interval == 8.0, "interval should be scaled"
        assert result.base_width == 2.0, "base_width should be scaled"
        assert result.dispersion == 6.0, "dispersion should be scaled"

    def test_non_spatial_params_unchanged(self):
        params = FillParams(
            fill_type="linear",
            color="#000000",
            angle=90.0,
            smoothness=0.5,
            uplimit=200.0,
            downlimit=50.0,
            shear=10.0,
        )
        result = _scale_fill_params(params, 3.0)
        assert result.angle == 90.0, "angle should NOT be scaled"
        assert result.smoothness == 0.5, "smoothness should NOT be scaled"
        assert result.uplimit == 200.0, "uplimit should NOT be scaled"
        assert result.downlimit == 50.0, "downlimit should NOT be scaled"
        assert result.shear == 10.0, "shear should NOT be scaled"

    def test_multiplier_is_spatial(self):
        params = FillParams(fill_type="linear", color="#000000", multiplier=1.5)
        result = _scale_fill_params(params, 3.0)
        assert result.multiplier == 4.5, "multiplier (MCP thickness) should be scaled"

    def test_color_unchanged(self):
        params = FillParams(fill_type="linear", color="#ff0000", interval=1.0)
        result = _scale_fill_params(params, 2.0)
        assert result.color == "#ff0000"

    def test_fill_type_unchanged(self):
        params = FillParams(fill_type="circular", color="#000000", interval=1.0)
        result = _scale_fill_params(params, 5.0)
        assert result.fill_type == "circular"

    def test_original_not_mutated(self):
        params = FillParams(fill_type="linear", color="#000000", interval=2.0)
        _scale_fill_params(params, 3.0)
        assert params.interval == 2.0, "original should not be mutated"

    def test_scale_factor_zero(self):
        params = FillParams(fill_type="linear", color="#000000", interval=5.0, base_width=2.0)
        result = _scale_fill_params(params, 0.0)
        assert result.interval == 0.0
        assert result.base_width == 0.0

    def test_fractional_scale(self):
        params = FillParams(fill_type="linear", color="#000000", interval=10.0)
        result = _scale_fill_params(params, 0.5)
        assert result.interval == 5.0


# ---------------------------------------------------------------------------
# _compute_relative_scale
# ---------------------------------------------------------------------------


class TestComputeRelativeScale:
    """Tests for _compute_relative_scale."""

    def test_same_dimensions_returns_1(self):
        style = _make_style(props=_make_props(width_mm=100.0, height_mm=100.0))
        scale = _compute_relative_scale(style, 100.0, 100.0)
        assert scale == 1.0

    def test_double_dimensions(self):
        import math

        style = _make_style(props=_make_props(width_mm=100.0, height_mm=100.0))
        scale = _compute_relative_scale(style, 200.0, 200.0)
        assert scale == pytest.approx(2.0), "doubling both dims should give scale=2.0"

    def test_half_dimensions(self):
        style = _make_style(props=_make_props(width_mm=200.0, height_mm=200.0))
        scale = _compute_relative_scale(style, 100.0, 100.0)
        assert scale == pytest.approx(0.5)

    def test_asymmetric_scaling_uses_geometric_mean(self):
        import math

        style = _make_style(props=_make_props(width_mm=100.0, height_mm=100.0))
        # scale_x=4, scale_y=1 => geometric mean = sqrt(4*1) = 2.0
        scale = _compute_relative_scale(style, 400.0, 100.0)
        assert scale == pytest.approx(2.0)

    def test_zero_source_width_returns_1(self):
        style = _make_style(props=_make_props(width_mm=0.0, height_mm=100.0))
        scale = _compute_relative_scale(style, 200.0, 200.0)
        assert scale == 1.0

    def test_zero_source_height_returns_1(self):
        style = _make_style(props=_make_props(width_mm=100.0, height_mm=0.0))
        scale = _compute_relative_scale(style, 200.0, 200.0)
        assert scale == 1.0

    def test_zero_target_width_returns_1(self):
        style = _make_style(props=_make_props(width_mm=100.0, height_mm=100.0))
        scale = _compute_relative_scale(style, 0.0, 200.0)
        assert scale == 1.0

    def test_zero_target_height_returns_1(self):
        style = _make_style(props=_make_props(width_mm=100.0, height_mm=100.0))
        scale = _compute_relative_scale(style, 200.0, 0.0)
        assert scale == 1.0

    def test_negative_source_returns_1(self):
        style = _make_style(props=_make_props(width_mm=-100.0, height_mm=100.0))
        scale = _compute_relative_scale(style, 200.0, 200.0)
        assert scale == 1.0


# ---------------------------------------------------------------------------
# _scale_style
# ---------------------------------------------------------------------------


class TestScaleStyle:
    """Tests for _scale_style."""

    def test_scale_1_returns_deep_copy(self):
        style = _make_style()
        result = _scale_style(style, 1.0)
        assert result is not style
        assert result.groups is not style.groups

    def test_fills_scaled_in_nested_tree(self):
        fill = _make_fill(interval=4.0)
        layer = _make_layer(fills=[fill])
        group = _make_group(children=[layer])
        style = _make_style(groups=[group])

        result = _scale_style(style, 2.0)
        result_fill = result.groups[0].children[0].fills[0].params  # type: ignore[union-attr]
        assert result_fill.interval == 8.0

    def test_original_not_mutated(self):
        fill = _make_fill(interval=4.0)
        layer = _make_layer(fills=[fill])
        group = _make_group(children=[layer])
        style = _make_style(groups=[group])

        _scale_style(style, 2.0)
        original_fill = style.groups[0].children[0].fills[0].params  # type: ignore[union-attr]
        assert original_fill.interval == 4.0

    def test_props_not_scaled(self):
        """Document props should be deep-copied but not scaled."""
        style = _make_style(props=_make_props(width_mm=100.0, interval_min=1.0))
        result = _scale_style(style, 2.0)
        assert result.props.width_mm == 100.0
        assert result.props.interval_min == 1.0


# ---------------------------------------------------------------------------
# apply_style with relative mode (mocked client)
# ---------------------------------------------------------------------------


class TestApplyStyleRelative:
    """Tests for apply_style with relative=True."""

    def _mock_client(self, target_width: float = 200.0, target_height: float = 200.0):
        mock = MagicMock()
        mock.new_document.return_value = MagicMock(
            root_id=1, width=target_width, height=target_height, dpi=72,
        )
        mock.add_group.return_value = {"id": 2}
        mock.add_layer.return_value = {"id": 3}
        mock.add_fill.return_value = {"id": 4}
        mock.render.return_value = True
        mock.svg.return_value = "<svg>test</svg>"
        return mock

    def test_absolute_mode_does_not_scale(self):
        """With relative=False (default), params are used as-is."""
        client = self._mock_client(target_width=400.0, target_height=400.0)
        fill = _make_fill(interval=2.0)
        layer = _make_layer(fills=[fill])
        group = _make_group(children=[layer])
        style = _make_style(
            groups=[group],
            props=_make_props(width_mm=100.0, height_mm=100.0),
        )

        apply_style(client, style, "/fake.png", relative=False)

        # Check the interval passed to set_fill_params
        call_kwargs = client.set_fill_params.call_args
        assert call_kwargs is not None
        _, kwargs = call_kwargs
        assert kwargs["interval"] == 2.0, "absolute mode should not scale interval"

    def test_relative_mode_scales_params(self):
        """With relative=True, spatial params are scaled by the dimension ratio."""
        # Source style: 100x100, target: 200x200 => scale = 2.0
        client = self._mock_client(target_width=200.0, target_height=200.0)
        fill = _make_fill(interval=2.0)
        layer = _make_layer(fills=[fill])
        group = _make_group(children=[layer])
        style = _make_style(
            groups=[group],
            props=_make_props(width_mm=100.0, height_mm=100.0),
        )

        apply_style(client, style, "/fake.png", relative=True)

        call_kwargs = client.set_fill_params.call_args
        assert call_kwargs is not None
        _, kwargs = call_kwargs
        assert kwargs["interval"] == pytest.approx(4.0), "relative mode should double interval"

    def test_relative_mode_same_size_no_change(self):
        """When source and target are the same size, relative mode changes nothing."""
        client = self._mock_client(target_width=100.0, target_height=100.0)
        fill = _make_fill(interval=5.0)
        layer = _make_layer(fills=[fill])
        group = _make_group(children=[layer])
        style = _make_style(
            groups=[group],
            props=_make_props(width_mm=100.0, height_mm=100.0),
        )

        apply_style(client, style, "/fake.png", relative=True)

        call_kwargs = client.set_fill_params.call_args
        assert call_kwargs is not None
        _, kwargs = call_kwargs
        assert kwargs["interval"] == 5.0, "same size should not change interval"
