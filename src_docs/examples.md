# Examples

## Open a document and inspect it

```python
from vexy_lines_api import MCPClient

with MCPClient() as vl:
    vl.open_document("artwork.lines")
    info = vl.get_document_info()
    print(f"{info.width_mm:.0f} x {info.height_mm:.0f} mm")
    print(f"Resolution: {info.resolution} dpi")
    print(f"Unsaved changes: {info.has_changes}")
```

## Walk the layer tree

```python
from vexy_lines_api import MCPClient

with MCPClient() as vl:
    vl.open_document("artwork.lines")
    root = vl.get_layer_tree()

    def print_tree(node, depth=0):
        indent = "  " * depth
        label = f"{node.type}: {node.caption}"
        if node.fill_type:
            label += f" [{node.fill_type}]"
        if not node.visible:
            label += " [hidden]"
        print(f"{indent}{label} (id={node.id})")
        for child in node.children:
            print_tree(child, depth + 1)

    print_tree(root)
```

## Change fill colours and re-export

```python
from vexy_lines_api import MCPClient

with MCPClient() as vl:
    vl.open_document("artwork.lines")
    root = vl.get_layer_tree()

    # Find all fill nodes and set them to blue
    def set_all_fills_blue(node):
        if node.type == "fill":
            vl.set_fill_params(node.id, color="#2563eb")
        for child in node.children:
            set_all_fills_blue(child)

    set_all_fills_blue(root)
    vl.render()
    vl.export_png("blue_version.png", dpi=150)
```

## Create a document from scratch

Build a complete document programmatically -- no `.lines` template needed.

```python
from vexy_lines_api import MCPClient

with MCPClient() as vl:
    doc = vl.new_document(source_image="photo.jpg", dpi=150)

    # Add a group, layer, and fill
    group = vl.add_group(parent_id=doc.root_id, caption="My Group")
    layer = vl.add_layer(group_id=group["id"])
    fill = vl.add_fill(
        layer_id=layer["id"],
        fill_type="linear",
        color="#333333",
        params={"interval": 2.0, "angle": 45},
    )

    vl.render()
    vl.export_svg("from_scratch.svg")
```

## Build a multi-layer composition

Combine multiple fill algorithms on separate layers with different colours.

```python
from vexy_lines_api import MCPClient

with MCPClient() as vl:
    doc = vl.new_document(source_image="portrait.jpg", dpi=150)

    group = vl.add_group(parent_id=doc.root_id, caption="Composition")

    # Layer 1: coarse linear fill for shadows
    layer1 = vl.add_layer(group_id=group["id"])
    vl.add_fill(
        layer_id=layer1["id"],
        fill_type="linear",
        color="#1a1a2e",
        params={"interval": 8.0, "angle": 45, "thickness": 2.0, "contrast": 0.9},
    )

    # Layer 2: fine circular fill for midtones
    layer2 = vl.add_layer(group_id=group["id"])
    vl.add_fill(
        layer_id=layer2["id"],
        fill_type="circular",
        color="#16213e",
        params={"interval": 3.0, "thickness": 0.8, "x0": 500, "y0": 400},
    )

    # Layer 3: halftone overlay for highlights
    layer3 = vl.add_layer(group_id=group["id"])
    vl.add_fill(
        layer_id=layer3["id"],
        fill_type="halftone",
        color="#e94560",
        params={"cell_size": 12.0, "rotation": 15, "break_down": 180},
    )

    vl.render(timeout=60)
    vl.export_svg("composition.svg")
    vl.export_png("composition.png", dpi=300)
```

## Style transfer: one style, many images

```python
from pathlib import Path
from vexy_lines_api import MCPClient, extract_style, apply_style

style = extract_style("artistic.lines")
photos = sorted(Path("./photos").glob("*.jpg"))
output = Path("./output")
output.mkdir(exist_ok=True)

with MCPClient() as vl:
    for photo in photos:
        svg = apply_style(vl, style, photo, dpi=72)
        (output / f"{photo.stem}.svg").write_text(svg)
        print(f"Done: {photo.name}")
```

