# API Reference

## MCPClient

Context-managed TCP client for the Vexy Lines MCP server. Speaks JSON-RPC 2.0 over newline-delimited TCP to the server embedded in the Vexy Lines desktop app.

```python
from vexy_lines_api import MCPClient

with MCPClient(host="127.0.0.1", port=47384, timeout=30.0, auto_launch=True) as vl:
    info = vl.get_document_info()
```

**Constructor:**

```python
MCPClient(
    host: str = "127.0.0.1",
    port: int = 47384,
    timeout: float = 30.0,
    *,
    auto_launch: bool = True,
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `host` | `str` | `"127.0.0.1"` | Server address |
| `port` | `int` | `47384` | Server TCP port |
| `timeout` | `float` | `30.0` | Socket timeout in seconds for all operations |
| `auto_launch` | `bool` | `True` | Launch the Vexy Lines app if connection fails |

### Connection lifecycle

1. **`__enter__`** calls `_connect()` then `_handshake()`.
2. **`_connect()`** opens a TCP socket. On failure, if `auto_launch=True`, launches the app and polls with exponential back-off (0.5 s initial, 1.2x growth, 2.0 s cap) for up to 30 seconds.
3. **`_handshake()`** sends `initialize` with protocol version `"2024-11-05"` and client info `{"name": "vexy-lines-apy", "version": "1.0.0"}`. Validates the server returns the same protocol version. Sends `notifications/initialized` notification.
4. **Tool calls** use `_send_request("tools/call", ...)` which assigns an auto-incrementing integer request ID.
5. **`__exit__`** shuts down and closes the socket.

### Auto-launch behaviour

When `auto_launch=True` and the initial connection fails:

- **macOS**: runs `open -a "Vexy Lines"` via subprocess.
- **Windows**: searches `C:\Program Files\Vexy Lines\`, `C:\Program Files (x86)\Vexy Lines\`, and `%LOCALAPPDATA%\Programs\Vexy Lines\` for `Vexy Lines.exe`. Raises `MCPError` if not found.
- **Other platforms**: raises `MCPError` (auto-launch unsupported).

After launching, polls the TCP port for up to 30 seconds before giving up.

---

### Document methods

#### `new_document(width, height, dpi, source_image) -> NewDocumentResult`

Create a new document. Width and height are inferred from the source image when omitted.

```python
def new_document(
    self,
    width: float | None = None,
    height: float | None = None,
    dpi: float = 300,
    source_image: str | None = None,
) -> NewDocumentResult
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `width` | `float \| None` | `None` | Width in pixels (inferred from source image if omitted) |
| `height` | `float \| None` | `None` | Height in pixels (inferred from source image if omitted) |
| `dpi` | `float` | `300` | Document resolution |
| `source_image` | `str \| None` | `None` | Path to source image file (resolved to absolute) |

