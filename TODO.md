# TODO — vexy-lines-apy

> Current improvement backlog for the API + style engine package.

## Code Quality

- [ ] Add connection health check / ping method to `MCPClient`
- [ ] Add retry logic for transient MCP connection failures
- [ ] Add `MCPClient.is_connected` property
- [ ] Add batch operations support (set params on multiple fills in one call)
- [ ] Add style comparison / diff utility (`compare_styles(a, b)`)
- [ ] Consider async client variant (`AsyncMCPClient`) for non-blocking workflows

## Documentation

- [ ] Audit protocol docs for argument name mismatches between documentation and actual `client.py` method signatures
- [ ] Document `save_and_consolidate()` workflow in examples.md

## Test Coverage

- [ ] Add tests for `save_document()`, `open_document()`, `render()`, `wait_for_render()`
- [ ] Add tests for `create_styled_document()` workflow
- [ ] Add tests for `video.py` module
- [ ] Add integration tests for the full style extraction → application pipeline
- [ ] Add tests for `save_and_consolidate()`

## Convention Files

- [ ] Create WORK.md, PLAN.md, CHANGELOG.md, DEPENDENCIES.md per project conventions

## Completed

- [x] Issue 307: Unit conversion in style transfer — `source_dpi` threading, `MCP_MM_PARAMS`/`MCP_PT_PARAMS`, mm→px and pt→px conversion in `_fill_params_to_dict()`, `_compute_relative_scale()` fix
- [x] `wait_for_render()` returns `False` on timeout (was always `True`)
- [x] `_svg_to_pil` renamed to `svg_to_pil` (public API)
- [x] `save_and_consolidate()` added (save → open → render → save workflow)
