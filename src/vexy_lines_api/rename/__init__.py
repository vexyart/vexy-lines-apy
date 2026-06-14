# this_file: vexy-lines-apy/src/vexy_lines_api/rename/__init__.py
"""AI-assisted renaming of Vexy Lines layers and fills.

Pipeline: render each fill in isolation, build an "inspection image" that
frames the fill's visible content over the full artwork, ask a vision model
what it is, and turn the answer into a filesystem-safe name. See
:func:`rename_lines` for the high-level entry point.
"""

from __future__ import annotations

from vexy_lines_api.rename.engine import (
    FillRename,
    LayerRename,
    RenamePlan,
    apply_rename_plan,
    build_rename_plan,
    rename_lines,
)
from vexy_lines_api.rename.inspection import content_bbox, make_inspection_image
from vexy_lines_api.rename.vlm import (
    VLMConfig,
    config_with_overrides,
    default_config,
    describe_region,
    suggest_layer_name,
    to_slug,
)

__all__ = [
    "FillRename",
    "LayerRename",
    "RenamePlan",
    "VLMConfig",
    "apply_rename_plan",
    "build_rename_plan",
    "config_with_overrides",
    "content_bbox",
    "default_config",
    "describe_region",
    "make_inspection_image",
    "rename_lines",
    "suggest_layer_name",
    "to_slug",
]
