# this_file: vexy-lines-apy/src/vexy_lines_api/rename/engine.py
"""Orchestrate AI-assisted renaming of a .lines file's layers and fills.

The pipeline (see :func:`rename_lines`):

1. Parse the ``.lines`` structure with ``vexy-lines-py``.
2. Open it in the Vexy Lines app (via :class:`~vexy_lines_api.client.MCPClient`),
   render with all fills visible, and capture the full artwork.
3. For each fill: show only that fill, render, capture it, build an inspection
   image, and ask a vision model what it is.
4. For each layer: ask a model for a name from its fills' descriptions.
5. Produce a :class:`RenamePlan`, then write a renamed copy of the file with
   :func:`~vexy_lines.rename_objects` (the app is never asked to save).

The MCP rendering and the model calls are injectable, so the planning logic is
fully testable without the app or a network.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from vexy_lines import GroupInfo, LayerInfo, parse, rename_objects, set_visibility
from vexy_lines_api.rename.inspection import make_inspection_image
from vexy_lines_api.rename.vlm import (
    VLMConfig,
    default_config,
    describe_region,
    suggest_layer_name,
    to_slug,
)

if TYPE_CHECKING:
    from vexy_lines import FillNode, LinesDocument
    from vexy_lines_api.client import MCPClient

# A callable that opens a specific .lines file, renders it, and returns PNG bytes.
# Visibility is baked into each file (live MCP set_visible does NOT affect the
# export), so each render targets a concrete on-disk document.
RenderLinesPng = Callable[["MCPClient", Path], bytes]
DescribeFn = Callable[[bytes], str]
SuggestFn = Callable[[list[str]], str]


@dataclass
class FillRename:
    """A planned rename for a single fill.

    Attributes:
        object_id: The fill's object ID in the .lines file.
        old_caption: The fill's current caption.
        fill_type: Algorithm name (e.g. ``"linear"``).
        layer_id: Object ID of the containing layer, or ``None``.
        description: Raw telegraphic phrase from the vision model.
        new_caption: Filesystem-safe slug used as the new caption.
    """

    object_id: int
    old_caption: str
    fill_type: str
    layer_id: int | None
    description: str
    new_caption: str


@dataclass
class LayerRename:
    """A planned rename for a single layer.

    Attributes:
        object_id: The layer's object ID.
        old_caption: The layer's current caption.
        fill_ids: Object IDs of fills contained in the layer.
        description: Raw name suggestion from the model.
        new_caption: Filesystem-safe slug used as the new caption.
    """

    object_id: int
    old_caption: str
    fill_ids: list[int]
    description: str
    new_caption: str


@dataclass
class RenamePlan:
    """The complete set of renames computed for a .lines file.

    Attributes:
        lines_path: Source ``.lines`` file the plan was built from.
        fills: Planned fill renames in document order.
        layers: Planned layer renames in document order.
        full_image: PNG bytes of the all-fills render (for debugging/UI).
    """

    lines_path: Path
    fills: list[FillRename] = field(default_factory=list)
    layers: list[LayerRename] = field(default_factory=list)
    full_image: bytes | None = None

    def as_renames(self) -> dict[int, str]:
        """Return the combined ``object_id -> new_caption`` map for both."""
        renames: dict[int, str] = {}
        for layer in self.layers:
            renames[layer.object_id] = layer.new_caption
        for fill in self.fills:
            renames[fill.object_id] = fill.new_caption
        return renames

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable summary (without image bytes)."""
        return {
            "lines_path": str(self.lines_path),
            "fills": [
                {
                    "object_id": f.object_id,
                    "old_caption": f.old_caption,
                    "fill_type": f.fill_type,
                    "layer_id": f.layer_id,
                    "description": f.description,
                    "new_caption": f.new_caption,
                }
                for f in self.fills
            ],
            "layers": [
                {
                    "object_id": le.object_id,
                    "old_caption": le.old_caption,
                    "fill_ids": le.fill_ids,
                    "description": le.description,
                    "new_caption": le.new_caption,
                }
                for le in self.layers
            ],
        }


# ---------------------------------------------------------------------------
# Tree walking
# ---------------------------------------------------------------------------


