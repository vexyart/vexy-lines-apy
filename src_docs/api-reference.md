# API Reference

## MCPClient

Context-managed TCP client for the Vexy Lines MCP server.

```python
from vexy_lines_api import MCPClient

with MCPClient(host="127.0.0.1", port=47384, timeout=30.0, auto_launch=True) as vl:
    info = vl.get_document_info()
```

**Constructor args:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `host` | `str` | `"127.0.0.1"` | Server address |
| `port` | `int` | `47384` | Server port |
| `timeout` | `float` | `30.0` | Socket timeout in seconds |
| `auto_launch` | `bool` | `True` | Launch the app on connection failure |

### Document methods

#### `new_document(width, height, dpi, source_image) -> NewDocumentResult`

Create a new document. Width and height are optional when a source image is provided.

#### `open_document(path) -> str`

Open a `.lines` file. Returns server status.

#### `save_document(path=None) -> str`

Save the document. Pass a path for Save As.

#### `export_document(path, dpi=None, format=None) -> str`

Export to file. Format: `"svg"`, `"pdf"`, `"png"`, `"jpg"`, `"eps"`.

#### `get_document_info() -> DocumentInfo`

Returns document metadata: dimensions, DPI, units, unsaved changes flag.

### Structure methods

#### `get_layer_tree() -> LayerNode`

Returns the full document tree as a recursive `LayerNode`.

#### `add_group(parent_id=None, caption=None, source_image_path=None) -> dict`

Add a group. Returns dict with `"id"` of the created group.

#### `add_layer(group_id) -> dict`

Add a layer to a group. Returns dict with `"id"`.

#### `add_fill(layer_id, fill_type, color=None, params=None) -> dict`

Add a fill to a layer. `fill_type` is e.g. `"linear"`, `"circular"`.

#### `delete_object(object_id) -> str`

Delete any object by ID.

### Fill parameter methods

#### `get_fill_params(fill_id) -> dict`

Get all parameters of a fill as a dict.

#### `set_fill_params(fill_id, **params) -> str`

Set fill parameters by keyword:

```python
vl.set_fill_params(42, color="#ff0000", interval=3.0, angle=45)
```

### Visual methods

#### `set_source_image(image_path, group_id=None) -> str`

Set the source image for a group.

#### `set_caption(object_id, caption) -> str`

Rename an object.

#### `set_visible(object_id, visible=True) -> str`

Toggle visibility.

#### `set_layer_mask(layer_id, paths, mode="create") -> str`

Set an SVG vector mask. Mode: `"create"`, `"add"`, `"subtract"`.

#### `get_layer_mask(layer_id) -> dict`

Get mask data for a layer.

#### `transform_layer(layer_id, translate_x=0, translate_y=0, rotate_deg=0, scale_x=1, scale_y=1) -> str`

Apply a 2D transform to a layer.

#### `set_layer_warp(layer_id, top_left, top_right, bottom_right, bottom_left) -> str`

Set perspective warp corners. Each corner is `[x, y]`.

### Control methods

#### `render(timeout=120.0) -> bool`

Render all layers and wait for completion. Combines `render_all()` + `wait_for_render()`.

#### `render_all() -> str`

Trigger a render without waiting.

#### `wait_for_render(timeout=120.0, poll_interval=0.5) -> bool`

Poll until rendering finishes.

#### `get_render_status() -> RenderStatus`

Check whether the document is currently rendering.

#### `undo() -> str` / `redo() -> str`

Undo or redo the last action.

#### `get_selection() -> dict | str`

Get the currently selected objects.

#### `select_object(object_id) -> str`

Select an object by ID.

### Export shortcuts

| Method | Returns |
|--------|---------|
| `export_svg(path, dpi=None)` | Resolved `Path` |
| `export_pdf(path, dpi=None)` | Resolved `Path` |
| `export_png(path, dpi=None)` | Resolved `Path` |
| `export_jpeg(path, dpi=None)` | Resolved `Path` |
| `export_eps(path, dpi=None)` | Resolved `Path` |
| `svg()` | SVG content as `str` |
| `svg_parsed()` | `svglab.Svg` object (requires `[svg]` extra) |

### Low-level method

#### `call_tool(name, arguments=None) -> dict | str`

Call any MCP tool by name. Returns parsed JSON dict or raw string.

---

## MCPError

Raised when the MCP server returns an error or communication fails.

