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
print(f"DPI: {style.props.dpi}")
print(f"Source image size: {style.source_image_size}")  # (width, height) or None
```

The returned `Style` is a deep copy -- modifying it won't affect the parsed document.

### What's inside a Style

| Field | Type | Source |
|-------|------|--------|
| `groups` | `list[GroupInfo \| LayerInfo]` | Deep copy of the document's fill tree |
| `props` | `DocumentProps` | Canvas dimensions (mm), DPI, thickness/interval ranges |
| `source_path` | `str \| None` | Path of the `.lines` file |
| `source_image_size` | `tuple[int, int] \| None` | Pixel dimensions of the embedded source image (requires Pillow) |

`DocumentProps` fields:

| Field | Type | Description |
|-------|------|-------------|
| `width_mm` | `float` | Canvas width in millimetres |
| `height_mm` | `float` | Canvas height in millimetres |
| `dpi` | `int` | Document resolution (default 300) |
| `thickness_min` | `float` | Minimum allowed stroke thickness (mm) |
| `thickness_max` | `float` | Maximum allowed stroke thickness (mm) |
| `interval_min` | `float` | Minimum allowed line spacing (mm) |
| `interval_max` | `float` | Maximum allowed line spacing (mm) |

### Edge case: no embedded source image

If the `.lines` file has no embedded source image (`doc.source_image_data is None`), `source_image_size` will be `None`. This affects:

- **`style_mode="auto"`**: falls back to `"slow"` mode since dimension comparison is impossible.
- **`style_mode="fast"`**: falls back to `"slow"` if the original `.lines` file is not available on disk.
- **Relative scaling**: still works because it uses `DocumentProps` dimensions, not the source image size.

## Apply a style to an image

```python
from vexy_lines_api import MCPClient, extract_style, apply_style

style = extract_style("reference.lines")

with MCPClient() as vl:
    svg = apply_style(vl, style, "photo.jpg", dpi=72)

with open("result.svg", "w") as f:
    f.write(svg)
```

### Style transfer modes

The `style_mode` parameter controls how the style is transferred:

| Mode | Strategy | Speed | Fidelity |
|------|----------|-------|----------|
| `"fast"` | Copy the original `.lines` file, swap the source image at the XML level, open in app | Fastest | Lossless -- all fills preserved exactly |
| `"slow"` | Create a new document via MCP, replicate the tree with `add_group`/`add_layer`/`add_fill`/`set_fill_params` | Slower | Good -- but some params (like `thick_gap`) have no MCP equivalent |
| `"auto"` | Use `"fast"` if source and target images have identical pixel dimensions; otherwise `"slow"` | Varies | Best available |

**Fast mode internals:**

1. Copies the original `.lines` file to a temp location.
2. Calls `vexy_lines.editor.replace_source_image()` to swap the embedded source image at the XML level.
3. If the target image has different dimensions, resizes it to match the original (downscale if larger, pad with white if smaller).
4. Opens the modified `.lines` in the app via `open_document`.
5. Renders and exports SVG.

**Slow mode internals:**

1. Creates a new document with `new_document(source_image=..., dpi=...)`.
2. Walks the style tree and calls `add_group`, `add_layer`, `add_fill` for each node.
3. For each fill, converts parser parameters to MCP parameters (name mapping + unit conversion), then calls `set_fill_params`.
4. Renders with `render(timeout=render_timeout)`.
5. Exports SVG with `svg()`.

**Fallback behaviour:**

- Fast mode falls back to slow if `style.source_path` is `None` or the file no longer exists on disk.
- Auto mode falls back to slow if `style.source_image_size` is `None` or image dimensions don't match.

### Unit conversion in slow mode

The `.lines` XML stores fill parameters in physical units (mm, points). The MCP server expects pixels and converts internally. The style engine handles this translation:

| Parser field | MCP name | XML unit | Conversion to pixels |
|-------------|----------|----------|---------------------|
| `interval` | `interval` | points | `value * (source_dpi / 72.0)` |
| `multiplier` | `thickness` | mm | `value * (source_dpi / 25.4)` |
| `thickness_min` | `thickness_min` | mm | `value * (source_dpi / 25.4)` |
| `dispersion` | `dispersion` | points | `value * (source_dpi / 72.0)` |
| `angle` | `angle` | degrees | No conversion |
| `smoothness` | `contrast` | unitless | No conversion |
| `uplimit` | `break_up` | 0--255 | No conversion |
| `downlimit` | `break_down` | 0--255 | No conversion |

The `source_dpi` is taken from `style.props.dpi` (defaulting to 72 if zero).

### Render timeout

The `render_timeout` parameter (default 300 seconds) controls how long `apply_style` waits for rendering. Complex fills at high resolution may need the full 300 s:

| Fill type | Typical render time (1920x1080 @ 72 dpi) |
|-----------|------------------------------------------|
| `linear`, `wave` | < 2 s |
| `circular`, `radial`, `spiral` | 2--5 s |
| `scribble`, `halftone` | 5--15 s |
| `handmade` | 5--30 s |
| `fractals` (high depth) | 30--300 s |
| `trace` | 10--60 s |

For batch processing, 72 dpi is the recommended target -- it renders significantly faster than 150 or 300 dpi with minimal visual difference in SVG output.

### Relative mode

By default, `apply_style` uses absolute mode: fill parameters are applied as-is from the source style. If the target image is much larger or smaller than the original, the style may look different (e.g. line spacing appears tighter on a larger image).

Relative mode scales spatial parameters to match the target document size:

```python
svg = apply_style(vl, style, "large_photo.jpg", dpi=72, relative=True)
```

#### Scale factor calculation

The scale factor is the **geometric mean** of the width and height ratios between source and target pixel dimensions:

```
source_w_px = style.props.width_mm * source_dpi / 25.4
source_h_px = style.props.height_mm * source_dpi / 25.4