## Style transfer with error handling and progress

```python
from pathlib import Path
from vexy_lines_api import MCPClient, MCPError, extract_style, apply_style

style = extract_style("artistic.lines")
photos = sorted(Path("./photos").glob("*.jpg"))
output = Path("./output")
output.mkdir(exist_ok=True)

failed: list[tuple[str, str]] = []

with MCPClient(timeout=60.0) as vl:
    for i, photo in enumerate(photos, 1):
        print(f"[{i}/{len(photos)}] Processing {photo.name}...")
        try:
            svg = apply_style(
                vl,
                style,
                photo,
                dpi=72,
                relative=True,
                render_timeout=120.0,
                save_lines_to=output / f"{photo.stem}.lines",
            )
            (output / f"{photo.stem}.svg").write_text(svg)
        except MCPError as e:
            print(f"  FAILED: {e.message}")
            failed.append((photo.name, e.message))
        except Exception as e:
            print(f"  FAILED: {e}")
            failed.append((photo.name, str(e)))

if failed:
    print(f"\n{len(failed)} failures:")
    for name, reason in failed:
        print(f"  {name}: {reason}")
else:
    print(f"\nAll {len(photos)} images processed successfully.")
```

## Style interpolation for animation

```python
from vexy_lines_api import MCPClient, extract_style, interpolate_style, apply_style

start = extract_style("soft.lines")
end = extract_style("bold.lines")

frames = [f"frame_{i:04d}.jpg" for i in range(60)]

with MCPClient() as vl:
    for i, frame in enumerate(frames):
        t = i / max(len(frames) - 1, 1)
        blended = interpolate_style(start, end, t)
        svg = apply_style(vl, blended, frame, dpi=72)
        with open(f"output/frame_{i:04d}.svg", "w") as f:
            f.write(svg)
```

## Export to multiple formats

```python
from vexy_lines_api import MCPClient

with MCPClient() as vl:
    vl.open_document("artwork.lines")
    vl.render()

    vl.export_svg("output.svg")
    vl.export_pdf("output.pdf")
    vl.export_png("output.png", dpi=300)
    vl.export_jpeg("output.jpg", dpi=150)
    vl.export_eps("output.eps")
```

## Get SVG as a string

```python
from vexy_lines_api import MCPClient

with MCPClient() as vl:
    vl.open_document("artwork.lines")
    vl.render()

    svg_text = vl.svg()
    print(f"SVG length: {len(svg_text)} chars")

    # Parse with svglab (requires: pip install vexy-lines-apy[svg])
    svg_obj = vl.svg_parsed()
```

## Error handling

```python
from vexy_lines_api import MCPClient, MCPError

try:
    with MCPClient(auto_launch=False, timeout=5.0) as vl:
        vl.get_document_info()
except MCPError as e:
    print(f"Could not connect: {e.message}")
```

## Low-level tool calls

Use `call_tool` to access any MCP tool directly, including tools not yet wrapped as typed methods.

```python
from vexy_lines_api import MCPClient

with MCPClient() as vl:
    vl.open_document("artwork.lines")

    # Direct tool call -- returns parsed JSON dict or raw string
    info = vl.call_tool("get_document_info")
    print(info)  # {'width_mm': 210.0, 'height_mm': 297.0, ...}

    # Tool call with arguments
    result = vl.call_tool("set_fill_params", {
        "id": 42,
        "params": {"color": "#ff0000", "interval": 20},
    })

    # List all available tools from the server
    tools = vl.call_tool("tools/list")
```

## Video processing with per-frame style transfer

