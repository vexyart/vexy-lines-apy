
[Vexy Lines for Mac & Windows](https://vexy.art/lines/) | [Help & Docs](https://help.vexy.art/lines/) | [Batch GUI](https://vexy.dev/vexy-lines-run/) | [CLI/MCP](https://vexy.dev/vexy-lines-cli/) | **API** | [.lines format](https://vexy.dev/vexy-lines-py/)

# AI-assisted rename of layers & fills

Vexy Lines documents are built from [layers and fills](https://help.vexy.art/lines/articles/document-structure-overview/) that often keep generic captions — `Layer`, `Layer 2`, `Blended`, `Linear`, or nothing at all. The `vexy_lines_api.rename` package looks at what each fill *actually draws* and renames it to something descriptive (e.g. `car-on-road`, `top-sky-bridge`, `foreground-road-surface`), then names each layer from the fills it contains.

It works by rendering each fill in isolation, asking a vision-language model (VLM) what it sees, and writing a renamed copy of the `.lines` file. Nothing about the original artwork changes — only the captions.

## How it works

For a `.lines` file with *N* fills:

1. **Parse the structure** with [`vexy-lines-py`](https://vexy.dev/vexy-lines-py/) to enumerate every group, layer, and fill (with their object IDs).
2. **Render the full artwork** once (all fills, as authored) — this is the "context" image.
3. **For each fill**, render it *in isolation*: write a copy of the `.lines` file with only that fill (and its containing layer/groups) visible, open *that* file in Vexy Lines, render, and export.
4. **Build an "inspection image"** for the fill:
    - find the bounding box of the visible (non-white) content in the single-fill render;
    - composite the full artwork on top at 20% opacity for context;
    - draw a 5px-thick red rectangle around the bounding box.
5. **Ask a VLM** to describe, telegraphically in three words, *where* and *what* is inside the red rectangle.
6. **Slugify** the description with [`pathvalidate`](https://pypi.org/project/pathvalidate/) + [`python-slugify`](https://pypi.org/project/python-slugify/) into a filesystem-safe caption.
7. **Name each layer** by asking the model for a short name from its fills' descriptions, then slugify it.
8. **Write the renamed `.lines`** by rewriting only the `caption` attributes — every fill parameter, mask, mesh, and embedded image is preserved byte-for-byte.

!!! warning "Why visibility is baked into a file copy"
    Toggling visibility *live* over the MCP API (`set_visible`) does **not** change what the app exports — every per-fill render comes out identical. The renamer instead writes a copy of the `.lines` with `visible="0"` / `visible="1"` baked into the XML (via `vexy_lines.set_visibility`) and opens that file. The app honours the `visible` attribute on load, so each fill renders correctly in isolation.

## Quick start

```python
from vexy_lines_api import rename_lines

# Analyse, name, and write a renamed copy next to the input.
plan = rename_lines("road-12.lines")          # -> road-12-renamed.lines

for fill in plan.fills:
    print(f"fill {fill.object_id}: {fill.old_caption!r} -> {fill.new_caption!r}  ({fill.description})")
for layer in plan.layers:
    print(f"layer {layer.object_id}: {layer.old_caption!r} -> {layer.new_caption!r}")
```

Compute the plan without writing anything:

```python
plan = rename_lines("road-12.lines", dry_run=True)
print(plan.to_dict())          # JSON-serialisable summary
```

Reuse an existing MCP connection and choose a work directory for artifacts:

```python
from vexy_lines_api import MCPClient, rename_lines

with MCPClient() as vl:
    plan = rename_lines("art.lines", "art-named.lines", client=vl, work_dir="./rename-work")
```

## Configuring the model

The renamer talks to a single **OpenAI-compatible** `/v1` endpoint and uses two models: a *vision* model to describe each fill and a *text* model to name each layer (they can be the same). Everything is configured from four environment variables, read by `default_config()`:

| Setting | Environment variable | `VLMConfig` field |
|---|---|---|
| API base URL | `VEXY_LINES_LLM_API_URL` | `api_url` |
| API key | `VEXY_LINES_LLM_API_KEY` | `api_key` |
| Vision model | `VEXY_LINES_LLM_MODEL_VISION` | `model_vision` |
| Text model | `VEXY_LINES_VLM_MODEL` | `model` |

```bash
export VEXY_LINES_LLM_API_URL="http://127.0.0.1:1234/v1"
export VEXY_LINES_LLM_API_KEY="sk-..."          # any value for local servers
export VEXY_LINES_LLM_MODEL_VISION="my-vision-model"
export VEXY_LINES_VLM_MODEL="my-text-model"
```

Any OpenAI-compatible server works — a locally-served model, a hosted gateway, or the OpenAI API itself. Override per call with a `VLMConfig` (or `config_with_overrides`, which the CLI flags and GUI settings both use):

```python
from vexy_lines_api import rename_lines, VLMConfig

cfg = VLMConfig(
    api_url="http://127.0.0.1:1234/v1",
    api_key="not-needed",
    model_vision="my-vision-model",
    model="my-text-model",
)
plan = rename_lines("art.lines", config=cfg)
```

## Artifacts

With `save_artifacts=True` (the default), the work directory (`<stem>-rename/` beside the input, or `work_dir`) receives:

- `_full.png` — the all-fills render
- `fill_<id>_single.png` — each fill rendered in isolation
- `fill_<id>_inspect.png` — each inspection image (red box + faint context)
- `rename-plan.json` — the full plan

The bulky per-fill `.lines` copies are intermediate and are always deleted after rendering.

## API reference

### `rename_lines(lines_path, output_path=None, *, client=None, config=None, work_dir=None, dpi=72, dry_run=False, **plan_kwargs) -> RenamePlan`

Analyse, name, and (unless `dry_run`) write a renamed `.lines` file. Creates and tears down an `MCPClient` when `client` is `None`. `output_path` defaults to `<stem>-renamed.lines`.

### `build_rename_plan(lines_path, client, *, config=None, work_dir=None, dpi=72, render_timeout=600.0, render_lines_png=None, describe=None, suggest=None, save_artifacts=True) -> RenamePlan`

The core planner. The rendering, description, and layer-naming steps are injectable (`render_lines_png(client, path)`, `describe(png_bytes)`, `suggest(list_of_phrases)`) so the logic is testable without the app or a network.

### `apply_rename_plan(plan, output_path) -> int`

Write a renamed copy of the plan's source file; returns the number of objects renamed. Equivalent to `vexy_lines.rename_objects(plan.lines_path, output_path, plan.as_renames())`.

### Data classes

- **`RenamePlan`** — `lines_path`, `fills: list[FillRename]`, `layers: list[LayerRename]`, `full_image: bytes | None`. Helpers: `as_renames() -> dict[int, str]`, `to_dict()`.
- **`FillRename`** — `object_id`, `old_caption`, `fill_type`, `layer_id`, `description`, `new_caption`.
- **`LayerRename`** — `object_id`, `old_caption`, `fill_ids`, `description`, `new_caption`.

### VLM helpers (`vexy_lines_api.rename.vlm`)

- **`VLMConfig`** / **`default_config()`** — connection settings (see above).
- **`describe_region(image_bytes, *, config=None, prompt=...) -> str`** — three-word description of the red-boxed region.
- **`suggest_layer_name(fill_descriptions, *, config=None) -> str`** — short layer name from its fills.
- **`to_slug(text) -> str`** — `slugify(sanitize_filename(text))`, with a built-in fallback when the optional packages are absent.

### Inspection helpers (`vexy_lines_api.rename.inspection`)

- **`content_bbox(image, *, bg=(255,255,255), threshold=16)`** — bounding box of non-background content.
- **`make_inspection_image(single_fill, full_filled, *, overlay_opacity=0.2, rect_color=(255,0,0), rect_width=5) -> bytes`** — the composited inspection PNG.

### File editing (`vexy-lines-py`)

- **`vexy_lines.set_visibility(lines_path, output_path, {object_id: bool})`** — bake `visible=` into a copy.
- **`vexy_lines.rename_objects(lines_path, output_path, {object_id: caption})`** — rewrite captions.

## Installation

The AI extra pulls the LLM client and slug libraries:

```bash
pip install "vexy-lines-apy[ai]"     # openai + pathvalidate + python-slugify
```

## Using it from the CLI and GUI

- **CLI:** `vexy-lines-cli ai-rename road-12.lines` — see the [CLI docs](https://vexy.dev/vexy-lines-cli/).
- **GUI:** *Lines ▸ AI Rename Layers & Fills…* in [Vexy Lines Run](https://vexy.dev/vexy-lines-run/).

## See also

- Official Vexy Lines help: [Document Structure](https://help.vexy.art/lines/articles/document-structure-overview/) · [Fill Properties](https://help.vexy.art/lines/articles/fill-properties-1/) · [Layers Panel](https://help.vexy.art/lines/articles/layers-panel/) · [Export](https://help.vexy.art/lines/articles/exporting-the-artwork/)
- [.lines parser reference](https://vexy.dev/vexy-lines-py/) in `vexy-lines-py`
- [MCP Protocol](mcp-protocol.md) — the tools the renamer drives
