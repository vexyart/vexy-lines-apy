# this_file: src/vexy_lines_api/types.py
"""Typed response dataclasses for MCP tool results.

These types represent the structured responses returned by the Vexy Lines
MCP server. They are used by :class:`~vexy_lines_api.client.MCPClient` to
provide typed return values instead of raw dicts.
"""

from __future__ import annotations

from dataclasses import dataclass, field


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
    """Recursive tree node representing a document/group/layer/fill.

    Used by ``get_layer_tree`` to return the full document structure.

    Attributes:
        id: Unique object identifier.
        type: Node type — ``"document"``, ``"group"``, ``"layer"``, or ``"fill"``.
        caption: User-visible name.
        visible: Whether the node is visible in the viewport.
        fill_type: Fill type string, only present when ``type == "fill"``.
        children: Child nodes forming the recursive tree.
    """

    id: int
    type: str  # "document", "group", "layer", "fill"
    caption: str
    visible: bool
    fill_type: str | None = None  # only present for type=="fill"
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
