# Installation

## Requirements

- Python 3.11 or newer
- The [Vexy Lines](https://vexy.art/lines/) desktop app (macOS or Windows) for all MCP operations

## Install from PyPI

```bash
pip install vexy-lines-apy
```

Or with `uv`:

```bash
uv add vexy-lines-apy
```

## Runtime dependencies

| Package | Version | Why |
|---------|---------|-----|
| `vexy-lines-py` | `>=0.1.0` | `.lines` file parser and types (`GroupInfo`, `LayerInfo`, `FillNode`, `FillParams`, `DocumentProps`) |
| `loguru` | `>=0.7.2` | Structured debug logging |
| `typing-extensions` | `>=4.0` | Backported type hints for Python 3.11 |
| `Pillow` | `>=10.0.0` | Image manipulation (source image dimensions, frame extraction, resizing) |
| `resvg-py` | `>=0.2.0` | SVG rasterisation for video frame pipeline |
| `opencv-python-headless` | `>=4.8.0` | Video decoding/encoding and frame extraction |
| `av` | `>=12.0.0` | Additional video container support |

### What works without the app

These functions work offline (no Vexy Lines app required):

- `extract_style()` -- parse `.lines` files
- `interpolate_style()` -- blend two styles
- `styles_compatible()` -- check style compatibility
- `probe()` -- read video metadata
- `svg_to_pil()` -- rasterise SVG strings
- `extract_preview_from_lines()` -- extract embedded images

These require a running Vexy Lines app:

- `MCPClient` and all its methods
- `apply_style()` -- style transfer via MCP
- `create_styled_document()` -- document creation via MCP
- `save_and_consolidate()` -- save/reopen/render cycle
- `process_video_with_style()` -- per-frame style transfer

## Optional extras

### SVG manipulation

```bash
pip install "vexy-lines-apy[svg]"
```

Adds the `svglab` package, enabling `client.svg_parsed()` which returns a full SVG DOM object you can traverse, edit, and render.

### External tools (optional, not Python packages)

| Tool | Used by | Purpose |
|------|---------|---------|
| `ffprobe` | `probe()` | Audio stream detection in video files |
| `ffmpeg` | `process_video()` | Audio stream merging in output videos |

Both are optional. Without them, `VideoInfo.has_audio` defaults to `False` and video output will have no audio track.

## Verify the install

```python
from vexy_lines_api import MCPClient, extract_style
print("vexy-lines-apy is ready")
```

To verify the MCP connection:

```python
from vexy_lines_api import MCPClient

with MCPClient() as vl:
    info = vl.get_document_info()
    print(f"Connected: {info.width_mm:.0f} x {info.height_mm:.0f} mm")
```

## The Vexy Lines app

The MCP client connects to a TCP server embedded in the Vexy Lines desktop app at `localhost:47384`. By default, `MCPClient` auto-launches the app if it isn't running.

To disable auto-launch:

```python
with MCPClient(auto_launch=False) as vl:
    ...
```

Auto-launch behaviour by platform:

| Platform | Mechanism |
|----------|-----------|
| macOS | `open -a "Vexy Lines"` |
| Windows | Searches standard install paths for `Vexy Lines.exe` |
| Linux | Not supported (raises `MCPError`) |

After launching, the client polls the TCP port for up to 30 seconds with exponential back-off before giving up.

## Development install

```bash
git clone https://github.com/vexyart/vexy-lines.git
cd vexy-lines/vexy-lines-apy
uv venv --python 3.12
uv pip install -e ".[dev]"
```

Run tests:

```bash
uvx hatch test
```

Run type checking:

```bash
uvx hatch run lint:typing
```

Run linting:

```bash
uvx hatch fmt
```
