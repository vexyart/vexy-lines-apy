# this_file: src/vexy_lines_api/__init__.py
"""Python bindings to the Vexy Lines MCP API and style engine.

Provides a TCP client for the Vexy Lines embedded MCP server (JSON-RPC 2.0)
and a style engine for extracting, applying, and interpolating fill structures
from .lines files.

Usage::

    from vexy_lines_api import MCPClient

    with MCPClient() as vl:
        info = vl.get_document_info()
        tree = vl.get_layer_tree()
        vl.render()
"""

from __future__ import annotations

from vexy_lines_api.client import MCPClient, MCPError
from vexy_lines_api.style import Style, apply_style, extract_style, interpolate_style, styles_compatible
from vexy_lines_api.types import DocumentInfo, LayerNode, NewDocumentResult, RenderStatus

__all__ = [
    "MCPClient",
    "MCPError",
    "DocumentInfo",
    "LayerNode",
    "NewDocumentResult",
    "RenderStatus",
    "Style",
    "apply_style",
    "extract_style",
    "interpolate_style",
    "styles_compatible",
]
