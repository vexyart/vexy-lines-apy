# this_file: vexy-lines-apy/src/vexy_lines_api/export/lines.py

from __future__ import annotations

import io
import shutil
import tempfile
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from vexy_lines import parse as parse_lines
from vexy_lines_api.client import MCPClient
from vexy_lines_api.style import apply_style, extract_style, interpolate_style, styles_compatible
from vexy_lines_api.export.callbacks import ProgressCallback, PreviewCallback, report_preview, report_progress
from vexy_lines_api.export.errors import ExportAborted
from vexy_lines_api.export.io import estimate_svg_dimensions, parse_size_multiplier, save_image_bytes
from vexy_lines_api.video import svg_to_pil

if TYPE_CHECKING:
    from vexy_lines_api.export.job import JobFolder


def load_style(path: str) -> Any:
    try:
        return extract_style(path)
    except Exception:
        logger.opt(exception=True).warning("Could not load style from {}", path)
        return None


def process_lines(
    *,
    input_paths: list[str],
    style_path: str | None,
    end_style_path: str | None,
    output_path: str,
    fmt: str,
    size: str,
    relative_style: bool = False,
    style_mode: str = "auto",
    abort_event: threading.Event | None = None,
    on_progress: ProgressCallback | None,
    on_preview: PreviewCallback | None = None,
    job_folder: JobFolder | None = None,
) -> None:
    total = len(input_paths)
    out_dir = Path(output_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    multiplier = parse_size_multiplier(size)

    style = load_style(style_path) if style_path else None
    end_style = load_style(end_style_path) if end_style_path else None

    with MCPClient() as client:
        for idx, path in enumerate(input_paths):
            if abort_event and abort_event.is_set():
                raise ExportAborted("Export aborted by user")

            stem = Path(path).stem
            ext = fmt.lower()

            if fmt == "LINES":
                report_progress(on_progress, idx, total, f"Copying {Path(path).name}")
                if job_folder is not None:
                    jf_dest = job_folder.asset_path(stem, "lines")
                    if not jf_dest.exists():
                        shutil.copy2(path, jf_dest)
                    job_folder.copy_to_output(jf_dest.name, out_dir / Path(path).name)
                else:
                    shutil.copy2(path, out_dir / Path(path).name)
                try:
                    doc = parse_lines(path)
                    preview_data = doc.preview_image_data or doc.source_image_data
                    if preview_data:
                        report_preview(on_preview, preview_data)
                except Exception:
                    pass
                continue

            if style is not None:
                report_progress(on_progress, idx, total, f"Processing {Path(path).name}")

                # Skip if job folder already has this asset
                if job_folder is not None:
                    jf_asset = job_folder.asset_path(stem, ext)
                    if jf_asset.exists():
                        logger.debug("Skipping {} (already in job folder)", stem)
                        job_folder.copy_to_output(jf_asset.name, out_dir / f"{stem}.{ext}")
                        continue

                try:
                    doc = parse_lines(path)
                except Exception:
                    logger.opt(exception=True).warning("Could not parse {}", path)
                    continue

                img_bytes: bytes | None = doc.source_image_data or doc.preview_image_data
                if img_bytes is None:
                    logger.warning("No image data in {}", path)
                    continue

                current_style = style
                if end_style is not None and styles_compatible(style, end_style) and total > 1:
                    current_style = interpolate_style(style, end_style, idx / (total - 1))

                with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                    tmp.write(img_bytes)
                    tmp_path = Path(tmp.name)
                try:
                    svg_text = apply_style(client, current_style, str(tmp_path), relative=relative_style, style_mode=style_mode)
                    width, height = estimate_svg_dimensions(svg_text)
                    image = svg_to_pil(svg_text, width, height)
                    preview_buf = io.BytesIO()
                    image.save(preview_buf, format="PNG")
                    report_preview(on_preview, preview_buf.getvalue())

                    if job_folder is not None:
                        # Save to job folder first, then copy to output
                        jf_asset = job_folder.asset_path(stem, ext)
                        if fmt == "SVG":
                            jf_asset.write_text(svg_text, encoding="utf-8")
                        elif fmt in ("PNG", "JPG"):
                            save_image_bytes(svg_text.encode(), jf_asset, fmt, multiplier)
                        job_folder.copy_to_output(jf_asset.name, out_dir / f"{stem}.{ext}")
                    else:
                        if fmt == "SVG":
                            (out_dir / f"{stem}.svg").write_text(svg_text, encoding="utf-8")
                        elif fmt in ("PNG", "JPG"):
                            save_image_bytes(svg_text.encode(), out_dir / f"{stem}.{fmt.lower()}", fmt, multiplier)
                finally:
                    tmp_path.unlink(missing_ok=True)
                continue

            # Unstyled direct MCP export
            report_progress(on_progress, idx, total, f"Exporting {Path(path).name}")

            # Skip if job folder already has this asset
            if job_folder is not None:
                jf_asset = job_folder.asset_path(stem, ext)
                if jf_asset.exists():
                    logger.debug("Skipping {} (already in job folder)", stem)
                    job_folder.copy_to_output(jf_asset.name, out_dir / f"{stem}.{ext}")
                    continue

            try:
                client.open_document(path)
                client.render()
                if fmt == "SVG":
                    if job_folder is not None:
                        jf_dest = job_folder.asset_path(stem, "svg")
                        client.export_svg(str(jf_dest))
                        job_folder.copy_to_output(jf_dest.name, out_dir / f"{stem}.svg")
                    else:
                        client.export_svg(str(out_dir / f"{stem}.svg"))
                elif fmt == "PNG":
                    if job_folder is not None:
                        jf_dest = job_folder.asset_path(stem, "png")
                        client.export_png(str(jf_dest))
                        report_preview(on_preview, jf_dest.read_bytes())
                        if multiplier > 1:
                            save_image_bytes(jf_dest.read_bytes(), jf_dest, fmt, multiplier)
                        job_folder.copy_to_output(jf_dest.name, out_dir / f"{stem}.png")
                    else:
                        dest = out_dir / f"{stem}.png"
                        client.export_png(str(dest))
                        report_preview(on_preview, dest.read_bytes())
                        if multiplier > 1:
                            save_image_bytes(dest.read_bytes(), dest, fmt, multiplier)
                elif fmt == "JPG":
                    if job_folder is not None:
                        jf_dest = job_folder.asset_path(stem, "jpg")
                        client.export_jpeg(str(jf_dest))
                        report_preview(on_preview, jf_dest.read_bytes())
                        if multiplier > 1:
                            save_image_bytes(jf_dest.read_bytes(), jf_dest, fmt, multiplier)
                        job_folder.copy_to_output(jf_dest.name, out_dir / f"{stem}.jpg")
                    else:
                        dest = out_dir / f"{stem}.jpg"
                        client.export_jpeg(str(dest))
                        report_preview(on_preview, dest.read_bytes())
                        if multiplier > 1:
                            save_image_bytes(dest.read_bytes(), dest, fmt, multiplier)
            except Exception:
                logger.opt(exception=True).warning("MCP export failed for {}", path)

    report_progress(on_progress, total, total, "Done")


_process_lines = process_lines
_load_style = load_style