scale_x = target_width / source_w_px
scale_y = target_height / source_h_px

scale = sqrt(scale_x * scale_y)
```

The geometric mean preserves the style's visual density regardless of aspect ratio changes. A `scale` of `1.0` means the dimensions match and no scaling occurs.

#### Which parameters are spatial

These parameters are multiplied by the scale factor in relative mode:

| Parser field | MCP name | Why it's spatial |
|-------------|----------|------------------|
| `interval` | `interval` | Line spacing -- mm |
| `multiplier` | `thickness` | Stroke width multiplier -- mm |
| `thickness_min` | `thickness_min` | Minimum stroke width -- mm |
| `dispersion` | `dispersion` | Random perpendicular offset -- mm |

These parameters are **not** scaled (they are ratios, angles, or thresholds):

| Parser field | MCP name | Why it's not spatial |
|-------------|----------|---------------------|
| `angle` | `angle` | Degrees -- scale-independent |
| `smoothness` | `contrast` | Unitless curve parameter |
| `uplimit` | `break_up` | Brightness threshold (0--255) |
| `downlimit` | `break_down` | Brightness threshold (0--255) |
| `shear` | -- | Angle in degrees |

#### Edge case: very different aspect ratios

When the target image has a very different aspect ratio from the source (e.g. portrait source applied to landscape target), the geometric mean balances the scaling. However, angle-dependent fills like `linear` at `angle=0` may appear visually different because the stroke direction interacts with the image composition differently. This is inherent to the geometry -- no scaling can fix it.

#### Edge case: zero source dimensions

If `style.props.width_mm` or `height_mm` is zero (corrupt file or missing metadata), relative scaling is disabled and a warning is logged. Same if the target document has zero dimensions. The function returns `scale = 1.0` in both cases.

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

The value is clamped to `[0.0, 1.0]`.

### What interpolates

- **Numeric fill params** (`NUMERIC_PARAMS`): `interval`, `angle`, `thick_gap`, `smoothness`, `uplimit`, `downlimit`, `multiplier`, `base_width`, `dispersion`, `vert_disp`, `shear` -- all linearly interpolated
- **Colours**: hex RGB (and RGBA) channels interpolated independently, clamped to `[0, 255]`
- **Document props**: `width_mm`, `height_mm`, `thickness_min`, `thickness_max`, `interval_min`, `interval_max` -- linearly interpolated

### What doesn't interpolate

- **DPI**: kept from style A (integer device setting)
- **Fill types**: must match (no blending between algorithms)
- **Tree structure**: must match exactly
- **Captions, visibility, masks, grid edges**: taken from style A
- **`source_path`**: set to `None` on interpolated styles

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

## Preserving intermediates

### `save_lines_to` parameter

When `save_lines_to` is provided, the intermediate `.lines` file is saved during style transfer:

```python
svg = apply_style(client, style, "photo.jpg", save_lines_to="styled.lines")
# styled.lines is now a valid .lines file with the style applied to photo.jpg
```

The path this takes depends on the style mode:

| Mode | Save mechanism | When it happens |
|------|---------------|-----------------|
| `"fast"` | `shutil.copy2()` of the modified temp `.lines` file | Before opening in the app |
| `"slow"` | `client.save_document(path)` after building the tree | After render, before SVG export |

The fast path is a file copy (no MCP roundtrip), so it's faster and produces a `.lines` file that exactly matches what the app sees. The slow path calls `save_document`, which triggers the app's serialiser.

### Job folder integration

The [JobFolder](api-reference.md#jobfolder) system uses `save_lines_to` automatically. Every export saves the full artifact chain: `.lines` -> `.svg` -> final format (`.png`/`.jpg`/`.mp4`). This enables resume on crash (the pipeline skips frames whose artifacts already exist on disk).

## `create_styled_document` and `save_and_consolidate`

For workflows where you need more control than `apply_style` provides:

```python
from vexy_lines_api import MCPClient, extract_style
from vexy_lines_api.style import create_styled_document, save_and_consolidate

style = extract_style("reference.lines")

with MCPClient() as vl:
    # Create the document but don't render or export
    create_styled_document(vl, style, "photo.jpg", dpi=150)

    # Make additional manual adjustments
    vl.set_fill_params(42, angle=90)
    vl.set_visible(43, visible=False)

    # Save with consolidation (save -> reopen -> render -> save)
    save_and_consolidate(vl, "final.lines", render_timeout=300)
```

The consolidation sequence improves `.lines` reliability by forcing the app to re-parse and re-render the file before the final write.