def _iter_layers(nodes: Iterable[GroupInfo | LayerInfo]) -> Iterable[LayerInfo]:
    """Yield every :class:`LayerInfo` in document order, descending groups."""
    for node in nodes:
        if isinstance(node, GroupInfo):
            yield from _iter_layers(node.children)
        elif isinstance(node, LayerInfo):
            yield node


def _collect_fill_contexts(doc: LinesDocument) -> tuple[list[tuple[FillNode, int | None, set[int]]], set[int]]:
    """Return per-fill context plus the set of all fill IDs.

    Each context is ``(fill, layer_id, ancestor_ids)`` where *ancestor_ids* is
    the set of object IDs of the fill's containing layer and all enclosing
    groups — the elements that must stay visible for the fill to render.
    """
    contexts: list[tuple[FillNode, int | None, set[int]]] = []
    all_fill_ids: set[int] = set()

    def walk(nodes: Iterable[GroupInfo | LayerInfo], ancestors: set[int]) -> None:
        for node in nodes:
            if isinstance(node, GroupInfo):
                child_ancestors = ancestors | ({node.object_id} if node.object_id is not None else set())
                walk(node.children, child_ancestors)
            elif isinstance(node, LayerInfo):
                layer_ancestors = ancestors | ({node.object_id} if node.object_id is not None else set())
                for fill in node.fills:
                    if fill.object_id is not None:
                        all_fill_ids.add(fill.object_id)
                        contexts.append((fill, node.object_id, layer_ancestors))

    walk(doc.groups, set())
    return contexts, all_fill_ids


