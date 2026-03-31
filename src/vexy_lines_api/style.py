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
from typing import TYPE_CHECKING, Literal

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
    "multiplier": "thickness",
    "thickness_min": "thickness_min",
    "smoothness": "contrast",
    "uplimit": "break_up",
    "downlimit": "break_down",
    "dispersion": "dispersion",
}
"""FillParams field name -> MCP ``set_fill_params`` key name.

The MCP server uses its own naming convention that differs from the XML
attribute names in ``.lines`` files.  Key non-obvious mappings:

- MCP ``thickness`` = XML ``multiplier`` (stroke width multiplier, stored in mm)
- MCP ``thickness_min`` = XML ``base_width`` (min stroke width, stored in mm)
- MCP ``contrast`` = XML ``smoothness`` (tone-mapping curve)
- MCP ``break_up`` / ``break_down`` = XML ``uplimit`` / ``downlimit``

Note: XML ``thick_gap`` has no MCP equivalent — it is not settable via the API.
"""

# Spatial params that should be scaled when applying a style in relative mode.
# These represent physical dimensions (mm, pixels) that change with document size.
# Excluded: angle, smoothness, uplimit, downlimit, multiplier, shear (ratios/degrees/thresholds).
SPATIAL_PARAMS: frozenset[str] = frozenset(
    {
        "interval",
        "multiplier",
        "thickness_min",
        "dispersion",
    }
)

# MCP parameter names that the server stores internally in mm.
# Server converts incoming pixel values: px * 25.4 / dpi → mm.
# To send correct values: mm_value * (source_dpi / 25.4) → pixels.
MCP_MM_PARAMS: frozenset[str] = frozenset({"thickness", "thickness_min"})

# MCP parameter names that the server stores internally in points.
# Server converts incoming pixel values: px * 72 / dpi → pt.
# To send correct values: pt_value * (source_dpi / 72.0) → pixels.
MCP_PT_PARAMS: frozenset[str] = frozenset({"interval", "dispersion"})


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
    source_image_size: tuple[int, int] | None = None  # NEW: (width, height) of embedded source image


StyleMode = Literal["auto", "fast", "slow"]
"""Style transfer mode: ``"auto"`` (default), ``"fast"`` (XML swap), ``"slow"`` (MCP copy)."""


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def _parse_lines_file(path: Path) -> LinesDocument:
    """Parse a .lines file, importing the parser lazily to keep startup fast."""
    from vexy_lines import parse  # noqa: PLC0415

    return parse(path)


