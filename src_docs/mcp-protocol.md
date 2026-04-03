# MCP Protocol

The Vexy Lines macOS/Windows app embeds an MCP server: a JSON-RPC 2.0 endpoint on `localhost:47384` over raw TCP with newline-delimited messages. This document covers the wire protocol, all 25 tools, and the bridge binary for Claude Desktop/Cursor.

## Connection

The server listens on `127.0.0.1:47384` by default. Connect with a TCP socket and perform the MCP handshake before calling tools.

`MCPClient` handles all of this automatically:

```python
from vexy_lines_api import MCPClient

with MCPClient() as vl:
    # handshake done, ready to call tools
    info = vl.get_document_info()
```

### Handshake protocol

The MCP handshake follows the [Model Context Protocol](https://spec.modelcontextprotocol.io/) specification:

**Step 1 -- Client sends `initialize`:**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": "2024-11-05",
    "capabilities": {},
    "clientInfo": {"name": "vexy-lines-apy", "version": "1.0.0"}
  }
}
```

**Step 2 -- Server responds with capabilities:**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "2024-11-05",
    "capabilities": {"tools": {}},
    "serverInfo": {"name": "vexy-lines", "version": "..."}
  }
}
```

The client validates that the server's `protocolVersion` matches `"2024-11-05"`. A mismatch raises `MCPError`.

**Step 3 -- Client sends `notifications/initialized`:**

```json
{"jsonrpc": "2.0", "method": "notifications/initialized"}
```

This is a notification (no `id`, no response expected). The connection is now ready for tool calls.

### Wire format

Each message is a single line of JSON followed by `\n`:

```json
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_document_info"}}
```

Responses follow the same format:

```json
{"jsonrpc":"2.0","id":2,"result":{"content":[{"type":"text","text":"{\"width_mm\":210,...}"}]}}
```

Tool results are wrapped in `content[0].text` which contains either a JSON string or plain text. The `MCPClient.call_tool()` method attempts JSON parse first, falling back to the raw string.

