# Installation

## Requirements

- Python 3.10 or newer
- The [Vexy Lines](https://vexy.art) desktop app (macOS or Windows) for all MCP operations

## Install from PyPI

```bash
pip install vexy-lines-apy
```

Or with `uv`:

```bash
uv add vexy-lines-apy
```

## Optional extras

### SVG manipulation

```bash
pip install "vexy-lines-apy[svg]"
```

Adds the `svglab` package, enabling `client.svg_parsed()` which returns a full SVG DOM object you can traverse, edit, and render.

## Runtime dependencies

| Package | Why |
|---------|-----|
| `vexy-lines-py` | `.lines` file parser and types |
| `loguru` | Structured debug logging |
| `typing-extensions` | Backported type hints for Python 3.10 |

## Verify the install

```python
from vexy_lines_api import MCPClient, extract_style
print("vexy-lines-apy is ready")
```

## The Vexy Lines app

The MCP client connects to a TCP server embedded in the Vexy Lines desktop app at `localhost:47384`. By default, `MCPClient` auto-launches the app if it isn't running.

To disable auto-launch:

```python
with MCPClient(auto_launch=False) as vl:
    ...
```

The style extraction functions (`extract_style`, `interpolate_style`, `styles_compatible`) work offline -- they parse `.lines` files directly and don't need the app. Only `apply_style` and `MCPClient` methods require a running app.

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
