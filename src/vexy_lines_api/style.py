# this_file: vexy-lines-apy/src/vexy_lines_api/style.py
"""Style engine: extract, apply, and interpolate fill structures from .lines files.

A Style captures the group->layer->fill tree and document properties from a
.lines file. It can be applied to a source image via MCP to produce rendered
SVG output, or interpolated with another compatible style to create smooth
transitions between two artistic treatments.

Pipeline::

    .lines file -> extract_style() -> Style dataclass
    Style + source image -> apply_style(client, ...) -> SVG string
    Style A + Style B + t -> interpolate_style(a, b, t) -> blended Style
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from vexy_lines.types import (
    NUMERIC_PARAMS,
    DocumentProps,
    FillNode,
    FillParams,
    GroupInfo,
    LayerInfo,
    LinesDocument,
)

if TYPE_CHECKING:
    from vexy_lines_api.client import MCPClient

_HEX_RGB_LEN = 6
_HEX_RGBA_LEN = 8

# Map parser FillParams field names to MCP server parameter names.
# The parser uses XML attribute names; the MCP server uses its own naming.
PARSER_TO_MCP_PARAMS: dict[str, str] = {
    "interval": "interval",
    "angle": "angle",
    "thickness": "thickness",
    "thickness_min": "thickness_min",
    "smoothness": "smoothness",
    "uplimit": "break_up",
    "downlimit": "break_down",
    "multiplier": "contrast",
    "dispersion": "dispersion",
}
"""FillParams field name -> MCP ``set_fill_params`` key name."""

# Spatial params that should be scaled when applying a style in relative mode.
# These represent physical dimensions (mm, pixels) that change with document size.
# Excluded: angle, smoothness, uplimit, downlimit, multiplier, shear (ratios/degrees/thresholds).
SPATIAL_PARAMS: frozenset[str] = frozenset({
    "interval",
    "thick_gap",
    "base_width",
    "dispersion",
    "vert_disp",
})


# ---------------------------------------------------------------------------
# Style dataclass
# ---------------------------------------------------------------------------


@dataclass
class Style:
    """A transferable style extracted from a .lines document.

    Contains the group->layer->fill structure with all fill parameters,
    plus document-level properties like DPI and thickness ranges.

    Attributes:
        groups: Top-level tree of groups and layers.
        props: Document-level properties (dimensions, DPI, thickness ranges).
        source_path: Path of the ``.lines`` file this style was extracted from.
    """

    groups: list[GroupInfo | LayerInfo]
    props: DocumentProps
    source_path: str | None = None


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def _parse_lines_file(path: Path) -> LinesDocument:
    """Parse a .lines file, importing the parser lazily to keep startup fast."""
    from vexy_lines import parse  # noqa: PLC0415

    return parse(path)


def extract_style(path: str | Path) -> Style:
    """Extract the fill style structure from a .lines file.

    Parses the file and returns a Style containing the full group->layer->fill
    tree and document properties. The style can then be applied to other
    images or interpolated with another style.

    Args:
        path: Path to a ``.lines`` file.

    Returns:
        Style with the complete group->layer->fill tree and document props.
    """
    path = Path(path)
    logger.debug("Extracting style from {}", path)
    doc: LinesDocument = _parse_lines_file(path)
    return Style(
        groups=copy.deepcopy(doc.groups),
        props=copy.deepcopy(doc.props),
        source_path=str(path),
    )


# ---------------------------------------------------------------------------
# Compatibility check
# ---------------------------------------------------------------------------


def styles_compatible(a: Style, b: Style) -> bool:
    """Check if two styles have compatible structures for interpolation.

    Two styles are compatible if they have the same tree structure:
    same number of groups, layers within groups, and fills within layers,
    with matching fill types at each position.

    Args:
        a: First style.
        b: Second style.

    Returns:
        ``True`` if the styles can be interpolated, ``False`` otherwise.
    """
    return _compare_structure(a.groups, b.groups)


# ---------------------------------------------------------------------------
# Interpolation
# ---------------------------------------------------------------------------


def interpolate_style(a: Style, b: Style, t: float) -> Style:
    """Interpolate between two compatible styles.

    Args:
        a: Start style (``t=0``).
        b: End style (``t=1``).
        t: Interpolation factor in ``[0, 1]``.

    Returns:
        New Style with linearly interpolated numeric fill parameters.
        String parameters (like colour) are interpolated as hex RGB.
        If styles are incompatible, returns a deep copy of style *a* unchanged.
    """
    t = max(0.0, min(1.0, t))

    if not styles_compatible(a, b):
        logger.warning(
            "Styles are not compatible for interpolation (source_a={}, source_b={}). Returning style a.",
            a.source_path,
            b.source_path,
        )
        return Style(
            groups=copy.deepcopy(a.groups),
            props=copy.deepcopy(a.props),
            source_path=a.source_path,
        )

    interpolated_groups: list[GroupInfo | LayerInfo] = []
    for node_a, node_b in zip(a.groups, b.groups, strict=True):
        if isinstance(node_a, GroupInfo) and isinstance(node_b, GroupInfo):
            interpolated_groups.append(_interpolate_group(node_a, node_b, t))
        elif isinstance(node_a, LayerInfo) and isinstance(node_b, LayerInfo):
            interpolated_groups.append(_interpolate_layer(node_a, node_b, t))
        else:
            # Shouldn't happen if compatible, but be safe
            interpolated_groups.append(copy.deepcopy(node_a))

    # Interpolate document props (numeric fields only)
    interpolated_props = _interpolate_doc_props(a.props, b.props, t)

    return Style(
        groups=interpolated_groups,
        props=interpolated_props,
        source_path=None,
    )


# ---------------------------------------------------------------------------
# Relative-mode scaling
# ---------------------------------------------------------------------------


def _scale_fill_params(params: FillParams, scale: float) -> FillParams:
    """Return a copy of *params* with spatial numeric values multiplied by *scale*.

    Only parameters listed in :data:`SPATIAL_PARAMS` are scaled.  Non-spatial
    parameters (angles, brightness thresholds, ratios) are left unchanged.

    A *scale* of ``1.0`` returns an identical copy.

    Args:
        params: Original fill parameters.
        scale: Multiplicative scale factor (e.g. ``2.0`` doubles spatial values).

    Returns:
        New :class:`~vexy_lines.types.FillParams` with scaled spatial values.
    """
    result = copy.deepcopy(params)
    if scale == 1.0:
        return result

    for field_name in NUMERIC_PARAMS:
        if field_name not in SPATIAL_PARAMS:
            continue
        value = getattr(result, field_name, None)
        if value is not None:
            setattr(result, field_name, float(value) * scale)

    return result


def _compute_relative_scale(style: Style, target_width: float, target_height: float) -> float:
    """Compute a uniform scale factor from source style dimensions to target dimensions.

    Uses the geometric mean of the X and Y ratios so that scaling is uniform
    regardless of aspect-ratio differences.  Returns ``1.0`` when the source
    dimensions are zero (no scaling possible).

    Args:
        style: Source style containing original document dimensions.
        target_width: Target document width (pixels or mm, same unit as source).
        target_height: Target document height (pixels or mm, same unit as source).

    Returns:
        Geometric-mean scale factor, or ``1.0`` if source dimensions are zero.
    """
    src_w = style.props.width_mm
    src_h = style.props.height_mm
    if src_w <= 0 or src_h <= 0:
        logger.warning(
            "Source style has zero/negative dimensions ({}x{}); relative scaling disabled",
            src_w,
            src_h,
        )
        return 1.0
    if target_width <= 0 or target_height <= 0:
        logger.warning(
            "Target document has zero/negative dimensions ({}x{}); relative scaling disabled",
            target_width,
            target_height,
        )
        return 1.0

    import math  # noqa: PLC0415

    scale_x = target_width / src_w
    scale_y = target_height / src_h
    return math.sqrt(scale_x * scale_y)


def _scale_style(style: Style, scale: float) -> Style:
    """Return a deep copy of *style* with all spatial fill params scaled.

    Args:
        style: Original style.
        scale: Uniform scale factor.

    Returns:
        New :class:`Style` with scaled fills.  If *scale* is ``1.0`` a plain
        deep copy is returned.
    """
    if scale == 1.0:
        return Style(
            groups=copy.deepcopy(style.groups),
            props=copy.deepcopy(style.props),
            source_path=style.source_path,
        )

    def _scale_nodes(nodes: list[GroupInfo | LayerInfo]) -> list[GroupInfo | LayerInfo]:
        result: list[GroupInfo | LayerInfo] = []
        for node in nodes:
            if isinstance(node, GroupInfo):
                result.append(
                    GroupInfo(
                        caption=node.caption,
                        object_id=node.object_id,
                        expanded=node.expanded,
                        children=_scale_nodes(node.children),
                    )
                )
            elif isinstance(node, LayerInfo):
                scaled_fills = [
                    FillNode(
                        xml_tag=f.xml_tag,
                        caption=f.caption,
                        params=_scale_fill_params(f.params, scale),
                        object_id=f.object_id,
                    )
                    for f in node.fills
                ]
                result.append(
                    LayerInfo(
                        caption=node.caption,
                        object_id=node.object_id,
                        visible=node.visible,
                        mask=copy.deepcopy(node.mask),
                        fills=scaled_fills,
                        grid_edges=copy.deepcopy(node.grid_edges),
                    )
                )
        return result

    return Style(
        groups=_scale_nodes(style.groups),
        props=copy.deepcopy(style.props),
        source_path=style.source_path,
    )


# ---------------------------------------------------------------------------
# Application via MCP
# ---------------------------------------------------------------------------


def apply_style(
    client: MCPClient,
    style: Style,
    source_image: str | Path,
    *,
    dpi: int = 72,
    relative: bool = False,
) -> str:
    """Apply a style to a source image via MCP and return the SVG result.

    Creates a new document in Vexy Lines, replicates the style's
    group->layer->fill structure, sets all fill parameters, renders,
    and exports as SVG.

    When *relative* is ``True``, spatial fill parameters (interval,
    thickness, base_width, dispersion, vert_disp) are scaled by the
    geometric mean of the width and height ratios between the source
    style's document and the new target document.  This makes styles
    look consistent regardless of image size.

    Args:
        client: Connected :class:`~vexy_lines_api.client.MCPClient` instance.
        style: Style to apply.
        source_image: Path to the source image file.
        dpi: Document DPI (lower = faster, 72 good for video).
        relative: If ``True``, scale spatial params to match target image
            dimensions (relative mode).  Default ``False`` (absolute mode).

    Returns:
        SVG string of the rendered result.
    """
    source_image = Path(source_image).expanduser().resolve()
    logger.debug(
        "Applying style (source={}, relative={}) to image {} at {}dpi",
        style.source_path,
        relative,
        source_image,
        dpi,
    )

    # 1. Create new document with the source image
    doc_result = client.new_document(source_image=str(source_image), dpi=dpi)
    root_id = doc_result.root_id
    logger.debug(
        "Created document: root_id={}, {}x{} @ {}dpi",
        root_id,
        doc_result.width,
        doc_result.height,
        doc_result.dpi,
    )

    # 2. Optionally scale style params for relative mode
    effective_style = style
    if relative:
        scale = _compute_relative_scale(style, doc_result.width, doc_result.height)
        logger.debug("Relative mode: scale factor = {:.4f}", scale)
        if scale != 1.0:
            effective_style = _scale_style(style, scale)

    # 3. Replicate the style tree
    for node in effective_style.groups:
        if isinstance(node, GroupInfo):
            _apply_group(client, node, parent_id=root_id)
        elif isinstance(node, LayerInfo):
            _apply_layer(client, node, group_id=root_id)

    # 4. Render and wait
    logger.debug("Rendering...")
    client.render(timeout=60.0)

    # 5. Export SVG
    logger.debug("Exporting SVG")
    return client.svg()


# ---------------------------------------------------------------------------
# Internal: apply helpers
# ---------------------------------------------------------------------------


def _apply_group(client: MCPClient, group: GroupInfo, parent_id: int) -> None:
    """Create a group in MCP and recursively add its children."""
    result = client.add_group(parent_id=parent_id, caption=group.caption)
    group_id = int(result["id"])
    logger.debug("Added group '{}' id={}", group.caption, group_id)

    for child in group.children:
        if isinstance(child, GroupInfo):
            _apply_group(client, child, parent_id=group_id)
        elif isinstance(child, LayerInfo):
            _apply_layer(client, child, group_id=group_id)


def _apply_layer(client: MCPClient, layer: LayerInfo, group_id: int) -> None:
    """Create a layer in MCP and add all its fills."""
    result = client.add_layer(group_id=group_id)
    layer_id = int(result["id"])
    logger.debug("Added layer '{}' id={}", layer.caption, layer_id)

    for fill in layer.fills:
        _apply_fill(client, fill, layer_id=layer_id)


def _apply_fill(client: MCPClient, fill: FillNode, layer_id: int) -> None:
    """Add a fill to a layer and apply all its numeric parameters.

    Passes parameters both during creation (``add_fill``) and via a
    subsequent ``set_fill_params`` call, ensuring the server picks up
    any params it ignores during initial creation.
    """
    params = fill.params

    init_params = _fill_params_to_dict(params)

    result = client.add_fill(
        layer_id=layer_id,
        fill_type=params.fill_type,
        color=params.color,
        params=init_params,
    )
    fill_id = int(result["id"])
    logger.debug("Added fill '{}' type={} id={}", fill.caption, params.fill_type, fill_id)

    # Re-apply via set_fill_params: some servers only honour params set this way
    if init_params:
        client.set_fill_params(fill_id, **init_params)


def _fill_params_to_dict(params: FillParams) -> dict[str, object]:
    """Extract numeric values from FillParams, translated to MCP parameter names.

    Reads each field listed in :data:`PARSER_TO_MCP_PARAMS`, translates the
    field name to the MCP server's expected key, and includes the colour.

    Args:
        params: Fill parameters to convert.

    Returns:
        Dict of MCP parameter names to values.
    """
    result: dict[str, object] = {}
    for field_name, mcp_name in PARSER_TO_MCP_PARAMS.items():
        value = getattr(params, field_name, None)
        if value is not None:
            result[mcp_name] = value
    # Include color_mode for static-colour fills
    if params.color:
        result["color"] = params.color
        result["color_mode"] = 2  # static colour
    return result


# ---------------------------------------------------------------------------
# Internal: interpolation primitives
# ---------------------------------------------------------------------------


def _lerp(a: float, b: float, t: float) -> float:
    """Linear interpolation between two floats.

    Args:
        a: Start value.
        b: End value.
        t: Interpolation factor in ``[0, 1]``.

    Returns:
        Interpolated value.
    """
    return a + (b - a) * t


def _lerp_color(a: str, b: str, t: float) -> str:
    """Interpolate between two hex colour strings (``#RRGGBB`` or ``#RRGGBBAA``).

    Parses each channel as an integer, linearly interpolates, and
    formats back to hex. Supports both 6-digit and 8-digit hex.

    Args:
        a: Start colour (e.g. ``"#ff0000"`` or ``"#ff0000ff"``).
        b: End colour.
        t: Interpolation factor in ``[0, 1]``.

    Returns:
        Interpolated hex colour string, matching the longer input format.
    """
    a_clean = a.lstrip("#")
    b_clean = b.lstrip("#")

    # Normalise to 8 digits (RRGGBBAA)
    has_alpha = len(a_clean) == _HEX_RGBA_LEN or len(b_clean) == _HEX_RGBA_LEN
    if len(a_clean) == _HEX_RGB_LEN:
        a_clean += "ff"
    if len(b_clean) == _HEX_RGB_LEN:
        b_clean += "ff"

    # Parse channels
    a_channels = [int(a_clean[i : i + 2], 16) for i in range(0, _HEX_RGBA_LEN, 2)]
    b_channels = [int(b_clean[i : i + 2], 16) for i in range(0, _HEX_RGBA_LEN, 2)]

    # Interpolate
    result_channels = [round(_lerp(ac, bc, t)) for ac, bc in zip(a_channels, b_channels, strict=True)]
    result_channels = [max(0, min(255, c)) for c in result_channels]

    if has_alpha:
        return "#{:02x}{:02x}{:02x}{:02x}".format(*result_channels)
    return "#{:02x}{:02x}{:02x}".format(*result_channels[:3])


def _interpolate_fill_params(a: FillParams, b: FillParams, t: float) -> FillParams:
    """Interpolate all numeric params between two FillParams.

    Numeric fields (listed in ``NUMERIC_PARAMS``) are linearly interpolated.
    The colour field is interpolated via hex RGB lerp. Non-numeric, non-colour
    fields are taken from style *a*.

    Args:
        a: Start fill params.
        b: End fill params.
        t: Interpolation factor in ``[0, 1]``.

    Returns:
        New :class:`~vexy_lines.types.FillParams` with interpolated values.
    """
    # Start with a deep copy of a
    result = copy.deepcopy(a)

    # Interpolate color
    if a.color and b.color:
        result.color = _lerp_color(a.color, b.color, t)

    # Interpolate numeric params
    for field_name in NUMERIC_PARAMS:
        val_a = getattr(a, field_name, None)
        val_b = getattr(b, field_name, None)
        if val_a is not None and val_b is not None:
            setattr(result, field_name, _lerp(float(val_a), float(val_b), t))
        # If one is None, keep a's value (already set by deepcopy)

    return result


def _interpolate_group(a: GroupInfo, b: GroupInfo, t: float) -> GroupInfo:
    """Recursively interpolate fills within matching group structures.

    Args:
        a: Start group.
        b: End group.
        t: Interpolation factor in ``[0, 1]``.

    Returns:
        New :class:`~vexy_lines.types.GroupInfo` with interpolated fills.
    """
    interpolated_children: list[GroupInfo | LayerInfo] = []
    for child_a, child_b in zip(a.children, b.children, strict=True):
        if isinstance(child_a, GroupInfo) and isinstance(child_b, GroupInfo):
            interpolated_children.append(_interpolate_group(child_a, child_b, t))
        elif isinstance(child_a, LayerInfo) and isinstance(child_b, LayerInfo):
            interpolated_children.append(_interpolate_layer(child_a, child_b, t))
        else:
            interpolated_children.append(copy.deepcopy(child_a))

    return GroupInfo(
        caption=a.caption,
        object_id=a.object_id,
        expanded=a.expanded,
        children=interpolated_children,
    )


def _interpolate_layer(a: LayerInfo, b: LayerInfo, t: float) -> LayerInfo:
    """Interpolate fills within matching layer structures.

    Args:
        a: Start layer.
        b: End layer.
        t: Interpolation factor in ``[0, 1]``.

    Returns:
        New :class:`~vexy_lines.types.LayerInfo` with interpolated fills.
    """
    interpolated_fills: list[FillNode] = []
    for fill_a, fill_b in zip(a.fills, b.fills, strict=True):
        interpolated_params = _interpolate_fill_params(fill_a.params, fill_b.params, t)
        interpolated_fills.append(
            FillNode(
                xml_tag=fill_a.xml_tag,
                caption=fill_a.caption,
                params=interpolated_params,
                object_id=None,
            )
        )

    return LayerInfo(
        caption=a.caption,
        object_id=a.object_id,
        visible=a.visible,
        mask=copy.deepcopy(a.mask),
        fills=interpolated_fills,
        grid_edges=copy.deepcopy(a.grid_edges),
    )


# ---------------------------------------------------------------------------
# Internal: structure comparison
# ---------------------------------------------------------------------------


def _compare_structure(a_nodes: list[GroupInfo | LayerInfo], b_nodes: list[GroupInfo | LayerInfo]) -> bool:
    """Recursively check if two node lists have matching structure.

    Matching means same count at each level, same node types (group vs layer),
    and for fills within layers, same count and matching fill types.

    Args:
        a_nodes: Nodes from style A.
        b_nodes: Nodes from style B.

    Returns:
        ``True`` if structures match, ``False`` otherwise.
    """
    if len(a_nodes) != len(b_nodes):
        return False

    for node_a, node_b in zip(a_nodes, b_nodes, strict=True):
        # Both must be the same type
        if type(node_a) is not type(node_b):
            return False

        if isinstance(node_a, GroupInfo) and isinstance(node_b, GroupInfo):
            if not _compare_structure(node_a.children, node_b.children):
                return False
        elif isinstance(node_a, LayerInfo) and isinstance(node_b, LayerInfo):
            if not _compare_fills(node_a.fills, node_b.fills):
                return False

    return True


def _compare_fills(a_fills: list[FillNode], b_fills: list[FillNode]) -> bool:
    """Check if two fill lists have matching types.

    Args:
        a_fills: Fills from layer A.
        b_fills: Fills from layer B.

    Returns:
        ``True`` if same count and each fill pair has matching ``fill_type``.
    """
    if len(a_fills) != len(b_fills):
        return False
    return all(fa.params.fill_type == fb.params.fill_type for fa, fb in zip(a_fills, b_fills, strict=True))


# ---------------------------------------------------------------------------
# Internal: document props interpolation
# ---------------------------------------------------------------------------


def _interpolate_doc_props(a: DocumentProps, b: DocumentProps, t: float) -> DocumentProps:
    """Interpolate numeric fields of DocumentProps.

    DPI is kept from style *a* (integer, not sensible to interpolate).
    Width/height in mm and thickness/interval ranges are interpolated.

    Args:
        a: Start document props.
        b: End document props.
        t: Interpolation factor in ``[0, 1]``.

    Returns:
        New :class:`~vexy_lines.types.DocumentProps` with interpolated numeric values.
    """
    return DocumentProps(
        width_mm=_lerp(a.width_mm, b.width_mm, t),
        height_mm=_lerp(a.height_mm, b.height_mm, t),
        dpi=a.dpi,  # DPI is an integer device setting; interpolating it is nonsensical
        thickness_min=_lerp(a.thickness_min, b.thickness_min, t),
        thickness_max=_lerp(a.thickness_max, b.thickness_max, t),
        interval_min=_lerp(a.interval_min, b.interval_min, t),
        interval_max=_lerp(a.interval_max, b.interval_max, t),
    )