```python
from vexy_lines_api import extract_style, process_video_with_style

style = extract_style("engraving.lines")

info = process_video_with_style(
    "input.mp4",
    "output.mp4",
    style=style,
    start_frame=0,
    end_frame=120,  # first 4 seconds at 30fps
    include_audio=True,
    relative=True,
    on_progress=lambda current, total: print(f"Frame {current}/{total}"),
)
print(f"Output: {info.width}x{info.height} @ {info.fps}fps, {info.total_frames} frames")
```

## Video with style interpolation

Transition between two styles across the video duration.

```python
from vexy_lines_api import extract_style, process_video_with_style

start_style = extract_style("watercolor.lines")
end_style = extract_style("woodcut.lines")

info = process_video_with_style(
    "clip.mp4",
    "transition.mp4",
    style=start_style,
    end_style=end_style,
    include_audio=True,
    relative=True,
    style_mode="auto",
)
```

## Using the JobFolder for resumable batch export

```python
from pathlib import Path
from vexy_lines_api import MCPClient, extract_style, apply_style
from vexy_lines_api.export import JobFolder

style = extract_style("reference.lines")
photos = sorted(Path("./photos").glob("*.jpg"))
output_dir = Path("./output")

jf = JobFolder(output_dir)

with MCPClient() as vl:
    existing = jf.existing_frames("styled", "svg")
    for i, photo in enumerate(photos):
        if i in existing:
            print(f"Skipping frame {i} (already exists)")
            continue

        svg_path = jf.frame_path("styled", i, "svg", pad_width=4)
        lines_path = jf.frame_path("styled", i, "lines", pad_width=4)

        svg = apply_style(vl, style, photo, dpi=72, save_lines_to=lines_path)
        svg_path.write_text(svg)
        print(f"Frame {i}: {svg_path.name}")

# When done, optionally clean up intermediates
# jf.cleanup()
```

## Export pipeline with callbacks

Use `process_export` for GUI/CLI integration with progress reporting.

```python
import threading
from vexy_lines_api.export import ExportRequest, process_export

request = ExportRequest(
    mode="images",
    input_paths=["photo1.jpg", "photo2.jpg", "photo3.jpg"],
    style_path="artistic.lines",
    end_style_path=None,
    output_path="./output/",
    format="SVG",
    size="1x",
    relative_style=True,
    style_mode="fast",
    force=False,
    cleanup=False,
)

abort = threading.Event()

process_export(
    request,
    abort_event=abort,
    on_progress=lambda cur, total, msg: print(f"[{cur}/{total}] {msg}"),
    on_complete=lambda msg: print(f"Done: {msg}"),
    on_error=lambda msg: print(f"Error: {msg}"),
)
```

## Style creation and consolidation

Create a styled document, make manual adjustments, then save with the consolidation pattern.

```python
from vexy_lines_api import MCPClient, extract_style
from vexy_lines_api.style import create_styled_document, save_and_consolidate

style = extract_style("base.lines")

with MCPClient() as vl:
    create_styled_document(vl, style, "photo.jpg", dpi=150, relative=True)

    # Tweak individual fills after the style is applied
    tree = vl.get_layer_tree()
    for child in tree.children:
        for layer in child.children:
            for fill in layer.children:
                if fill.fill_type == "linear":
                    vl.set_fill_params(fill.id, angle=90)

    # Save -> reopen -> render -> save (ensures file integrity)
    save_and_consolidate(vl, "custom.lines", render_timeout=120)
```

## Integration with Claude Desktop

When Vexy Lines is configured as an MCP server in Claude Desktop via the `vexylines-mcp` bridge, Claude can call the tools directly. The Python client and the bridge share the same underlying TCP connection to the app.

To use both simultaneously, ensure only one connection is active at a time:

```python
from vexy_lines_api import MCPClient

# Close any Claude Desktop MCP connection first (or use a separate document)
with MCPClient() as vl:
    vl.open_document("artwork.lines")
    # ... work with the document ...
    vl.save_document()
# Connection released -- Claude Desktop can reconnect
```

The bridge binary location depends on your platform. See [MCP Protocol](mcp-protocol.md#bridge-binary) for setup instructions.
