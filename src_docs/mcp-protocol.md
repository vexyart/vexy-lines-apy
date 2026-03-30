# MCP Protocol

The Vexy Lines macOS/Windows app embeds an MCP server: a JSON-RPC 2.0 endpoint on `localhost:47384` over raw TCP with newline-delimited messages.

## Connection

The server listens on `127.0.0.1:47384` by default. Connect with a TCP socket and perform the MCP handshake before calling tools.

`MCPClient` handles all of this automatically:

```python
from vexy_lines_api import MCPClient

with MCPClient() as vl:
    # handshake done, ready to call tools
    info = vl.get_document_info()
```

### Handshake

1. Client sends `initialize` with protocol version `"2024-11-05"` and client info
2. Server responds with its capabilities and matching protocol version
3. Client sends `notifications/initialized` notification
4. Connection is ready for tool calls

### Wire format

Each message is a single line of JSON followed by `\n`:

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_document_info"}}
```

Responses follow the same format:

```json
{"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"{\"width_mm\":210,...}"}]}}
```

Tool results are wrapped in `content[0].text` which contains either JSON or plain text.

## The 25 tools

### Document (5 tools)

| Tool | Description | Args |
|------|-------------|------|
| `new_document` | Create a new document | `width`, `height`, `dpi`, `source_image` |
| `open_document` | Open a `.lines` file | `path` |
| `save_document` | Save current document | `path` (optional, for Save As) |
| `export_document` | Export to file | `path`, `format`, `dpi` |
| `get_document_info` | Get metadata | (none) |

### Structure (5 tools)

| Tool | Description | Args |
|------|-------------|------|
| `get_layer_tree` | Full document tree | (none) |
| `add_group` | Add a group | `parent_id`, `caption`, `source_image_path` |
| `add_layer` | Add a layer | `group_id` |
| `add_fill` | Add a fill to a layer | `layer_id`, `fill_type`, `color`, `params` |
| `delete_object` | Delete by ID | `object_id` |

### Fill parameters (2 tools)

| Tool | Description | Args |
|------|-------------|------|
| `get_fill_params` | Get fill params | `fill_id` |
| `set_fill_params` | Set fill params | `fill_id`, plus any param keys |

### Visual (7 tools)

| Tool | Description | Args |
|------|-------------|------|
| `set_source_image` | Set group source image | `image_path`, `group_id` |
| `set_caption` | Rename an object | `object_id`, `caption` |
| `set_visible` | Toggle visibility | `object_id`, `visible` |
| `set_layer_mask` | Set SVG vector mask | `layer_id`, `paths`, `mode` |
| `get_layer_mask` | Get mask data | `layer_id` |
| `transform_layer` | 2D transform | `layer_id`, `translate_x/y`, `rotate_deg`, `scale_x/y` |
| `set_layer_warp` | Perspective warp | `layer_id`, `top_left/right`, `bottom_left/right` |

### Control (6 tools)

| Tool | Description | Args |
|------|-------------|------|
| `render_all` | Trigger render | (none) |
| `get_render_status` | Check if rendering | (none) |
| `undo` | Undo last action | (none) |
| `redo` | Redo last action | (none) |
| `get_selection` | Get selected objects | (none) |
| `select_object` | Select by ID | `object_id` |

## Coordinates

All coordinates are in pixels at the document's DPI. Origin is top-left.

## Export formats

The `export_document` tool supports: `svg`, `pdf`, `png`, `jpg`, `eps`.

## Error handling

Server errors come back as JSON-RPC error objects:

```json
{"jsonrpc":"2.0","id":1,"error":{"code":-32000,"message":"No document open"}}
```

`MCPClient` raises `MCPError` with the message string.

## Bridge server

For Claude Desktop and Cursor, `vexy-lines-mcp` bridges stdio to TCP. It reads JSON-RPC from stdin, forwards to the TCP server, and writes responses to stdout. See the [CLI docs](https://github.com/vexyart/vexy-lines/tree/main/vexy-lines-cli) for setup instructions.
