# this_file: vexy-lines-apy/src/vexy_lines_api/export/images.py

from __future__ import annotations

import io
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from vexy_lines_api.client import MCPClient
from vexy_lines_api.style import apply_style, interpolate_style, styles_compatible
from vexy_lines_api.export.callbacks import ProgressCallback, PreviewCallback, report_preview, report_progress
from vexy_lines_api.export.errors import ExportAborted
from vexy_lines_api.export.io import estimate_svg_dimensions, parse_size_multiplier, save_image_bytes, save_svg_as_image
from vexy_lines_api.export.lines import load_style
from vexy_lines_api.video import svg_to_pil

if TYPE_CHECKING:
    from vexy_lines_api.export.job import JobFolder


def process_images(
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
    ext = fmt.lower()

    style = load_style(style_path) if style_path else None
    end_style = load_style(end_style_path) if end_style_path else None

    if style is not None:
        with MCPClient() as client:
            for idx, path in enumerate(input_paths):
                if abort_event and abort_event.is_set():
                    raise ExportAborted("Export aborted by user")

                report_progress(on_progress, idx, total, f"Styling {Path(path).name}")
                stem = Path(path).stem

                # Skip if job folder already has this asset
                if job_folder is not None:
                    jf_asset = job_folder.asset_path(stem, ext)
                    if jf_asset.exists():
                        logger.debug("Skipping {} (already in job folder)", stem)
                        job_folder.copy_to_output(jf_asset.name, out_dir / f"{stem}.{ext}")
                        continue

                try:
                    current_style = style
                    if end_style is not None and styles_compatible(style, end_style) and total > 1:
                        current_style = interpolate_style(style, end_style, idx / (total - 1))

                    # Save .lines intermediate when job folder is active
                    lines_dest: Path | None = None
                    if job_folder is not None:
                        lines_dest = job_folder.asset_path(stem, "lines")
                        if lines_dest.exists():
                            lines_dest = None  # already saved, skip

                    result = apply_style(
                        client, current_style, path,
                        relative=relative_style, style_mode=style_mode,
                        save_lines_to=str(lines_dest) if lines_dest is not None else None,
                    )
                    final_svg = result if isinstance(result, str) else result.decode()
                    width, height = estimate_svg_dimensions(final_svg)
                    preview_image = svg_to_pil(final_svg, width, height)
                    preview_buf = io.BytesIO()
                    preview_image.save(preview_buf, format="PNG")
                    report_preview(on_preview, preview_buf.getvalue())

                    if job_folder is not None:
                        # Save SVG intermediate (always, unless already exists)
                        svg_dest = job_folder.asset_path(stem, "svg")
                        if not svg_dest.exists():
                            svg_dest.write_text(final_svg, encoding="utf-8")

                        jf_asset = job_folder.asset_path(stem, ext)
                        if fmt == "SVG":
                            # SVG already saved as intermediate; copy to final asset
                            if not jf_asset.exists():
                                jf_asset.write_text(final_svg, encoding="utf-8")
                        else:
                            save_svg_as_image(final_svg, jf_asset, fmt, multiplier)
                        job_folder.copy_to_output(jf_asset.name, out_dir / f"{stem}.{ext}")
                    else:
                        if fmt == "SVG":
                            (out_dir / f"{stem}.svg").write_text(final_svg, encoding="utf-8")
                        else:
                            save_svg_as_image(final_svg, out_dir / f"{stem}.{ext}", fmt, multiplier)
                except Exception:
                    logger.opt(exception=True).warning("Style application failed for {}", path)
                    img_data = Path(path).read_bytes()
                    report_preview(on_preview, img_data)
                    if job_folder is not None:
                        jf_asset = job_folder.asset_path(stem, ext)
                        save_image_bytes(img_data, jf_asset, fmt, multiplier)
                        job_folder.copy_to_output(jf_asset.name, out_dir / f"{stem}.{ext}")
                    else:
                        save_image_bytes(img_data, out_dir / f"{stem}.{ext}", fmt, multiplier)
    else:
        for idx, path in enumerate(input_paths):
            if abort_event and abort_event.is_set():
                raise ExportAborted("Export aborted by user")
            report_progress(on_progress, idx, total, f"Exporting {Path(path).name}")
            stem = Path(path).stem

            if job_folder is not None:
                jf_asset = job_folder.asset_path(stem, ext)
                if jf_asset.exists():
                    logger.debug("Skipping {} (already in job folder)", stem)
                    job_folder.copy_to_output(jf_asset.name, out_dir / f"{stem}.{ext}")
                    continue

            img_data = Path(path).read_bytes()
            report_preview(on_preview, img_data)
            if job_folder is not None:
                jf_asset = job_folder.asset_path(stem, ext)
                save_image_bytes(img_data, jf_asset, fmt, multiplier)
                job_folder.copy_to_output(jf_asset.name, out_dir / f"{stem}.{ext}")
            else:
                save_image_bytes(img_data, out_dir / f"{stem}.{ext}", fmt, multiplier)

    report_progress(on_progress, total, total, "Done")


_process_images = process_images
