# Changelog

All notable changes to **vexy-lines-apy** are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [1.0.46] — 2026-06

- chore: Auto-commit maintenance, CI alignment.

## [1.0.45] — 2026-06

- fix: Socket clean-up edge cases under `__exit__` with pending auto-launch.

## [1.0.44] — 2026-06

- refactor: `_wait_for_server` back-off capped at 2 s; interval starts at 0.5 s.

## [1.0.43] — 2026-06

- feat: `record_interpolation_screen` — captures Vexy Lines window frame-by-frame; optional MP4 assembly; `keep_work` / `work_dir` controls.

## [1.0.42] — 2026-06

- feat: `render_interpolation_video` — generates interpolated `.lines` frames, renders via MCP, rasterises PNG, assembles MP4.

## [1.0.41] — 2026-06

- feat: AI-assisted rename (`rename_lines`) — renders each fill in isolation, calls vision LLM, writes a renamed copy.
- feat: `[ai]` optional extra: `openai`, `pathvalidate`, `python-slugify`.

## [1.0.36] — 2026-04

- feat: `interpolate_lines` — offline `.lines` interpolation; no app required.
- feat: `interpolate_style`, `styles_compatible` — blend two styles at any `t` in [0, 1].

## [1.0.35] — 2026-04

- feat: Job Folder system (`JobFolder`, `ExportRequest`, `process_export`) — persistent intermediate storage, resume on interruption, `VEXY_LINES_JOB_FOLDER` env override.
- feat: Video export now caches raw source frames under `src/src--{stem}--{NNN}.png` before styling.
- feat: `apply_style()` gains `save_lines_to` parameter.

## [1.0.30] — 2026-03

- feat: `svg_parsed()` — returns a parsed `svglab.Svg` object (requires `pip install svglab`).
- feat: `svg()` — exports to a temporary file and returns SVG content as a string.
- feat: `export_svg`, `export_pdf`, `export_png`, `export_jpeg`, `export_eps` convenience shortcuts.

## [1.0.20] — 2026-02

- feat: `extract_style`, `apply_style` — style engine API.
- feat: Image-filter chain methods: `get_image_filters`, `set_image_filters`, `add_image_filter`, `remove_image_filter`.
- feat: Visual methods: `set_source_image`, `set_caption`, `set_visible`, `set_layer_mask`, `get_layer_mask`, `transform_layer`, `set_layer_warp`.

## [1.0.0] — 2026-01

- Initial release: TCP/JSON-RPC 2.0 MCP client, `MCPClient` context manager.
- Document operations: `new_document`, `open_document`, `save_document`, `export_document`, `get_document_info`.
- Structure operations: `get_layer_tree`, `add_group`, `add_layer`, `add_fill`, `delete_object`.
- Control: `render`, `render_all`, `wait_for_render`, `get_render_status`, `undo`, `redo`, `get_selection`, `select_object`.
- Auto-launch: opens Vexy Lines on macOS (`open -a`) or Windows (Program Files search) and waits up to 30 s.

## Previous releases

See [GitHub releases](https://github.com/vexyart/vexy-lines-apy/releases) for earlier versions.
