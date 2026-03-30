# this_file: vexy-lines-apy/src/vexy_lines_api/types.py
"""Response dataclasses for Vexy Lines MCP tool results.

:class:`MCPClient` deserialises raw JSON dicts into these typed objects.
Import them directly if you need to type-annotate code that works with
MCP responses::

    from vexy_lines_api.types import DocumentInfo, LayerNode
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# MCP fill type constants (must match the C++ server g_tmplTypes table)
# ---------------------------------------------------------------------------

FILL_TYPES: frozenset[str] = frozenset({
    "linear",
    "wave",
    "circular",
    "radial",
    "spiral",
    "scribble",
    "halftone",
    "handmade",
    "fractals",
    "trace",
})
"""All valid fill type names accepted by the ``add_fill`` MCP tool."""

# Common base parameters shared by all stroke-based fills (everything except trace).
_BASE_PARAMS: tuple[str, ...] = (
    "interval",
    "angle",
    "thickness",
    "thickness_min",
    "contrast",
    "smoothness",
    "break_up",
    "break_down",
    "dispersion",
    "vdisp",
    "color_mode",
    "color_seg_len",
    "color_seg_disp",
)

FILL_TYPE_PARAMS: dict[str, tuple[str, ...]] = {
    "linear": _BASE_PARAMS,
    "wave": (*_BASE_PARAMS, "wave_height", "wave_length", "wave_fade", "phase", "curviness"),
    "circular": (*_BASE_PARAMS, "x0", "y0"),
    "radial": (*_BASE_PARAMS, "x0", "y0", "r0", "auto_distance", "auto_randomize"),
    "spiral": (*_BASE_PARAMS, "x0", "y0", "direction_ccw"),
    "scribble": (*_BASE_PARAMS, "scribble_length", "curviness", "variety", "complexity", "rotation",
                 "scribble_pattern"),
    "halftone": (*_BASE_PARAMS, "cell_size", "rotation", "halftone_mode", "rotation_mode", "morphing",
                 "randomization"),
    "handmade": (*_BASE_PARAMS, "mode", "parity_mode", "is_filled", "expand_lines", "averaging"),
    "fractals": (*_BASE_PARAMS, "depth", "kind"),
    "trace": ("smoothness", "clearing_level", "detailing", "color_mode"),
}
"""Parameter names accepted by ``set_fill_params`` for each fill type.

Derived from the C++ ``paramsForType()`` function in ``mcptools.cpp``.
Spatial values (interval, thickness, dispersion, etc.) are in pixels.
"""


# ---------------------------------------------------------------------------
# Response dataclasses
# ---------------------------------------------------------------------------


@dataclass
class DocumentInfo:
    """Document metadata returned by ``get_document_info``.

    Attributes:
        width_mm: Document width in millimetres.
        height_mm: Document height in millimetres.
        resolution: Document resolution (DPI).
        units: Measurement units string (e.g. ``"mm"``).
        has_changes: Whether the document has unsaved changes.
    """

    width_mm: float
    height_mm: float
    resolution: float
    units: str
    has_changes: bool


@dataclass
class LayerNode:
    """Recursive tree node returned by ``get_layer_tree``.

    The tree mirrors the document structure: a single ``"document"`` root
    contains ``"group"`` nodes, which contain ``"layer"`` nodes, which contain
    ``"fill"`` leaf nodes.

    Attributes:
        id: Unique object identifier used in MCP tool calls.
        type: One of ``"document"``, ``"group"``, ``"layer"``, ``"fill"``.
        caption: User-visible name shown in the Vexy Lines layer panel.
        visible: Whether the node is currently visible in the viewport.
        fill_type: Fill algorithm name (e.g. ``"linear"``, ``"circular"``);
            set only when ``type == "fill"``, ``None`` otherwise.
        children: Child nodes; empty for ``"fill"`` leaves.
    """

    id: int
    type: str  # "document" | "group" | "layer" | "fill"
    caption: str
    visible: bool
    fill_type: str | None = None  # set only for type == "fill"
    children: list[LayerNode] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> LayerNode:
        """Build a LayerNode tree from a nested dict.

        Args:
            d: Dictionary with keys ``id``, ``type``, ``caption``, ``visible``,
               and optionally ``fill_type`` and ``children``.

        Returns:
            Fully constructed :class:`LayerNode` tree.
        """
        raw_children = d.get("children", [])
        children_list: list[dict[str, object]] = raw_children if isinstance(raw_children, list) else []
        children = [cls.from_dict(c) for c in children_list]  # type: ignore[arg-type]
        return cls(
            id=int(d.get("id", 0)),  # type: ignore[arg-type]
            type=str(d.get("type", "")),
            caption=str(d.get("caption", "")),
            visible=bool(d.get("visible", True)),
            fill_type=str(d["fill_type"]) if "fill_type" in d and d["fill_type"] is not None else None,
            children=children,
        )


@dataclass
class NewDocumentResult:
    """Result of creating a new document.

    Attributes:
        status: Status string (e.g. ``"ok"``).
        width: Document width in pixels.
        height: Document height in pixels.
        dpi: Document resolution.
        root_id: Object ID of the document root node.
    """

    status: str
    width: float
    height: float
    dpi: float
    root_id: int


@dataclass
class RenderStatus:
    """Current render state.

    Attributes:
        rendering: ``True`` if the document is currently being rendered.
    """

    rendering: bool