def _dedupe(names: list[str]) -> list[str]:
    """Make slugs unique by appending ``-2``, ``-3`` … to later duplicates."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for name in names:
        if name not in seen:
            seen[name] = 1
            out.append(name)
        else:
            seen[name] += 1
            out.append(f"{name}-{seen[name]}")
    return out


# ---------------------------------------------------------------------------
# Default MCP-backed renderer
# ---------------------------------------------------------------------------


def _make_default_render_lines_png(work_dir: Path, dpi: int | None, render_timeout: float) -> RenderLinesPng:
    """Build a renderer that opens a .lines file, renders, and returns PNG bytes.

    Each call opens *lines_path* fresh so the file's baked-in visibility takes
    effect, renders it, exports SVG, and rasterises locally (the app's MCP PNG
    export is unreliable — mirrors :func:`vexy_lines_api.bundle.export_bundle`).
    """
    from vexy_lines_api.bundle import _wait_for_file  # noqa: PLC0415
    from vexy_lines_api.export.io import save_svg_as_image  # noqa: PLC0415

    counter = {"n": 0}

    def render_lines_png(client: MCPClient, lines_path: Path) -> bytes:
        client.open_document(str(Path(lines_path).resolve()))
        client.render(timeout=render_timeout)
        counter["n"] += 1
        svg_path = work_dir / f"_render_{counter['n']:03d}.svg"
        client.export_svg(str(svg_path), dpi=dpi)
        _wait_for_file(svg_path)
        svg_text = svg_path.read_text(encoding="utf-8")
        png_path = work_dir / f"_render_{counter['n']:03d}.png"
        save_svg_as_image(svg_text, png_path, "PNG")
        data = png_path.read_bytes()
        svg_path.unlink(missing_ok=True)
        png_path.unlink(missing_ok=True)
        return data

    return render_lines_png


# ---------------------------------------------------------------------------
# Plan building
# ---------------------------------------------------------------------------


def build_rename_plan(
    lines_path: str | Path,
    client: MCPClient,
    *,
    config: VLMConfig | None = None,
    work_dir: str | Path | None = None,
    dpi: int | None = 72,
    render_timeout: float = 600.0,
    render_lines_png: RenderLinesPng | None = None,
    describe: DescribeFn | None = None,
    suggest: SuggestFn | None = None,
    save_artifacts: bool = True,
) -> RenamePlan:
    """Build a :class:`RenamePlan` for *lines_path* using the app and a model.

    For each fill, a copy of the document is written with that fill visible and
    every other fill set to ``visible="0"`` (its containing layer/groups kept
    visible), then opened and exported — live MCP visibility toggling does not
    affect the export, so visibility is baked into the file instead.

    Args:
        lines_path: Path to the ``.lines`` file.
        client: A connected :class:`~vexy_lines_api.client.MCPClient`.
        config: VLM settings; :func:`~vexy_lines_api.rename.vlm.default_config`
            when ``None``.
        work_dir: Directory for inspection artifacts and temp renders. A
            ``<stem>-rename`` folder beside the input when ``None``.
        dpi: Export DPI for renders (lower is faster; default 72).
        render_timeout: Maximum seconds to wait for each render.
        render_lines_png: Callable ``(client, lines_path) -> png_bytes`` that
            opens and renders a specific file; an MCP+SVG renderer is built when
            ``None`` (override in tests).
        describe: Callable mapping inspection PNG bytes to a phrase;
            :func:`~vexy_lines_api.rename.vlm.describe_region` when ``None``.
        suggest: Callable mapping fill phrases to a layer name;
            :func:`~vexy_lines_api.rename.vlm.suggest_layer_name` when ``None``.
        save_artifacts: Write single-fill and inspection PNGs into *work_dir*.

    Returns:
        The computed :class:`RenamePlan` (not yet applied to any file).
    """
    src = Path(lines_path).expanduser().resolve()
    doc = parse(src)
    config = config or default_config()

    out_dir = Path(work_dir).expanduser().resolve() if work_dir is not None else src.parent / f"{src.stem}-rename"
    out_dir.mkdir(parents=True, exist_ok=True)

    if render_lines_png is None:
        render_lines_png = _make_default_render_lines_png(out_dir, dpi, render_timeout)
    describe_fn: DescribeFn = describe or (lambda png: describe_region(png, config=config))
    suggest_fn: SuggestFn = suggest or (lambda items: suggest_layer_name(items, config=config))

    contexts, all_fill_ids = _collect_fill_contexts(doc)
    layers = list(_iter_layers(doc.groups))
    logger.info("Renaming {}: {} layers, {} fills", src.name, len(layers), len(all_fill_ids))

    # 1) Full render: the document exactly as authored.
    full_png = render_lines_png(client, src)
    if save_artifacts:
        (out_dir / "_full.png").write_bytes(full_png)

    # 2) Per-fill renders: a copy with only this fill (and its ancestors) visible.
    descriptions: dict[int, str] = {}
    for fill, _layer_id, ancestors in contexts:
        fid = fill.object_id
        assert fid is not None  # contexts only yields fills with an object_id  # noqa: S101
        visible_map: dict[int, bool] = dict.fromkeys(all_fill_ids, False)
        visible_map[fid] = True
        for anc in ancestors:
            visible_map[anc] = True

        variant = out_dir / f"_fill_{fid}.lines"
        set_visibility(src, variant, visible_map)
        try:
            single_png = render_lines_png(client, variant)
        finally:
            # The per-fill .lines copy is a bulky (~MBs) intermediate; never keep it.
            variant.unlink(missing_ok=True)
        inspection = make_inspection_image(single_png, full_png)
        phrase = describe_fn(inspection)
        descriptions[fid] = phrase
        if save_artifacts:
            (out_dir / f"fill_{fid}_single.png").write_bytes(single_png)
            (out_dir / f"fill_{fid}_inspect.png").write_bytes(inspection)
        logger.info("Fill {} ({}): {!r}", fid, fill.params.fill_type, phrase)

    plan = _assemble_plan(src, full_png, layers, descriptions, suggest_fn)
    if save_artifacts:
        _write_plan_json(out_dir / "rename-plan.json", plan)
    return plan


def _assemble_plan(
    src: Path,
    full_png: bytes,
    layers: list[LayerInfo],
    descriptions: dict[int, str],
    suggest_fn: SuggestFn,
) -> RenamePlan:
    """Turn per-fill descriptions into a deduplicated :class:`RenamePlan`."""
    plan = RenamePlan(lines_path=src, full_image=full_png)

    # Fills, with globally-unique slugs. Capture the object_id up front so the
    # downstream code never has to re-narrow Optional[int].
    fill_records: list[tuple[int, FillNode, int | None]] = []
    for layer in layers:
        for fill in layer.fills:
            if fill.object_id is not None:
                fill_records.append((fill.object_id, fill, layer.object_id))

    fill_slugs = _dedupe(
        [to_slug(descriptions.get(fid, "") or fill.params.fill_type) for fid, fill, _ in fill_records]
    )
    for (fid, fill, layer_id), slug in zip(fill_records, fill_slugs, strict=True):
        plan.fills.append(
            FillRename(
                object_id=fid,
                old_caption=fill.caption,
                fill_type=fill.params.fill_type,
                layer_id=layer_id,
                description=descriptions.get(fid, ""),
                new_caption=slug,
            )
        )

    # Layers, with globally-unique slugs.
    layer_records = [(le.object_id, le) for le in layers if le.object_id is not None]
    layer_raw: list[str] = []
    for _, layer in layer_records:
        phrases = [descriptions.get(f.object_id, "") for f in layer.fills if f.object_id is not None]
        layer_raw.append(suggest_fn([p for p in phrases if p]))
    layer_slugs = _dedupe([to_slug(name) for name in layer_raw])
    for (lid, layer), raw, slug in zip(layer_records, layer_raw, layer_slugs, strict=True):
        plan.layers.append(
            LayerRename(
                object_id=lid,
                old_caption=layer.caption,
                fill_ids=[f.object_id for f in layer.fills if f.object_id is not None],
                description=raw,
                new_caption=slug,
            )
        )

    return plan


def _write_plan_json(path: Path, plan: RenamePlan) -> None:
    import json  # noqa: PLC0415

    path.write_text(json.dumps(plan.to_dict(), indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Applying
# ---------------------------------------------------------------------------


def apply_rename_plan(plan: RenamePlan, output_path: str | Path) -> int:
    """Write a renamed copy of the plan's source file.

    Args:
        plan: A :class:`RenamePlan` from :func:`build_rename_plan`.
        output_path: Destination ``.lines`` path (may equal the source).

    Returns:
        The number of objects renamed.
    """
    return rename_objects(plan.lines_path, output_path, plan.as_renames())


def rename_lines(
    lines_path: str | Path,
    output_path: str | Path | None = None,
    *,
    client: MCPClient | None = None,
    config: VLMConfig | None = None,
    work_dir: str | Path | None = None,
    dpi: int | None = 72,
    dry_run: bool = False,
    **plan_kwargs: object,
) -> RenamePlan:
    """Analyse, name, and (unless *dry_run*) rewrite a .lines file.

    Args:
        lines_path: Path to the ``.lines`` file.
        output_path: Where to write the renamed file. Defaults to
            ``<stem>-renamed.lines`` beside the input. Ignored when *dry_run*.
        client: A connected :class:`~vexy_lines_api.client.MCPClient`. When
            ``None``, one is created for the duration of the call.
        config: VLM settings; environment defaults when ``None``.
        work_dir: Directory for artifacts (see :func:`build_rename_plan`).
        dpi: Export DPI for renders.
        dry_run: Compute the plan but do not write any file.
        **plan_kwargs: Forwarded to :func:`build_rename_plan` (e.g. ``describe``,
            ``suggest``, ``render_lines_png``, ``save_artifacts``).

    Returns:
        The computed :class:`RenamePlan`.
    """
    src = Path(lines_path).expanduser().resolve()

    def _run(active_client: MCPClient) -> RenamePlan:
        return build_rename_plan(
            src,
            active_client,
            config=config,
            work_dir=work_dir,
            dpi=dpi,
            **plan_kwargs,  # type: ignore[arg-type]
        )

    if client is not None:
        plan = _run(client)
    else:
        from vexy_lines_api.client import MCPClient as _MCPClient  # noqa: PLC0415

        with _MCPClient() as own_client:
            plan = _run(own_client)

    if not dry_run:
        if output_path is not None:
            out = Path(output_path).expanduser().resolve()
        else:
            out = src.with_name(f"{src.stem}-renamed.lines")
        count = apply_rename_plan(plan, out)
        logger.info("Wrote {} ({} renames) -> {}", out.name, count, out)

    return plan
