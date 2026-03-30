
[Vexy Lines for Mac & Windows](https://vexy.art/lines/) | [Download](https://www.vexy.art/lines/#buy) | [Buy](https://www.vexy.art/lines/#buy) | [Batch GUI](https://vexy.dev/vexy-lines-run/) | [CLI/MCP](https://vexy.dev/vexy-lines-cli/) | **API** | [.lines format](https://vexy.dev/vexy-lines-py/)

[![Vexy Lines](https://i.vexy.art/vl/websiteart/vexy-lines-hero-poster.png)](https://www.vexy.art/lines/)

# vexy-lines-apy

Python bindings to the [Vexy Lines](https://vexy.art) MCP API and style engine.

Connect to the Vexy Lines app over TCP, drive it programmatically, and transfer artistic styles between images -- all from Python.

## Two entry points

**MCPClient** -- a context-managed TCP client that speaks JSON-RPC 2.0 to the Vexy Lines embedded server. Open documents, manipulate layers, tweak fill parameters, render, export. The app auto-launches if it isn't running.

**Style engine** -- extract a fill style from a `.lines` file, apply it to any source image, or blend two styles at any mix ratio. No GUI interaction needed.

## Quick start: MCP client

```python
from vexy_lines_api import MCPClient

with MCPClient() as vl:
    vl.open_document("photo.lines")
    info = vl.get_document_info()
    print(f"{info.width_mm:.0f} x {info.height_mm:.0f} mm @ {info.resolution} dpi")

    tree = vl.get_layer_tree()    # LayerNode tree
    vl.render()                    # render + wait for completion
    vl.export_svg("output.svg")
```

## Quick start: style transfer

```python
from vexy_lines_api import MCPClient, extract_style, apply_style

style = extract_style("reference.lines")

with MCPClient() as vl:
    svg = apply_style(vl, style, "photo.jpg", dpi=72)

with open("result.svg", "w") as f:
    f.write(svg)
```

## Quick start: style interpolation

```python
from vexy_lines_api import extract_style, interpolate_style

a = extract_style("painterly.lines")
b = extract_style("technical.lines")
mid = interpolate_style(a, b, t=0.5)   # halfway between both
```

## Next steps

- [Installation](installation.md) -- install options and optional extras
- [API Reference](api-reference.md) -- every class, method, and function
- [Style Engine](style-engine.md) -- how extraction, application, and interpolation work
- [MCP Protocol](mcp-protocol.md) -- the 25 tools in 5 groups
- [Examples](examples.md) -- real-world usage patterns
