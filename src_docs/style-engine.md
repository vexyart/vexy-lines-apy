# Style Engine

The style engine extracts, applies, and interpolates fill structures from `.lines` files. It bridges the parser (`vexy-lines-py`) and the MCP client into a high-level workflow: take a style from one file, apply it to a different image.

## Concepts

A **Style** is a snapshot of the group/layer/fill tree and document properties from a `.lines` file. It contains everything needed to replicate the artistic look: which fill algorithms, in what order, with what parameters.

**Extraction** reads a `.lines` file and captures the tree. This is offline -- no app needed.

**Application** creates a new document in Vexy Lines via MCP, rebuilds the fill tree with matching parameters, renders, and exports SVG.

**Interpolation** blends two compatible styles at any ratio. Numeric parameters and hex colours interpolate linearly.

## Extract a style

```python
from vexy_lines_api import extract_style

style = extract_style("reference.lines")

# Inspect what's inside
for node in style.groups:
    print(node)

print(f"Source: {style.source_path}")
print(f"Canvas: {style.props.width_mm} x {style.props.height_mm} mm")
```

The returned `Style` is a deep copy -- modifying it won't affect the parsed document.

## Apply a style to an image

```python
from vexy_lines_api import MCPClient, extract_style, apply_style

style = extract_style("reference.lines")

with MCPClient() as vl:
    svg = apply_style(vl, style, "photo.jpg", dpi=72)

with open("result.svg", "w") as f:
    f.write(svg)
```

What happens behind the scenes:

1. Creates a new document with the source image
2. Walks the style tree and creates matching groups, layers, and fills via MCP
3. Sets all numeric fill parameters on each fill
4. Renders and waits for completion
5. Exports and returns the SVG string

### Relative mode

By default, `apply_style` uses absolute mode: fill parameters are applied as-is from the source style. If the target image is much larger or smaller than the original, the style may look different.

Relative mode scales spatial parameters (interval, thickness, base_width, dispersion, vert_disp) to match the target document size:

```python
svg = apply_style(vl, style, "large_photo.jpg", dpi=72, relative=True)
```

The scale factor is the geometric mean of the width and height ratios between source and target dimensions. Non-spatial parameters (angles, brightness thresholds, ratios) stay unchanged.

## Interpolate two styles

Blend two styles to create smooth transitions. Both styles must be compatible -- same tree structure, same fill types at each position.

```python
from vexy_lines_api import extract_style, interpolate_style, styles_compatible

a = extract_style("painterly.lines")
b = extract_style("technical.lines")

# Check compatibility first
if styles_compatible(a, b):
    mid = interpolate_style(a, b, t=0.5)  # halfway blend
```

The `t` parameter controls the mix:

| `t` value | Result |
|-----------|--------|
| `0.0` | Identical to style A |
| `0.25` | 75% A, 25% B |
| `0.5` | Halfway between A and B |
| `1.0` | Identical to style B |

### What interpolates

- **Numeric fill params**: interval, angle, thickness, smoothness, uplimit, downlimit, multiplier, base_width, dispersion, shear -- all linearly interpolated
- **Colours**: hex RGB channels interpolated independently
- **Document props**: width, height, thickness/interval ranges interpolated; DPI kept from style A (integer device setting)

### What doesn't interpolate

- Fill types (must match)
- Tree structure (must match)
- Captions, visibility, masks, grid edges (taken from style A)

## Compatibility check

Two styles are compatible when they share the exact same structure:

- Same number of top-level nodes
- Same node types at each position (group vs layer)
- Within each group, same number and types of children (recursive)
- Within each layer, same number of fills with matching fill types

```python
from vexy_lines_api import styles_compatible

if not styles_compatible(a, b):
    print("Styles have different structures -- can't interpolate")
```

If you pass incompatible styles to `interpolate_style`, it logs a warning and returns a deep copy of style A unchanged.

## Animation workflow

Interpolation across a sequence of images creates smooth style transitions:

```python
from vexy_lines_api import MCPClient, extract_style, interpolate_style, apply_style

start = extract_style("start.lines")
end = extract_style("end.lines")
images = ["frame_001.jpg", "frame_002.jpg", "frame_003.jpg"]

with MCPClient() as vl:
    for i, img in enumerate(images):
        t = i / max(len(images) - 1, 1)
        style = interpolate_style(start, end, t)
        svg = apply_style(vl, style, img, dpi=72)
        with open(f"output_{i:03d}.svg", "w") as f:
            f.write(svg)
```

The CLI command `vexy-lines style-transfer --style start.lines --end-style end.lines` does this automatically.
