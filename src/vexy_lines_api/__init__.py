# this_file: vexy-lines-apy/src/vexy_lines_api/__init__.py
"""Python bindings for the Vexy Lines MCP API and style engine.

Two entry points:

- :class:`MCPClient` — TCP client for the JSON-RPC 2.0 server embedded in the
  Vexy Lines macOS app (default port 47384). Exposes all 25 MCP tools as typed
  Python methods.

- Style engine (:func:`extract_style`, :func:`apply_style`,
  :func:`interpolate_style`) — extract a fill style from a ``.lines`` file,
  apply it to any source image, or blend two styles at an arbitrary mix ratio.

Basic document workflow::

    from vexy_lines_api import MCPClient

    with MCPClient() as vl:
        vl.open_document("photo.lines")
        info = vl.get_document_info()   # DocumentInfo(width_mm=..., ...)
        tree = vl.get_layer_tree()      # LayerNode tree
        vl.render()                     # render + wait for completion
        vl.export_svg("output.svg")

Style transfer workflow::

    from vexy_lines_api import MCPClient, extract_style, apply_style

    style = extract_style("reference.lines")   # parse fill tree from file

    with MCPClient() as vl:
        svg = apply_style(vl, style, "photo.jpg", dpi=72)

Style interpolation::

    from vexy_lines_api import extract_style, interpolate_style

    a = extract_style("painterly.lines")
    b = extract_style("technical.lines")
    mid = interpolate_style(a, b, t=0.5)   # halfway between both styles
"""

from __future__ import annotations

from vexy_lines_api.client import MCPClient, MCPError
from vexy_lines_api.export import ExportFormat, ExportMode, ExportRequest, process_export
from vexy_lines_api.media import extract_frame, extract_preview_from_lines, fit_image_to_box, truncate_start
from vexy_lines_api.style import (
    Style,
    StyleMode,
    apply_style,
    create_styled_document,
    extract_style,
    interpolate_style,
    save_and_consolidate,
    styles_compatible,
)
from vexy_lines_api.types import (
    FILL_TYPE_PARAMS,
    FILL_TYPES,
    DocumentInfo,
    LayerNode,
    NewDocumentResult,
    RenderStatus,
)
from vexy_lines_api.video import VideoInfo, svg_to_pil, probe, process_video, process_video_with_style

__all__ = [
    "FILL_TYPES",
    "FILL_TYPE_PARAMS",
    "DocumentInfo",
    "LayerNode",
    "MCPClient",
    "MCPError",
    "ExportFormat",
    "ExportMode",
    "ExportRequest",
    "NewDocumentResult",
    "RenderStatus",
    "Style",
    "StyleMode",
    "VideoInfo",
    "svg_to_pil",
    "apply_style",
    "create_styled_document",
    "extract_style",
    "extract_frame",
    "extract_preview_from_lines",
    "fit_image_to_box",
    "interpolate_style",
    "process_export",
    "save_and_consolidate",
    "probe",
    "process_video",
    "process_video_with_style",
    "styles_compatible",
    "truncate_start",
]
