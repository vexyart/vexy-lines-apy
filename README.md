# vexy-lines-apy

Python bindings to the [Vexy Lines](https://vexy.art) MCP API and style engine.

Connect to the Vexy Lines app over TCP, drive it programmatically — open documents, tweak fill parameters, render, export — and transfer or blend artistic styles between images without touching the GUI.

**Requires the Vexy Lines app** (macOS or Windows) for all MCP operations. The app auto-launches if it isn't running.

## Install

```bash
pip install vexy-lines-apy
```

For SVG object manipulation (`svg_parsed()`), install `svglab` separately:

```bash
pip install svglab
```

## Quick start

```python
from vexy_lines_api import MCPClient

with MCPClient() as vl:
    vl.open_document("photo.lines")

    info = vl.get_document_info()
    print(f"{info.width_mm:.0f} x {info.height_mm:.0f} mm @ {info.resolution} dpi")

    tree = vl.get_layer_tree()          # LayerNode tree
    vl.render()                          # render all layers, wait for completion
    vl.export_svg("output.svg")
```

`MCPClient()` connects to `localhost:47384`. If the app isn't open, it launches it and waits up to 30 seconds.

## Export formats

```python
with MCPClient() as vl:
    vl.open_document("art.lines")
    vl.render()

    vl.export_svg("out.svg")
    vl.export_pdf("out.pdf")
    vl.export_png("out.png", dpi=150)
    vl.export_jpeg("out.jpg")
    vl.export_eps("out.eps")

    # SVG as a string (useful for embedding or piping)
    svg_text = vl.svg()

    # SVG as a parsed svglab object (requires svglab)
    svg_obj = vl.svg_parsed()
```

## Edit fill parameters

```python
with MCPClient() as vl:
    vl.open_document("art.lines")
    tree = vl.get_layer_tree()

    # Find a fill node and change its colour
    fill_id = tree.children[0].children[0].children[0].id
    vl.set_fill_params(fill_id, color="#3a7bd5", opacity=0.9)

    vl.render()
    vl.export_png("result.png")
```

## Style engine

Extract the complete fill structure from a `.lines` file and apply it to any source image — no GUI required.

```python
from vexy_lines_api import MCPClient, extract_style, apply_style

style = extract_style("reference.lines")   # parse fill tree from file

with MCPClient() as vl:
    svg = apply_style(vl, style, "photo.jpg", dpi=72)

with open("result.svg", "w") as f:
    f.write(svg)
```

### Style interpolation

Blend two compatible styles at any mix ratio. Numeric fill parameters and colours interpolate smoothly.

```python
from vexy_lines_api import MCPClient, extract_style, interpolate_style, apply_style

painterly = extract_style("painterly.lines")
technical = extract_style("technical.lines")

mid = interpolate_style(painterly, technical, t=0.5)   # halfway blend

with MCPClient() as vl:
    svg = apply_style(vl, mid, "photo.jpg")
```

Two styles are compatible for interpolation when they share the same group/layer/fill structure with matching fill types. Check with `styles_compatible(a, b)` before blending.

## Job folder (resumable exports)

Long-running exports (especially video) save every intermediate artifact to a persistent **job folder** alongside the output. If a job is interrupted, re-running the same command resumes from where it left off.

```python
from vexy_lines_api.export import ExportRequest, process_export

request = ExportRequest(
    mode="video",
    input_paths=["clip.mp4"],
    style_path="look.lines",
    end_style_path=None,
    output_path="styled.mp4",
    format="MP4",
    size="1x",
)
process_export(request)
# Creates styled-vljob/ with all intermediates:
#   src/src--styled--001.png, styled--001.lines, styled--001.svg, styled--001.png, ...
```

Use `force=True` to discard previous progress and start fresh. Use `cleanup=True` to delete the job folder after the final output is written.

Override the job folder location with the `VEXY_LINES_JOB_FOLDER` environment variable.

## API reference

### Document

| Method | Description |
|---|---|
| `new_document(width, height, dpi, source_image)` | Create a new document |
| `open_document(path)` | Open a `.lines` file |
| `save_document(path)` | Save (or Save As) |
| `export_document(path, format, dpi)` | Export to svg/pdf/png/jpg/eps |
| `get_document_info()` | Returns `DocumentInfo` |

### Structure

| Method | Description |
|---|---|
| `get_layer_tree()` | Returns root `LayerNode` |
| `add_group(parent_id, caption)` | Add a group |
| `add_layer(group_id)` | Add a layer to a group |
| `add_fill(layer_id, fill_type, color, params)` | Add a fill to a layer |
| `delete_object(object_id)` | Delete any object |

### Fill parameters

| Method | Description |
|---|---|
| `get_fill_params(fill_id)` | Get all params as a dict |
| `set_fill_params(fill_id, **params)` | Set params by keyword |

### Visual

| Method | Description |
|---|---|
| `set_source_image(image_path, group_id)` | Set source image for a group |
| `set_caption(object_id, caption)` | Rename an object |
| `set_visible(object_id, visible)` | Toggle visibility |
| `set_layer_mask(layer_id, paths, mode)` | Set SVG vector mask |
| `get_layer_mask(layer_id)` | Get layer mask data |
| `transform_layer(layer_id, ...)` | Translate, rotate, scale |
| `set_layer_warp(layer_id, ...)` | Perspective warp corners |

### Control

| Method | Description |
|---|---|
| `render()` | Render all layers and wait |
| `render_all()` | Trigger render (no wait) |
| `wait_for_render(timeout)` | Poll until render completes |
| `get_render_status()` | Returns `RenderStatus` |
| `undo()` / `redo()` | Undo/redo last action |
| `get_selection()` | Get selected objects |
| `select_object(object_id)` | Select by ID |

### Export shortcuts

| Method | Returns |
|---|---|
| `export_svg(path, dpi)` | Resolved `Path` |
| `export_pdf(path, dpi)` | Resolved `Path` |
| `export_png(path, dpi)` | Resolved `Path` |
| `export_jpeg(path, dpi)` | Resolved `Path` |
| `export_eps(path, dpi)` | Resolved `Path` |
| `svg()` | SVG content as `str` |
| `svg_parsed()` | `svglab.Svg` object (requires `svglab`) |

### Style engine

| Function | Description |
|---|---|
| `extract_style(path)` | Parse a `.lines` file into a `Style` |
| `apply_style(client, style, source_image, dpi, save_lines_to)` | Apply style to an image, return SVG string. Optionally save the intermediate `.lines` file. |
| `interpolate_style(a, b, t)` | Blend two styles at ratio `t` in [0, 1] |
| `styles_compatible(a, b)` | Check if two styles can be interpolated |
| `JobFolder(output_path, force)` | Persistent job folder for resumable exports |

### Types

`DocumentInfo`, `JobFolder`, `LayerNode`, `NewDocumentResult`, `RenderStatus`, `Style`

## Dependencies

- [`vexy-lines-py`](../vexy-lines-py) — `.lines` file parser and types
- [`loguru`](https://github.com/Delgan/loguru) — structured logging
- [`typing-extensions`](https://pypi.org/project/typing-extensions/) — backported type hints

## Full documentation

[Read the docs](https://vexyart.github.io/vexy-lines/vexy-lines-apy/) for the complete API reference, style engine guide, MCP protocol specification, and more examples.

## License

MIT
