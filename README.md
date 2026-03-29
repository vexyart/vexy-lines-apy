# vexy-lines-apy

Python bindings to the Vexy Lines MCP API and style engine.

Provides a typed TCP client for the Vexy Lines embedded MCP server (JSON-RPC 2.0 over newline-delimited TCP) and a style engine for extracting, applying, and interpolating fill structures from `.lines` files.

## Installation

```bash
pip install vexy-lines-apy
```

## Quick start

### Connect to Vexy Lines and query the document

```python
from vexy_lines_api import MCPClient

with MCPClient() as vl:
    info = vl.get_document_info()
    print(f"Document: {info.width_mm}x{info.height_mm}mm @ {info.resolution}dpi")

    tree = vl.get_layer_tree()
    print(f"Root node: {tree.caption} ({len(tree.children)} children)")

    vl.render()
    svg_path = vl.export_svg("output.svg")
    print(f"Exported to {svg_path}")
```

### Apply a style from a .lines file to an image

```python
from vexy_lines_api import MCPClient, extract_style, apply_style

style = extract_style("my_artwork.lines")

with MCPClient() as vl:
    svg = apply_style(vl, style, "photo.jpg", dpi=72)
    with open("styled.svg", "w") as f:
        f.write(svg)
```

### Interpolate between two styles

```python
from vexy_lines_api import extract_style, interpolate_style, styles_compatible

style_a = extract_style("bold.lines")
style_b = extract_style("thin.lines")

if styles_compatible(style_a, style_b):
    blended = interpolate_style(style_a, style_b, t=0.5)
```

## API reference

### Client

| Class / Function | Description |
|------------------|-------------|
| `MCPClient` | Context-managed TCP client for the Vexy Lines MCP server |
| `MCPError` | Exception for MCP communication or server errors |

#### MCPClient methods

**Document:** `new_document`, `open_document`, `save_document`, `export_document`, `get_document_info`

**Structure:** `get_layer_tree`, `add_group`, `add_layer`, `add_fill`, `delete_object`

**Fill params:** `get_fill_params`, `set_fill_params`

**Visual:** `set_source_image`, `set_caption`, `set_visible`, `set_layer_mask`, `get_layer_mask`, `transform_layer`, `set_layer_warp`

**Control:** `render_all`, `wait_for_render`, `get_render_status`, `render`, `undo`, `redo`, `get_selection`, `select_object`

**Export:** `export_svg`, `export_pdf`, `export_png`, `export_jpeg`, `export_eps`, `svg`, `svg_parsed`

### Types

| Type | Description |
|------|-------------|
| `DocumentInfo` | Document metadata (dimensions, resolution, units) |
| `LayerNode` | Recursive tree node for the document layer structure |
| `NewDocumentResult` | Result of creating a new document |
| `RenderStatus` | Current render state |

### Style engine

| Function | Description |
|----------|-------------|
| `extract_style(path)` | Extract fill style tree from a `.lines` file |
| `apply_style(client, style, image)` | Apply a style to an image via MCP, returns SVG |
| `interpolate_style(a, b, t)` | Blend two compatible styles at factor `t` |
| `styles_compatible(a, b)` | Check if two styles have matching tree structure |
| `Style` | Dataclass holding the group/layer/fill tree and document props |

## Dependencies

- [`vexy-lines-py`](../vexy-lines-py) — `.lines` file types and constants
- [`loguru`](https://github.com/Delgan/loguru) — structured logging
- [`typing-extensions`](https://pypi.org/project/typing-extensions/) — backported type hints

## License

MIT
