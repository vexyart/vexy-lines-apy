# this_file: src/vexy_lines_api/style.py
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
    """Parse a .lines file, trying vexy_lines.parse first, then vexy_lines_utils.parser.

    Args:
        path: Path to the .lines file.

    Returns:
        Parsed LinesDocument.
    """
    # Try the vexy-lines-py package first (it has a types module but parse lives elsewhere)
    try:
        from vexy_lines.types import LinesDocument as _LD  # noqa: F811

        # vexy-lines-py is a types-only package; parsing is in vexy-lines-utils
        _LD  # just check import works
    except ImportError:
        pass

    # The actual parse function lives in vexy_lines_utils.parser (vexy-lines-utils package)
    try:
        from vexy_lines_utils.parser import parse as _parse  # type: ignore[import-untyped]

        return _parse(path)  # type: ignore[return-value]
    except ImportError:
        pass

    msg = (
        "Cannot parse .lines files: install 'vexy-lines-utils' "
        "(pip install vexy-lines-utils) which provides the parser."
    )
    raise ImportError(msg)


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
# Application via MCP
# ---------------------------------------------------------------------------


def apply_style(
    client: MCPClient,
    style: Style,
    source_image: str | Path,
    *,
    dpi: int = 72,
) -> str:
    """Apply a style to a source image via MCP and return the SVG result.

    Creates a new document in Vexy Lines, replicates the style's
    group->layer->fill structure, sets all fill parameters, renders,
    and exports as SVG.

    Args:
        client: Connected :class:`~vexy_lines_api.client.MCPClient` instance.
        style: Style to apply.
        source_image: Path to the source image file.
        dpi: Document DPI (lower = faster, 72 good for video).

    Returns:
        SVG string of the rendered result.
    """
    source_image = Path(source_image).expanduser().resolve()
    logger.debug("Applying style (source={}) to image {} at {}dpi", style.source_path, source_image, dpi)

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

    # 2. Replicate the style tree
    for node in style.groups:
        if isinstance(node, GroupInfo):
            _apply_group(client, node, parent_id=root_id)
        elif isinstance(node, LayerInfo):
            _apply_layer(client, node, group_id=root_id)

    # 3. Render and wait
    logger.debug("Rendering...")
    client.render(timeout=60.0)

    # 4. Export SVG
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
    """Add a fill to a layer and set its parameters."""
    params = fill.params

    # Build the params dict for add_fill (initial creation)
    init_params = _fill_params_to_dict(params)

    result = client.add_fill(
        layer_id=layer_id,
        fill_type=params.fill_type,
        color=params.color,
        params=init_params,
    )
    fill_id = int(result["id"])
    logger.debug("Added fill '{}' type={} id={}", fill.caption, params.fill_type, fill_id)

    # Set any remaining params via set_fill_params for completeness
    if init_params:
        client.set_fill_params(fill_id, **init_params)


def _fill_params_to_dict(params: FillParams) -> dict[str, object]:
    """Extract all non-None numeric values from FillParams as a dict.

    Uses the ``NUMERIC_PARAMS`` list from the types module to identify which
    fields are numeric and should be passed to the MCP API.

    Args:
        params: Fill parameters to convert.

    Returns:
        Dict of parameter names to numeric values.
    """
    result: dict[str, object] = {}
    for field_name in NUMERIC_PARAMS:
        value = getattr(params, field_name, None)
        if value is not None:
            result[field_name] = value
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
        dpi=a.dpi,  # Keep a's DPI -- not meaningful to interpolate
        thickness_min=_lerp(a.thickness_min, b.thickness_min, t),
        thickness_max=_lerp(a.thickness_max, b.thickness_max, t),
        interval_min=_lerp(a.interval_min, b.interval_min, t),
        interval_max=_lerp(a.interval_max, b.interval_max, t),
    )
