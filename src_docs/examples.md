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
        print(f"{indent}{label}")
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

    # Use with svglab (install separately: pip install svglab)
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