### Calling a tool

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "set_fill_params",
    "arguments": {
      "id": 42,
      "params": {"color": "#ff0000", "interval": 20}
    }
  }
}
```

The `id` field is an auto-incrementing integer assigned by the client. The `name` field selects the tool. `arguments` contains tool-specific parameters.

### Listing available tools

After handshake, you can call `tools/list` to get the full tool catalog:

```json
{"jsonrpc":"2.0","id":2,"method":"tools/list"}
```

The response contains an `tools` array with name, description, and JSON Schema for each tool's parameters. `MCPClient` does not call this automatically -- it uses hardcoded method wrappers instead.

---

## Coordinates

All spatial coordinates are in **pixels at the document's DPI**. Origin is top-left corner. The server converts to internal units automatically:

| Internal unit | Conversion | Applies to |
|---------------|------------|------------|
| Millimetres | `px * 25.4 / dpi` | `thickness`, `thickness_min` |
| Points | `px * 72 / dpi` | `interval`, `dispersion` |
| Degrees | No conversion | `angle`, `rotate_deg` |
| Unitless | No conversion | `contrast`, `break_up`, `break_down`, ratios |

---

## The 25 tools

### Document tools (5)

#### `new_document`

Create a new document with optional source image.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `width` | `float` | no | inferred | Document width in pixels |
| `height` | `float` | no | inferred | Document height in pixels |
| `dpi` | `int` | no | `300` | Document resolution |
| `source_image` | `string` | no | -- | Absolute path to source image file |

When `source_image` is provided without `width`/`height`, the document dimensions are inferred from the image. The source image is embedded in the document.

**Response** (JSON): `{"status": "ok", "width": 1920, "height": 1080, "dpi": 300, "root_id": 1}`

#### `open_document`

Open a `.lines` file from disk.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | `string` | yes | Absolute path to `.lines` file |

**Response** (text): status string.

#### `save_document`

Save the current document. Omit `path` to save in-place.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | `string` | no | Absolute path for Save As |

**Response** (text): status string.

#### `export_document`

Export the document to a file.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `path` | `string` | yes | -- | Absolute output path |
| `format` | `string` | no | inferred from extension | `"svg"`, `"pdf"`, `"png"`, `"jpg"`, or `"eps"` |
| `dpi` | `int` | no | document DPI | Override resolution for export |

**Response** (text): status string.

#### `get_document_info`

Get metadata about the current document. No parameters.

**Response** (JSON):

```json
{
  "width_mm": 210.0,
  "height_mm": 297.0,
  "resolution": 300.0,
  "units": "mm",
  "has_changes": false
}
```

---

### Structure tools (5)

#### `get_layer_tree`

Get the full document tree. No parameters.

**Response** (JSON): recursive tree structure:

```json
{
  "id": 1,
  "type": "document",
  "caption": "My Document",
  "visible": true,
  "children": [
    {
      "id": 2,
      "type": "group",
      "caption": "Group 1",
      "visible": true,
      "children": [
        {
          "id": 3,
          "type": "layer",
          "caption": "Layer 1",
          "visible": true,
          "children": [
            {
              "id": 4,
              "type": "fill",
              "caption": "Linear Fill",
              "visible": true,
              "fill_type": "linear",
              "children": []
            }
          ]
        }
      ]
    }
  ]
}
```

Node types: `"document"` (root, one per document), `"group"`, `"layer"`, `"fill"` (leaf). Only `"fill"` nodes have `fill_type` set.

#### `add_group`

Add a new group to the document tree.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `parent_id` | `int` | no | document root | Parent object ID |
| `caption` | `string` | no | auto-generated | Group display name |
| `source_image_path` | `string` | no | -- | Source image for the group |

**Response** (JSON): `{"id": 5}` -- object ID of the created group.

#### `add_layer`

Add a new layer to a group.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `group_id` | `int` | yes | Parent group object ID |

**Response** (JSON): `{"id": 6}` -- object ID of the created layer.

#### `add_fill`

Add a fill algorithm to a layer.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `layer_id` | `int` | yes | -- | Parent layer object ID |
| `fill_type` | `string` | yes | -- | Algorithm name (see table below) |
| `color` | `string` | no | -- | Hex colour `"#RRGGBB"` or `"#RRGGBBAA"` |
| `params` | `object` | no | -- | Initial fill parameters dict |

Valid `fill_type` values:

| Value | Algorithm | Description |
|-------|-----------|-------------|
| `"linear"` | Linear strokes | Parallel straight lines at a given angle |
| `"wave"` | Sigmoid/wave strokes | Sinusoidal parallel lines |
| `"circular"` | Circular strokes | Concentric circles from a centre point |
| `"radial"` | Radial strokes | Lines radiating outward from a centre |
| `"spiral"` | Spiral strokes | Spiralling outward from a centre |
| `"scribble"` | Scribble strokes | Random hand-drawn-looking paths |
| `"halftone"` | Halftone dots | Dot/circle grid simulating halftone printing |
| `"handmade"` | Free-curve strokes | User-drawn or pattern-based curves |
| `"fractals"` | Peano/fractal curves | Space-filling fractal curves (slow to render at high depth) |
| `"trace"` | Traced area | Edge-tracing vectorisation of the source image |

**Response** (JSON): `{"id": 7}` -- object ID of the created fill.

#### `delete_object`

Delete any object (group, layer, or fill) from the document tree.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | `int` | yes | Object ID to delete |

**Response** (text): status string.

---

### Fill parameter tools (2)

#### `get_fill_params`

Get all current parameters of a fill.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | `int` | yes | Fill object ID |

**Response** (JSON): dict of parameter names to current values. The keys depend on the fill type (see [parameter reference](#fill-parameter-reference) below).

#### `set_fill_params`

Set one or more parameters on a fill.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | `int` | yes | Fill object ID |
| `params` | `object` | yes | Dict of parameter names to new values |

All spatial values must be in **pixels**. The server converts internally. Example wire message:

```json
{
  "jsonrpc": "2.0",
  "id": 5,
  "method": "tools/call",
  "params": {
    "name": "set_fill_params",
    "arguments": {
      "id": 42,
      "params": {
        "color": "#ff0000",
        "interval": 20,
        "angle": 45,
        "thickness": 3.5,
        "contrast": 0.8
      }
    }
  }
}
```

**Response** (text): status string.

---

### Visual tools (7)

#### `set_source_image`

Set the source image for a group.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `image_path` | `string` | yes | -- | Absolute path to image file |
| `group_id` | `int` | no | current group | Target group |

#### `set_caption`

Rename an object.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | `int` | yes | Object ID |
| `caption` | `string` | yes | New display name |

#### `set_visible`

Toggle object visibility.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | `int` | yes | Object ID |
| `visible` | `boolean` | yes | `true` to show, `false` to hide |

#### `set_layer_mask`

Set an SVG vector mask on a layer.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `layer_id` | `int` | yes | -- | Target layer |
| `paths` | `array[string]` | yes | -- | SVG path data strings |
| `mode` | `string` | no | `"create"` | `"create"` (replace), `"add"` (union), `"subtract"` (difference) |

SVG path data uses standard syntax: `"M 0 0 L 100 0 L 100 100 L 0 100 Z"`. Coordinates are in pixels at document DPI, origin top-left.

#### `get_layer_mask`

Get the current mask data for a layer.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `layer_id` | `int` | yes | Target layer |

**Response** (JSON): mask data dict.

#### `transform_layer`

Apply a 2D affine transform to a layer.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `id` | `int` | yes | -- | Target layer |
| `translate_x` | `float` | no | `0` | Horizontal translation in pixels |
| `translate_y` | `float` | no | `0` | Vertical translation in pixels |
| `rotate_deg` | `float` | no | `0` | Rotation angle in degrees |
| `scale_x` | `float` | no | `1` | Horizontal scale factor |
| `scale_y` | `float` | no | `1` | Vertical scale factor |

#### `set_layer_warp`

Set perspective warp on a layer by specifying four corner positions.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | `int` | yes | Target layer |
| `top_left` | `[float, float]` | yes | `[x, y]` coordinates in pixels |
| `top_right` | `[float, float]` | yes | `[x, y]` coordinates in pixels |
| `bottom_right` | `[float, float]` | yes | `[x, y]` coordinates in pixels |
| `bottom_left` | `[float, float]` | yes | `[x, y]` coordinates in pixels |

Example: warp a 1000x1000 layer into a trapezoid:

```python
vl.set_layer_warp(
    layer_id=3,
    top_left=[100, 0],
    top_right=[900, 0],
    bottom_right=[1000, 1000],
    bottom_left=[0, 1000],
)
```

---

### Control tools (6)

#### `render_all`

Trigger rendering of all layers. No parameters. Returns immediately -- use `get_render_status` to poll for completion.

**Response** (text): status string.

#### `get_render_status`

Check whether the document is currently rendering. No parameters.

**Response** (JSON): `{"rendering": true}` or `{"rendering": false}`.

Note: the rendering flag may not flip to `true` immediately after `render_all`. The Python client's `wait_for_render()` handles this by waiting 0.5 s before polling and detecting completion via consecutive `false` readings.

#### `undo`

Undo the last action. No parameters.

#### `redo`

Redo the last undone action. No parameters.

#### `get_selection`

Get the currently selected objects. No parameters.

**Response** (JSON): selection data dict or status string.

#### `select_object`

Select an object by ID.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | `int` | yes | Object to select |

---

## Fill parameter reference

### Base parameters (all stroke fills except `trace`)

| Parameter | Type | Unit | Description |
|-----------|------|------|-------------|
| `interval` | `float` | px (stored as pt) | Line spacing |
| `angle` | `float` | degrees | Stroke angle |
| `thickness` | `float` | px (stored as mm) | Stroke width multiplier |
| `thickness_min` | `float` | px (stored as mm) | Minimum stroke width |
| `contrast` | `float` | unitless | Tone-mapping curve steepness |
| `smoothness` | `float` | unitless | Curve smoothness |
| `break_up` | `float` | 0--255 | Upper brightness threshold |
| `break_down` | `float` | 0--255 | Lower brightness threshold |
| `dispersion` | `float` | px (stored as pt) | Random perpendicular offset |
| `vdisp` | `float` | px | Random vertical displacement |
| `color_mode` | `int` | enum | Colour mode (0=source, 2=static) |
| `color_seg_len` | `float` | px | Colour segment length |
| `color_seg_disp` | `float` | px | Colour segment dispersion |
| `color` | `string` | hex | Fill colour (`"#RRGGBB"` or `"#RRGGBBAA"`) |

### Wave extras

| Parameter | Type | Description |
|-----------|------|-------------|
| `wave_height` | `float` | Wave amplitude in pixels |
| `wave_length` | `float` | Wavelength in pixels |
| `wave_fade` | `float` | Fade factor |
| `phase` | `float` | Phase offset |
| `curviness` | `float` | Curve smoothness of wave |

### Circular extras

| Parameter | Type | Description |
|-----------|------|-------------|
| `x0` | `float` | Centre X in pixels |
| `y0` | `float` | Centre Y in pixels |

### Radial extras

| Parameter | Type | Description |
|-----------|------|-------------|
| `x0` | `float` | Centre X in pixels |
| `y0` | `float` | Centre Y in pixels |
| `r0` | `float` | Starting radius in pixels |
| `auto_distance` | `bool` | Auto-calculate line distance |
| `auto_randomize` | `bool` | Randomise ray distribution |

### Spiral extras

| Parameter | Type | Description |
|-----------|------|-------------|
| `x0` | `float` | Centre X in pixels |
| `y0` | `float` | Centre Y in pixels |
| `direction_ccw` | `bool` | Counter-clockwise direction |

### Scribble extras

| Parameter | Type | Description |
|-----------|------|-------------|
| `scribble_length` | `float` | Scribble path length |
| `curviness` | `float` | Path curvature |
| `variety` | `float` | Path variety |
| `complexity` | `float` | Path complexity |
| `rotation` | `float` | Pattern rotation in degrees |
| `scribble_pattern` | `int` | Pattern preset index |

### Halftone extras

| Parameter | Type | Description |
|-----------|------|-------------|
| `cell_size` | `float` | Cell size in pixels |
| `rotation` | `float` | Grid rotation in degrees |
| `halftone_mode` | `int` | Dot shape mode |
| `rotation_mode` | `int` | Rotation algorithm |
| `morphing` | `float` | Shape morphing factor |
| `randomization` | `float` | Random offset factor |

### Handmade extras

| Parameter | Type | Description |
|-----------|------|-------------|
| `mode` | `int` | Drawing mode preset |
| `parity_mode` | `int` | Parity handling |
| `is_filled` | `bool` | Fill closed paths |
| `expand_lines` | `bool` | Expand line widths |
| `averaging` | `float` | Smoothing factor |

### Fractals extras

| Parameter | Type | Description |
|-----------|------|-------------|
| `depth` | `int` | Recursion depth (higher = slower render) |
| `kind` | `int` | Fractal type preset |

### Trace parameters (standalone, no base params)

| Parameter | Type | Description |
|-----------|------|-------------|
| `smoothness` | `float` | Edge smoothness |
| `clearing_level` | `float` | Detail clearing threshold |
| `detailing` | `float` | Detail level |
| `color_mode` | `int` | Colour mode |

---

## Error handling

Server errors are returned as JSON-RPC error objects:

```json
{"jsonrpc": "2.0", "id": 3, "error": {"code": -32000, "message": "No document open"}}
```

`MCPClient` raises `MCPError` with the error code and message. Common error codes:

| Code | Meaning |
|------|---------|
| `-32000` | Application error (e.g. no document open, invalid object ID) |
| `-32600` | Invalid request |
| `-32601` | Method not found |
| `-32602` | Invalid params |
| `-32603` | Internal error |

---

## Bridge binary

For Claude Desktop and Cursor integration, the `vexylines-mcp` bridge binary converts between stdio and TCP. It reads JSON-RPC from stdin, forwards to the TCP server at `localhost:47384`, and writes responses to stdout.

### Claude Desktop setup

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "vexy-lines": {
      "command": "/path/to/vexylines-mcp"
    }
  }
}
```

The bridge binary is bundled with the Vexy Lines app. Typical locations:

- **macOS**: `/Applications/Vexy Lines.app/Contents/Resources/vexylines-mcp`
- **Windows**: `C:\Program Files\Vexy Lines\vexylines-mcp.exe`

### Cursor setup

Add to `.cursor/mcp.json` in your project:

```json
{
  "mcpServers": {
    "vexy-lines": {
      "command": "/path/to/vexylines-mcp"
    }
  }
}
```

The bridge handles the MCP handshake transparently. All 25 tools are exposed with their JSON Schema parameter definitions via `tools/list`.

See the [CLI docs](https://github.com/vexyart/vexy-lines/tree/main/vexy-lines-cli) for additional setup instructions and the `vexy-lines mcp-serve` command which provides an alternative Python-based bridge.