def _get_image_dimensions_from_bytes(data: bytes) -> tuple[int, int] | None:
    """Return (width, height) for image bytes, or None on failure."""
    try:
        import io as _io  # noqa: PLC0415

        from PIL import Image as PILImage  # noqa: PLC0415

        with PILImage.open(_io.BytesIO(data)) as img:
            return img.size
    except Exception:
        return None


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

    # Get embedded source image pixel dimensions
    source_image_size = None
    if doc.source_image_data:
        source_image_size = _get_image_dimensions_from_bytes(doc.source_image_data)

    return Style(
        groups=copy.deepcopy(doc.groups),
        props=copy.deepcopy(doc.props),
        source_path=str(path),
        source_image_size=source_image_size,
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

    for field_name in SPATIAL_PARAMS:
        value = getattr(result, field_name, None)
        if value is not None:
            setattr(result, field_name, float(value) * scale)

    return result


def _compute_relative_scale(style: Style, target_width: float, target_height: float) -> float:
    """Compute a uniform scale factor from source style dimensions to target dimensions.

    Converts source dimensions from mm to pixels using the source DPI, then
    computes the geometric mean of the X and Y ratios against the target
    pixel dimensions.  Returns ``1.0`` when source dimensions are zero.

    Args:
        style: Source style containing original document dimensions and DPI.
        target_width: Target document width in pixels.
        target_height: Target document height in pixels.

    Returns:
        Geometric-mean scale factor, or ``1.0`` if source dimensions are zero.
    """
    src_dpi = style.props.dpi or 72
    src_w_px = style.props.width_mm * src_dpi / 25.4
    src_h_px = style.props.height_mm * src_dpi / 25.4
    if src_w_px <= 0 or src_h_px <= 0:
        logger.warning(
            "Source style has zero/negative dimensions ({}x{} mm); relative scaling disabled",
            style.props.width_mm,
            style.props.height_mm,
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

    scale_x = target_width / src_w_px
    scale_y = target_height / src_h_px
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
    render_timeout: float = 300.0,
    style_mode: Literal["auto", "fast", "slow"] = "fast",
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
        render_timeout: Maximum seconds to wait for the render to complete.
            Complex fills (Fractals) at high resolution may need 120-300s.

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

    # Style transfer mode selection:
    # - "fast": always use XML swap (resize new image to match old if needed)
    # - "slow": always create new doc + copy fills via MCP
    # - "auto": use fast if source image pixel dimensions match exactly, otherwise slow
    use_fast = False
    if style_mode == "fast":
        use_fast = True
    elif style_mode == "auto":
        use_fast = _dimensions_match(style, source_image)

    if use_fast:
        if not style.source_path or not Path(style.source_path).is_file():
            logger.warning("Fast mode requested but source .lines not available; falling back to slow")
        else:
            return _apply_style_fast(client, style, source_image, render_timeout=render_timeout)

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
    source_dpi = style.props.dpi or 72

    for node in effective_style.groups:
        if isinstance(node, GroupInfo):
            _apply_group(client, node, parent_id=root_id, source_dpi=source_dpi)
        elif isinstance(node, LayerInfo):
            _apply_layer(client, node, group_id=root_id, source_dpi=source_dpi)

    # 4. Render and wait
    logger.debug("Rendering...")
    client.render(timeout=render_timeout)

    # 5. Export SVG
    logger.debug("Exporting SVG")
    return client.svg()


def create_styled_document(
    client: MCPClient,
    style: Style,
    source_image: str | Path,
    *,
    dpi: int = 72,
    relative: bool = False,
) -> None:
    """Create a styled document in Vexy Lines without rendering or exporting.

    Replicates the style's group->layer->fill structure onto a new document
    with the given source image.  The document remains open in the app so
    the caller can save, render, or export as needed.

    For durable ``.lines`` output after edits, follow the consolidation pattern
    of save -> open -> render -> save. Use :func:`save_and_consolidate` to run
    that sequence in one call.

    Args:
        client: Connected :class:`~vexy_lines_api.client.MCPClient` instance.
        style: Style to apply.
        source_image: Path to the source image file.
        dpi: Document DPI.
        relative: If ``True``, scale spatial params to match target dimensions.
    """
    source_image = Path(source_image).expanduser().resolve()
    logger.debug("Creating styled document from {} at {}dpi", source_image, dpi)

    doc_result = client.new_document(source_image=str(source_image), dpi=dpi)
    root_id = doc_result.root_id

    effective_style = style
    if relative:
        scale = _compute_relative_scale(style, doc_result.width, doc_result.height)
        if scale != 1.0:
            effective_style = _scale_style(style, scale)

    source_dpi = style.props.dpi or 72

    for node in effective_style.groups:
        if isinstance(node, GroupInfo):
            _apply_group(client, node, parent_id=root_id, source_dpi=source_dpi)
        elif isinstance(node, LayerInfo):
            _apply_layer(client, node, group_id=root_id, source_dpi=source_dpi)


def save_and_consolidate(
    client: MCPClient,
    path: str | Path,
    *,
    render_timeout: float = 300.0,
) -> None:
    """Save a document, reopen it, render it, and save again.

    This helper improves ``.lines`` reliability after programmatic edits by
    forcing the Vexy Lines app to re-parse and re-render the saved file before
    the final write. The consolidation sequence is:

    1. Save current document state to disk.
    2. Reopen that saved file in Vexy Lines.
    3. Render the reopened document and wait for completion.
    4. Save again so the persisted file reflects the rendered state.

    Args:
        client: Connected :class:`~vexy_lines_api.client.MCPClient` instance.
        path: Destination ``.lines`` path.
        render_timeout: Maximum seconds to wait for the render after reopen.
    """
    resolved_path = Path(path).expanduser().resolve()
    resolved_path_str = str(resolved_path)

    logger.debug("Consolidation step 1/4: initial save to {}", resolved_path_str)
    client.save_document(resolved_path_str)

    logger.debug("Consolidation step 2/4: reopening {}", resolved_path_str)
    client.open_document(resolved_path_str)

    logger.debug("Consolidation step 3/4: rendering reopened document")
    render_ok = client.render(timeout=render_timeout)
    if not render_ok:
        logger.warning("Render timed out after {}s during consolidation of {}", render_timeout, resolved_path_str)

    logger.debug("Consolidation step 4/4: final save to {}", resolved_path_str)
    client.save_document(resolved_path_str)


# ---------------------------------------------------------------------------
# Internal: fast-path helpers
# ---------------------------------------------------------------------------


def _get_image_dimensions(path: Path) -> tuple[int, int] | None:
    """Return (width, height) in pixels for an image file, or None on failure."""
    try:
        from PIL import Image as PILImage  # noqa: PLC0415

        with PILImage.open(path) as img:
            return img.size
    except Exception:
        return None


def _dimensions_match(style: Style, target_image: Path) -> bool:
    """Check if target image has the same pixel dimensions as the style's embedded source image."""
    if not style.source_image_size:
        return False
    target_dims = _get_image_dimensions(target_image)
    if target_dims is None:
        return False
    return style.source_image_size[0] == target_dims[0] and style.source_image_size[1] == target_dims[1]


def _apply_style_fast(
    client: MCPClient,
    style: Style,
    source_image: Path,
    *,
    render_timeout: float = 300.0,
) -> str:
    """Fast path: swap source image at XML level, open modified .lines, render.

    If the new image has different dimensions from the original embedded source,
    it is resized to fit (downscaled if larger, padded with white if smaller).
    This preserves all fill parameters losslessly.
    """
    import tempfile  # noqa: PLC0415

    from vexy_lines.editor import replace_source_image  # noqa: PLC0415

    logger.info(
        "Fast path: XML source image swap in {} (source_image_size={})",
        style.source_path,
        style.source_image_size,
    )

    with tempfile.NamedTemporaryFile(suffix=".lines", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        replace_source_image(
            style.source_path,
            source_image,
            tmp_path,
            target_size=style.source_image_size,
        )
        client.open_document(str(tmp_path))
        client.render(timeout=render_timeout)
        return client.svg()
    finally:
        tmp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Internal: apply helpers
# ---------------------------------------------------------------------------


def _apply_group(client: MCPClient, group: GroupInfo, parent_id: int, source_dpi: int) -> None:
    """Create a group in MCP and recursively add its children."""
    result = client.add_group(parent_id=parent_id, caption=group.caption)
    group_id = int(result["id"])
    logger.debug("Added group '{}' id={}", group.caption, group_id)

    for child in group.children:
        if isinstance(child, GroupInfo):
            _apply_group(client, child, parent_id=group_id, source_dpi=source_dpi)
        elif isinstance(child, LayerInfo):
            _apply_layer(client, child, group_id=group_id, source_dpi=source_dpi)


def _apply_layer(client: MCPClient, layer: LayerInfo, group_id: int, source_dpi: int) -> None:
    """Create a layer in MCP and add all its fills."""
    result = client.add_layer(group_id=group_id)
    layer_id = int(result["id"])
    logger.debug("Added layer '{}' id={}", layer.caption, layer_id)

    for fill in layer.fills:
        _apply_fill(client, fill, layer_id=layer_id, source_dpi=source_dpi)


def _apply_fill(client: MCPClient, fill: FillNode, layer_id: int, source_dpi: int) -> None:
    """Add a fill to a layer and apply all its numeric parameters.

    Passes parameters both during creation (``add_fill``) and via a
    subsequent ``set_fill_params`` call, ensuring the server picks up
    any params it ignores during initial creation.
    """
    params = fill.params

    init_params = _fill_params_to_dict(params, source_dpi=source_dpi)

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


def _fill_params_to_dict(params: FillParams, source_dpi: int = 72) -> dict[str, object]:
    """Extract numeric values from FillParams, converted to MCP pixel units.

    Reads each field listed in :data:`PARSER_TO_MCP_PARAMS`, translates the
    field name to the MCP server's expected key, and converts spatial values
    from their storage units (mm or points) to pixels using *source_dpi*.

    The MCP server expects all spatial values in pixels and converts them
    internally: thickness params to mm (``px * 25.4 / dpi``), other spatial
    params to points (``px * 72 / dpi``).

    Args:
        params: Fill parameters to convert.
        source_dpi: DPI of the source ``.lines`` document.  Used to convert
            mm/pt values to the pixel values the MCP server expects.

    Returns:
        Dict of MCP parameter names to pixel-converted values.
    """
    mm_to_px = source_dpi / 25.4
    pt_to_px = source_dpi / 72.0

    result: dict[str, object] = {}
    for field_name, mcp_name in PARSER_TO_MCP_PARAMS.items():
        value = getattr(params, field_name, None)
        if value is not None:
            if mcp_name in MCP_MM_PARAMS:
                result[mcp_name] = float(value) * mm_to_px
            elif mcp_name in MCP_PT_PARAMS:
                result[mcp_name] = float(value) * pt_to_px
            else:
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