Returns a [`NewDocumentResult`](#newdocumentresult) with the created document's metadata.

#### `open_document(path) -> str`

Open a `.lines` file. The path is resolved to absolute before sending.

```python
def open_document(self, path: str) -> str
```

Returns server status string.

#### `save_document(path=None) -> str`

Save the current document. Pass a path for Save As.

```python
def save_document(self, path: str | None = None) -> str
```

#### `export_document(path, dpi=None, format=None) -> str`

Export to file. Format is one of `"svg"`, `"pdf"`, `"png"`, `"jpg"`, `"eps"`.

```python
def export_document(
    self,
    path: str,
    dpi: int | None = None,
    format: str | None = None,
) -> str
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `path` | `str` | required | Output file path (resolved to absolute) |
| `dpi` | `int \| None` | `None` | Override document DPI for export |
| `format` | `str \| None` | `None` | `"svg"`, `"pdf"`, `"png"`, `"jpg"`, or `"eps"` |

#### `get_document_info() -> DocumentInfo`

Returns a [`DocumentInfo`](#documentinfo) with dimensions, DPI, units, and unsaved changes flag.

```python
def get_document_info(self) -> DocumentInfo
```

---

### Structure methods

#### `get_layer_tree() -> LayerNode`

Returns the full document tree as a recursive [`LayerNode`](#layernode). The root node has `type == "document"`.

```python
def get_layer_tree(self) -> LayerNode
```

#### `add_group(parent_id=None, caption=None, source_image_path=None) -> dict`

Add a group to the document.

```python
def add_group(
    self,
    parent_id: int | None = None,
    caption: str | None = None,
    source_image_path: str | None = None,
) -> dict[str, object]
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `parent_id` | `int \| None` | `None` | Parent object ID (defaults to document root) |
| `caption` | `str \| None` | `None` | Group display name |
| `source_image_path` | `str \| None` | `None` | Source image for the group |

Returns a dict containing `"id"` of the created group.

#### `add_layer(group_id) -> dict`

Add a layer to a group.

```python
def add_layer(self, group_id: int) -> dict[str, object]
```

Returns a dict containing `"id"` of the created layer.

#### `add_fill(layer_id, fill_type, color=None, params=None) -> dict`

Add a fill to a layer.

```python
def add_fill(
    self,
    layer_id: int,
    fill_type: str,
    color: str | None = None,
    params: dict[str, object] | None = None,
) -> dict[str, object]
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `layer_id` | `int` | required | Parent layer object ID |
| `fill_type` | `str` | required | One of `FILL_TYPES`: `"linear"`, `"wave"`, `"circular"`, `"radial"`, `"spiral"`, `"scribble"`, `"halftone"`, `"handmade"`, `"fractals"`, `"trace"` |
| `color` | `str \| None` | `None` | Hex colour string (`"#RRGGBB"` or `"#RRGGBBAA"`) |
| `params` | `dict \| None` | `None` | Fill parameters dict (see [FILL_TYPE_PARAMS](#fill_type_params)) |

Returns a dict containing `"id"` of the created fill.

#### `delete_object(object_id) -> str`

Delete any object by ID (group, layer, or fill).

```python
def delete_object(self, object_id: int) -> str
```

Note: the wire argument key is `"id"`, not `"object_id"`.

---

### Fill parameter methods

#### `get_fill_params(fill_id) -> dict`

Get all parameters of a fill as a dict. The wire argument key is `"id"`.

```python
def get_fill_params(self, fill_id: int) -> dict[str, object]
```

Returns a dict of parameter names to current values.

#### `set_fill_params(fill_id, **params) -> str`

Set fill parameters by keyword. The wire format wraps kwargs inside a `"params"` dict alongside `"id"`.

```python
def set_fill_params(self, fill_id: int, **params: object) -> str
```

```python
vl.set_fill_params(42, color="#ff0000", interval=3.0, angle=45)
```

All spatial values (interval, thickness, dispersion) are in **pixels**. The server converts internally to mm or points based on the document DPI. See [FILL_TYPE_PARAMS](#fill_type_params) for valid parameter names per fill type.

---

### Visual methods

#### `set_source_image(image_path, group_id=None) -> str`

Set the source image for a group.

```python
def set_source_image(self, image_path: str, group_id: int | None = None) -> str
```

#### `set_caption(object_id, caption) -> str`

Rename any object. Wire argument key is `"id"`.

```python
def set_caption(self, object_id: int, caption: str) -> str
```

#### `set_visible(object_id, visible) -> str`

Toggle visibility. The `visible` parameter is keyword-only.

```python
def set_visible(self, object_id: int, *, visible: bool) -> str
```

#### `set_layer_mask(layer_id, paths, mode="create") -> str`

Set an SVG vector mask on a layer.

```python
def set_layer_mask(
    self,
    layer_id: int,
    paths: list[str],
    mode: str = "create",
) -> str
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `layer_id` | `int` | required | Target layer object ID |
| `paths` | `list[str]` | required | SVG path data strings (e.g. `["M 0 0 L 100 100 Z"]`) |
| `mode` | `str` | `"create"` | `"create"` (replace), `"add"` (union), `"subtract"` (difference) |

#### `get_layer_mask(layer_id) -> dict`

Get mask data for a layer.

```python
def get_layer_mask(self, layer_id: int) -> dict[str, object]
```

#### `transform_layer(layer_id, ...) -> str`

Apply a 2D transform to a layer.

```python
def transform_layer(
    self,
    layer_id: int,
    translate_x: float = 0,
    translate_y: float = 0,
    rotate_deg: float = 0,
    scale_x: float = 1,
    scale_y: float = 1,
) -> str
```

All positional values are in pixels. Wire argument key for the layer is `"id"`.

#### `set_layer_warp(layer_id, top_left, top_right, bottom_right, bottom_left) -> str`

Set perspective warp corners. Each corner is `[x, y]` in pixels. Wire argument key for the layer is `"id"`.

```python
def set_layer_warp(
    self,
    layer_id: int,
    top_left: list[float],
    top_right: list[float],
    bottom_right: list[float],
    bottom_left: list[float],
) -> str
```

---

### Control methods

#### `render(timeout=120.0) -> bool`

Render all layers and wait for completion. Combines `render_all()` + `wait_for_render()`.

```python
def render(self, timeout: float = 120.0) -> bool
```

Returns `True` when rendering completed, `False` if timed out. The app continues rendering in the background on timeout.

#### `render_all() -> str`

Trigger a render without waiting.

```python
def render_all(self) -> str
```

#### `wait_for_render(timeout=120.0, poll_interval=0.5) -> bool`

Poll until rendering finishes. Waits 0.5 s before the first check to let the render thread set its flag. Handles two scenarios:

- **Render started and finished**: detected by a `True -> False` transition in `get_render_status`.
- **Render already finished**: detected by four consecutive `False` readings without ever seeing `True`.

Adds a 0.5 s settling delay after detecting completion.

```python
def wait_for_render(self, timeout: float = 120.0, poll_interval: float = 0.5) -> bool
```

#### `get_render_status() -> RenderStatus`

Check whether the document is currently rendering.

```python
def get_render_status(self) -> RenderStatus
```

#### `undo() -> str` / `redo() -> str`

Undo or redo the last action.

#### `get_selection() -> dict | str`

Get the currently selected objects.

```python
def get_selection(self) -> dict[str, object] | str
```

#### `select_object(object_id) -> str`

Select an object by ID. Wire argument key is `"id"`.

```python
def select_object(self, object_id: int) -> str
```

---

### Export shortcuts

Convenience methods that call `export_document` with the appropriate format and return the resolved absolute path. The `dpi` parameter is keyword-only.

```python
def export_svg(self, path: str, *, dpi: int | None = None) -> Path
def export_pdf(self, path: str, *, dpi: int | None = None) -> Path
def export_png(self, path: str, *, dpi: int | None = None) -> Path
def export_jpeg(self, path: str, *, dpi: int | None = None) -> Path
def export_eps(self, path: str, *, dpi: int | None = None) -> Path
```

| Method | Format | Notes |
|--------|--------|-------|
| `export_svg(path, *, dpi=None)` | `"svg"` | Vector output |
| `export_pdf(path, *, dpi=None)` | `"pdf"` | Vector output |
| `export_png(path, *, dpi=None)` | `"png"` | Raster; lower DPI = faster export |
| `export_jpeg(path, *, dpi=None)` | `"jpg"` | Raster; lower DPI = faster export |
| `export_eps(path, *, dpi=None)` | `"eps"` | Encapsulated PostScript |

All return the resolved `Path` of the exported file.

#### `svg() -> str`

Export as SVG to a temporary file, read it, clean up, and return the SVG content as a string. Useful for piping into other tools or returning from an API.

```python
def svg(self) -> str
```

#### `svg_parsed() -> svglab.Svg`

Export as SVG and return a parsed `svglab.Svg` DOM object for traversal, editing, and rasterisation. Requires the `[svg]` extra (`pip install vexy-lines-apy[svg]`).

```python
def svg_parsed(self) -> object  # svglab.Svg at runtime
```

Raises `ImportError` if `svglab` is not installed.

---

### Low-level method

#### `call_tool(name, arguments=None) -> dict | str`

Call any MCP tool by name. The server wraps results in `content[0].text` which may be JSON or plain text. This method attempts JSON parse first, then falls back to returning the raw string.

```python
def call_tool(
    self,
    name: str,
    arguments: dict[str, object] | None = None,
) -> dict[str, object] | str
```

Use this to call tools not yet wrapped as typed methods, or to pass through raw arguments:

```python
# Direct tool call
result = vl.call_tool("get_document_info")

# With arguments
result = vl.call_tool("set_fill_params", {"id": 42, "params": {"color": "#ff0000"}})
```

---

## MCPError

Raised when the MCP server returns an error, connection fails, or protocol validation fails.

```python
class MCPError(Exception):
    message: str  # Human-readable error description
```

Common scenarios that raise `MCPError`:

| Cause | Example message |
|-------|-----------------|
| Connection refused | `Cannot connect to Vexy Lines MCP server at 127.0.0.1:47384: ...` |
| App not found (Windows) | `Vexy Lines not found. Install it or pass auto_launch=False...` |
| Unsupported platform | `Auto-launch not supported on linux...` |
| Server timeout | `Vexy Lines launched but MCP server not ready after 30s...` |
| Protocol mismatch | `Protocol mismatch: client=2024-11-05, server=...` |
| Server error | `MCP error -32000: No document open` |
| Connection closed | `Connection closed by server` |
| Invalid JSON | `Invalid JSON from server: ...` |
| Unexpected response | `Unexpected response from new_document: ...` |

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

Parse a `.lines` file and return a [`Style`](#style) containing the full group/layer/fill tree and document properties. Does not need the app -- works offline via the `vexy-lines-py` parser.

If `Pillow` is available, also extracts the pixel dimensions of the embedded source image into `style.source_image_size`.

```python
def extract_style(path: str | Path) -> Style
```

### `apply_style(client, style, source_image, ...) -> str`

Apply a style to a source image via MCP. Returns the SVG string.

```python
def apply_style(
    client: MCPClient,
    style: Style,
    source_image: str | Path,
    *,
    dpi: int = 72,
    relative: bool = False,
    render_timeout: float = 300.0,
    style_mode: Literal["auto", "fast", "slow"] = "fast",
    save_lines_to: str | Path | None = None,
) -> str
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `client` | `MCPClient` | required | Connected MCP client |
| `style` | `Style` | required | Style to apply |
| `source_image` | `str \| Path` | required | Path to source image |
| `dpi` | `int` | `72` | Document DPI (lower = faster; 72 good for video) |
| `relative` | `bool` | `False` | Scale spatial params to match target size |
| `render_timeout` | `float` | `300.0` | Max seconds to wait for render (Fractals at high res may need 120-300 s) |
| `style_mode` | `"auto" \| "fast" \| "slow"` | `"fast"` | Transfer strategy (see below) |
| `save_lines_to` | `str \| Path \| None` | `None` | Save intermediate `.lines` to this path |

**Style modes:**

| Mode | Strategy |
|------|----------|
| `"fast"` | XML source-image swap in the `.lines` file, then open in app. Preserves all fill params losslessly. If the source image has different dimensions, it is resized to match. Falls back to `"slow"` if the original `.lines` file is not available. |
| `"slow"` | Creates a new document via MCP, replicates the style tree by calling `add_group` / `add_layer` / `add_fill` / `set_fill_params` for every node. |
| `"auto"` | Uses `"fast"` if the target image pixel dimensions exactly match the embedded source image; otherwise `"slow"`. |

### `create_styled_document(client, style, source_image, ...) -> None`

Create a styled document in Vexy Lines without rendering or exporting. The document remains open in the app.

```python
def create_styled_document(
    client: MCPClient,
    style: Style,
    source_image: str | Path,
    *,
    dpi: int = 72,
    relative: bool = False,
) -> None
```

### `save_and_consolidate(client, path, ...) -> None`

Save, reopen, render, and save again. Improves `.lines` reliability after programmatic edits.

```python
def save_and_consolidate(
    client: MCPClient,
    path: str | Path,
    *,
    render_timeout: float = 300.0,
) -> None
```

Sequence: save -> reopen -> render -> save.

### `interpolate_style(a, b, t) -> Style`

Blend two compatible styles. `t=0` returns style A, `t=1` returns style B. Numeric fill parameters and hex colours interpolate linearly.

```python
def interpolate_style(a: Style, b: Style, t: float) -> Style
```

The `t` value is clamped to `[0.0, 1.0]`. If styles are incompatible, logs a warning and returns a deep copy of style A.

### `styles_compatible(a, b) -> bool`

Check whether two styles have matching tree structures. Required before interpolation.

```python
def styles_compatible(a: Style, b: Style) -> bool
```

---

## JobFolder

Persistent job folder for resumable export pipelines. Stores intermediate artifacts (`.lines`, `.svg`, frames) alongside the final output instead of using temporary directories that vanish on crash.

```python
from vexy_lines_api.export import JobFolder

jf = JobFolder("output.mp4", force=False)
print(jf.path)          # /absolute/path/to/output-vljob/
print(jf.output_stem)   # "output"
print(jf.src_path)      # /absolute/path/to/output-vljob/src/
```

**Constructor:**

```python
JobFolder(output_path: str | Path, *, force: bool = False)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `output_path` | `str \| Path` | required | Final output destination (file or directory) |
| `force` | `bool` | `False` | Delete existing job folder and start fresh |

**Path resolution:**

| Output type | Example output path | Computed job folder |
|-------------|--------------------|--------------------|
| File (`.mp4`, `.png`, `.jpg`, `.jpeg`, `.svg`, `.lines`) | `./out/video.mp4` | `./out/video-vljob/` |
| Directory | `./output/` | `./output-vljob/` |

Override with the `VEXY_LINES_JOB_FOLDER` environment variable.

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `path` | `Path` | The job folder directory |
| `output_stem` | `str` | Base name for naming intermediate files |
| `src_path` | `Path` | `{job_folder}/src/` directory for raw source frames |

**Methods:**

| Method | Signature | Returns | Description |
|--------|-----------|---------|-------------|
| `asset_path` | `(name: str, ext: str)` | `Path` | `{job_folder}/{name}.{ext}` |
| `frame_path` | `(name: str, frame_num: int, ext: str, *, pad_width: int)` | `Path` | `{job_folder}/{name}--{NNN}.{ext}` (zero-padded) |
| `frame_src_path` | `(name: str, frame_num: int, ext: str, *, pad_width: int)` | `Path` | `{job_folder}/src/src--{name}--{NNN}.{ext}` |
| `existing_frames` | `(name: str, ext: str)` | `set[int]` | Frame numbers already on disk |
| `existing_src_frames` | `(name: str, ext: str)` | `set[int]` | Source frame numbers already on disk |
| `copy_to_output` | `(src_name: str, dest: str \| Path)` | `Path` | Copy file from job folder to destination |
| `cleanup` | `()` | `None` | Delete the entire job folder |

---

## Export pipeline

### `process_export(request, ...) -> None`

Unified entry point for all export modes. Accepts either an `ExportRequest` dataclass or legacy positional arguments. Creates a `JobFolder`, dispatches to the appropriate processor, and optionally cleans up.

```python
def process_export(
    request: ExportRequest | str,
    input_paths: list[str] | None = None,
    style_path: str | None = None,
    end_style_path: str | None = None,
    output_path: str | None = None,
    fmt: str | None = None,
    size: str | None = None,
    *,
    audio: bool = True,
    frame_range: tuple[int, int] | None = None,
    relative_style: bool = False,
    force: bool = False,
    cleanup: bool = False,
    abort_event: threading.Event | None = None,
    on_progress: ProgressCallback | None = None,
    on_complete: CompleteCallback | None = None,
    on_error: ErrorCallback | None = None,
    on_preview: PreviewCallback | None = None,
) -> None
```

### `ExportRequest`

Canonical export request dataclass. Frozen (immutable after creation).

```python
@dataclass(frozen=True)
class ExportRequest:
    mode: ExportMode             # "lines" | "images" | "video"
    input_paths: list[str]
    style_path: str | None
    end_style_path: str | None
    output_path: str
    format: ExportFormat          # "LINES" | "SVG" | "PNG" | "JPG" | "MP4"
    size: str
    audio: bool = True
    frame_range: tuple[int, int] | None = None
    relative_style: bool = False
    style_mode: str = "fast"
    force: bool = False           # Force-clean job folder
    cleanup: bool = False         # Delete job folder after success
```

### Callback types

```python
ProgressCallback = Callable[[int, int, str], None]  # (current, total, message)
CompleteCallback = Callable[[str], None]             # (message)
ErrorCallback    = Callable[[str], None]             # (message)
PreviewCallback  = Callable[[bytes], None]           # (image_bytes)
```

### Export errors

| Exception | When raised |
|-----------|-------------|
| `ExportAborted` | Abort event was set during processing |
| `ExportValidationError` | Missing required fields in legacy argument mode |

---

## Video utilities

### `VideoInfo`

Frozen dataclass with video metadata.

| Field | Type | Description |
|-------|------|-------------|
| `width` | `int` | Frame width in pixels |
| `height` | `int` | Frame height in pixels |
| `fps` | `float` | Frames per second |
| `total_frames` | `int` | Total number of frames |
| `duration` | `float` | Duration in seconds |
| `has_audio` | `bool` | Whether the file contains an audio stream (requires `ffprobe`) |

### `probe(path) -> VideoInfo`

Read video metadata using OpenCV. Audio detection requires `ffprobe` on PATH.

```python
def probe(path: str) -> VideoInfo
```

### `svg_to_pil(svg_string, width, height) -> Image.Image`

Rasterise an SVG string to a PIL Image via `resvg_py`. Patches mm dimensions to px before rasterising. Falls back to a blank white image if `resvg_py` is not installed.

```python
def svg_to_pil(svg_string: str, width: int, height: int) -> Image.Image
```

### `process_video(input_path, output_path, ...) -> VideoInfo`

Re-encode a video with optional trim and scale. No style transfer.

```python
def process_video(
    input_path: str,
    output_path: str,
    *,
    start_frame: int = 0,
    end_frame: int | None = None,
    include_audio: bool = True,
    size_multiplier: int = 1,
    abort_event: Any = None,
    on_frame_image: Any = None,
) -> VideoInfo
```

### `process_video_with_style(input_path, output_path, ...) -> VideoInfo`

Per-frame style transfer. Each frame is: decoded -> saved as PNG -> styled via MCP -> rasterised via `resvg_py` -> encoded to output video. If `end_style` is provided, the style interpolates linearly across the frame range.

```python
def process_video_with_style(
    input_path: str,
    output_path: str,
    *,
    style: Style | None = None,
    end_style: Style | None = None,
    start_frame: int = 0,
    end_frame: int | None = None,
    include_audio: bool = True,
    size_multiplier: int = 1,
    relative: bool = False,
    style_mode: str = "auto",
    abort_event: Any = None,
    on_progress: Callable[[int, int], None] | None = None,
    on_frame_image: Callable[[Image.Image], None] | None = None,
) -> VideoInfo
```

---

## Media utilities

### `extract_preview_from_lines(filepath) -> bytes | None`

Extract the embedded preview or source image from a `.lines` file. Returns PNG or JPEG bytes, or `None` on failure.

### `extract_frame(video_path, frame_number=1) -> Image.Image | None`

Extract a single frame from a video file as a PIL Image. `frame_number` is 1-based.

### `fit_image_to_box(image, width, height) -> Image.Image`

Scale a PIL Image to fit within `width x height` while preserving aspect ratio. Composites RGBA onto white, returns RGB.

### `truncate_start(text, max_chars=60) -> str`

Truncate a string from the start, prepending `"..."` if truncated. For display in progress messages.

---

## Dataclasses

### `Style`

A transferable style extracted from a `.lines` document.

| Field | Type | Description |
|-------|------|-------------|
| `groups` | `list[GroupInfo \| LayerInfo]` | Top-level fill tree (from `vexy_lines.types`) |
| `props` | `DocumentProps` | Document dimensions, DPI, and thickness/interval ranges |
| `source_path` | `str \| None` | Path of the `.lines` file this style was extracted from |
| `source_image_size` | `tuple[int, int] \| None` | `(width, height)` of the embedded source image in pixels |

`StyleMode = Literal["auto", "fast", "slow"]` -- type alias for the `style_mode` parameter.

### `DocumentInfo`

MCP response from `get_document_info`.

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
| `fill_type` | `str \| None` | Fill algorithm name (only when `type == "fill"`) |
| `children` | `list[LayerNode]` | Child nodes (empty for fills) |

Class method `LayerNode.from_dict(d)` constructs the tree from nested dicts returned by the server.

### `NewDocumentResult`

MCP response from `new_document`.

| Field | Type | Description |
|-------|------|-------------|
| `status` | `str` | Status string (e.g. `"ok"`) |
| `width` | `float` | Width in pixels |
| `height` | `float` | Height in pixels |
| `dpi` | `float` | Resolution |
| `root_id` | `int` | Root node object ID (use as `parent_id` for `add_group`) |

### `RenderStatus`

MCP response from `get_render_status`.

| Field | Type | Description |
|-------|------|-------------|
| `rendering` | `bool` | Whether the document is currently rendering |

---

## Constants

### `FILL_TYPES`

```python
FILL_TYPES: frozenset[str] = frozenset({
    "linear", "wave", "circular", "radial", "spiral",
    "scribble", "halftone", "handmade", "fractals", "trace",
})
```

All valid fill type names accepted by `add_fill`.

### `FILL_TYPE_PARAMS`

```python
FILL_TYPE_PARAMS: dict[str, tuple[str, ...]]
```

Maps each fill type to its valid parameter names for `set_fill_params`. Derived from the C++ `paramsForType()` in `mcptools.cpp`.

**Base parameters** (shared by all stroke-based fills except `trace`):

`interval`, `angle`, `thickness`, `thickness_min`, `contrast`, `smoothness`, `break_up`, `break_down`, `dispersion`, `vdisp`, `color_mode`, `color_seg_len`, `color_seg_disp`

**Per-type additions:**

| Fill type | Extra parameters |
|-----------|-----------------|
| `linear` | (base only) |
| `wave` | `wave_height`, `wave_length`, `wave_fade`, `phase`, `curviness` |
| `circular` | `x0`, `y0` |
| `radial` | `x0`, `y0`, `r0`, `auto_distance`, `auto_randomize` |
| `spiral` | `x0`, `y0`, `direction_ccw` |
| `scribble` | `scribble_length`, `curviness`, `variety`, `complexity`, `rotation`, `scribble_pattern` |
| `halftone` | `cell_size`, `rotation`, `halftone_mode`, `rotation_mode`, `morphing`, `randomization` |
| `handmade` | `mode`, `parity_mode`, `is_filled`, `expand_lines`, `averaging` |
| `fractals` | `depth`, `kind` |
| `trace` | `smoothness`, `clearing_level`, `detailing`, `color_mode` (no base params) |

### Parameter name mapping (parser to MCP)

The `.lines` XML uses different attribute names from the MCP server. The style engine handles this translation internally via `PARSER_TO_MCP_PARAMS`:

| Parser field (XML) | MCP parameter | Notes |
|--------------------|---------------|-------|
| `interval` | `interval` | Line spacing, stored in points |
| `angle` | `angle` | Degrees |
| `multiplier` | `thickness` | Stroke width multiplier, stored in mm |
| `thickness_min` | `thickness_min` | Min stroke width, stored in mm |
| `smoothness` | `contrast` | Tone-mapping curve |
| `uplimit` | `break_up` | Upper brightness threshold |
| `downlimit` | `break_down` | Lower brightness threshold |
| `dispersion` | `dispersion` | Random offset, stored in points |

Note: XML `thick_gap` has no MCP equivalent and is not settable via the API.
