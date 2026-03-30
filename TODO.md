# TODO — Issue 307: Fix unit conversion in style transfer

## Root cause

`.lines` XML stores spatial values in two different unit systems:
- **Thickness params** (`multiplier`, `base_width`): stored in **mm**
- **Spatial params** (`interval`, `dispersion`): stored in **points** (1 pt = 1/72 inch)

The MCP `set_fill_params` API expects **pixels** for all spatial parameters. The MCP server
then converts internally: thickness px→mm (`px * 25.4/dpi`), spatial px→pt (`px * 72/dpi`).

Current `_fill_params_to_dict()` does name translation only — **zero unit conversion**.
Raw mm/pt values get sent as if they were pixels, then the MCP server converts them
*again*, producing values that are off by factors of `dpi/25.4` or `dpi/72`.

Concrete example (beara-01.lines at 300 DPI → target at 72 DPI):
- `multiplier = 1.2014 mm` → sent as `1.2014 "pixels"` → MCP stores `1.2014 * 25.4/72 = 0.424 mm` (should be `1.2014 mm`)
- `interval = 5.07 pt` → sent as `5.07 "pixels"` → MCP stores `5.07 * 72/72 = 5.07 pt` (happens to be correct at 72 DPI only)

## Changes needed

### 1. Add MCP unit classification constants (`style.py`)

```python
# MCP params stored internally in mm (server converts: px * 25.4/dpi → mm)
MCP_MM_PARAMS: frozenset[str] = frozenset({"thickness", "thickness_min"})

# MCP params stored internally in pt (server converts: px * 72/dpi → pt)
MCP_PT_PARAMS: frozenset[str] = frozenset({"interval", "dispersion"})
```

### 2. Add mm→px and pt→px conversion in `_fill_params_to_dict()` (`style.py`)

- Add `source_dpi: int` parameter (the DPI of the source .lines document)
- After name translation, convert each value to pixels:
  - MCP_MM_PARAMS: `value_mm * (source_dpi / 25.4)` → pixels
  - MCP_PT_PARAMS: `value_pt * (source_dpi / 72.0)` → pixels
  - All other params (angle, contrast, break_up, break_down): pass as-is

### 3. Thread `source_dpi` through the apply chain (`style.py`)

- `_apply_fill(client, fill, layer_id)` → add `source_dpi: int` param, pass to `_fill_params_to_dict`
- `_apply_layer(client, layer, group_id)` → add `source_dpi: int` param, pass to `_apply_fill`
- `_apply_group(client, group, parent_id)` → add `source_dpi: int` param, pass to `_apply_layer`
- `apply_style()` → pass `style.props.dpi` as `source_dpi` to `_apply_group`/`_apply_layer`
- `create_styled_document()` → same

### 4. Fix `_compute_relative_scale()` unit mismatch (`style.py`)

Currently divides `target_width` (pixels) by `style.props.width_mm` (mm) — mixed units.

Fix: convert source mm to pixels before comparing:
```python
src_dpi = style.props.dpi or 72
src_w_px = style.props.width_mm * src_dpi / 25.4
src_h_px = style.props.height_mm * src_dpi / 25.4
scale_x = target_width / src_w_px
scale_y = target_height / src_h_px
```

This produces a dimensionless pixel-space scale factor. For the same image at different DPIs,
scale = 1.0 (correct — the pixel content is identical).

### 5. Clean up `SPATIAL_PARAMS` (`style.py`)

- Remove `base_width` — it's redundant with `thickness_min` (both from same XML attr `base_width`).
  It's scaled by `_scale_fill_params` but never sent to MCP (not in `PARSER_TO_MCP_PARAMS`).

### 6. Update tests (`tests/test_style.py`)

- `TestFillParamsToDict`: All tests must pass `source_dpi` and verify pixel-converted values.
  Add tests for mm→px and pt→px conversion at different DPIs.
- `TestComputeRelativeScale`: Update to use pixel target dimensions consistent with source DPI.
  `test_same_dimensions_returns_1` needs target pixels matching source mm at source DPI.
- `TestApplyStyle`: Update mock expectations — `set_fill_params` now receives pixel values.
- `TestApplyStyleRelative`: Update expectations for pixel-space scale computation.
- Add new test: round-trip verification that source mm/pt values survive the
  convert→MCP→store cycle correctly.