```python
from vexy_lines_api import MCPClient, MCPError

try:
    with MCPClient(auto_launch=False) as vl:
        vl.get_document_info()
except MCPError as e:
    print(f"MCP failed: {e.message}")
```

---

## Style functions

### `extract_style(path) -> Style`

Parse a `.lines` file and return a `Style` containing the full group/layer/fill tree and document properties. Does not need the app.

### `apply_style(client, style, source_image, dpi=72, relative=False, save_lines_to=None) -> str`

Apply a style to a source image via MCP. Creates a new document, replicates the style tree, renders, and exports SVG.

When `relative=True`, spatial fill parameters (interval, thickness, base_width, dispersion) are scaled by the geometric mean of width/height ratios between the source style's document and the target. Keeps styles looking consistent across different image sizes.

When `save_lines_to` is provided (a file path), the intermediate `.lines` document is saved to that path after style transfer. Useful for preserving the full artifact chain or re-opening the result in the Vexy Lines app.

### `interpolate_style(a, b, t) -> Style`

Blend two compatible styles. `t=0` returns style A, `t=1` returns style B, `t=0.5` is the midpoint. Numeric fill parameters and hex colours interpolate linearly.

### `styles_compatible(a, b) -> bool`

Check whether two styles have matching tree structures (same groups, layers, fills, fill types). Required for interpolation.

---

## JobFolder

Persistent job folder for resumable export pipelines. Stores intermediate artifacts alongside the final output.

```python
from vexy_lines_api.export import JobFolder

jf = JobFolder("output.mp4", force=False)
print(jf.path)          # /path/to/output-vljob/
print(jf.output_stem)   # "output"
```

**Constructor args:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `output_path` | `str \| Path` | required | Final output destination (file or directory) |
| `force` | `bool` | `False` | Delete existing job folder and start fresh |

**Methods:**

| Method | Returns | Description |
|--------|---------|-------------|
| `asset_path(name, ext)` | `Path` | `{job_folder}/{name}.{ext}` |
| `frame_path(name, frame_num, ext, pad_width=...)` | `Path` | `{job_folder}/{name}--{NNN}.{ext}` |
| `frame_src_path(name, frame_num, ext, pad_width=...)` | `Path` | `{job_folder}/src/src--{name}--{NNN}.{ext}` |
| `existing_frames(name, ext)` | `set[int]` | Frame numbers already on disk |
| `existing_src_frames(name, ext)` | `set[int]` | Source frame numbers already on disk |
| `copy_to_output(src_name, dest)` | `Path` | Copy file from job folder to destination |
| `cleanup()` | `None` | Delete the entire job folder |

**Path resolution:**

| Output type | Output path | Job folder |
|-------------|-------------|------------|
| File (`.mp4`, `.png`, etc.) | `./out/video.mp4` | `./out/video-vljob/` |
| Directory | `./output/` | `./output-vljob/` |

Override with `VEXY_LINES_JOB_FOLDER` environment variable.

---

## Dataclasses

### `Style`

| Field | Type | Description |
|-------|------|-------------|
| `groups` | `list[GroupInfo \| LayerInfo]` | The fill tree |
| `props` | `DocumentProps` | Document dimensions and stroke limits |
| `source_path` | `str \| None` | Path of the source `.lines` file |

### `DocumentInfo`

| Field | Type | Description |
|-------|------|-------------|
| `width_mm` | `float` | Document width in mm |
| `height_mm` | `float` | Document height in mm |
| `resolution` | `float` | DPI |
| `units` | `str` | Measurement units (e.g. `"mm"`) |
| `has_changes` | `bool` | Unsaved changes flag |

### `LayerNode`

Recursive tree node from `get_layer_tree()`.

| Field | Type | Description |
|-------|------|-------------|
| `id` | `int` | Object ID for MCP calls |
| `type` | `str` | `"document"`, `"group"`, `"layer"`, or `"fill"` |
| `caption` | `str` | Display name |
| `visible` | `bool` | Visibility state |
| `fill_type` | `str \| None` | Fill algorithm (only when `type == "fill"`) |
| `children` | `list[LayerNode]` | Child nodes |

### `NewDocumentResult`

| Field | Type | Description |
|-------|------|-------------|
| `status` | `str` | Status string |
| `width` | `float` | Width in pixels |
| `height` | `float` | Height in pixels |
| `dpi` | `float` | Resolution |
| `root_id` | `int` | Root node object ID |

### `RenderStatus`

| Field | Type | Description |
|-------|------|-------------|
| `rendering` | `bool` | Whether the document is currently rendering |
