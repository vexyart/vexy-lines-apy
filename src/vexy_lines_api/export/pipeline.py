# this_file: vexy-lines-apy/src/vexy_lines_api/export/pipeline.py

from __future__ import annotations

import threading

from loguru import logger

from vexy_lines_api.export.callbacks import (
    CompleteCallback,
    ErrorCallback,
    PreviewCallback,
    ProgressCallback,
    report_complete,
    report_error,
)
from vexy_lines_api.export.errors import ExportAborted, ExportValidationError
from vexy_lines_api.export.images import process_images
from vexy_lines_api.export.io import estimate_svg_dimensions, parse_size_multiplier, save_image_bytes, save_svg_as_image
from vexy_lines_api.export.job import JobFolder
from vexy_lines_api.export.lines import process_lines
from vexy_lines_api.export.models import ExportRequest
from vexy_lines_api.export.video import process_video


def _normalize_request(
    request: ExportRequest | str,
    input_paths: list[str] | None,
    style_path: str | None,
    end_style_path: str | None,
    output_path: str | None,
    fmt: str | None,
    size: str | None,
    *,
    audio: bool,
    frame_range: tuple[int, int] | None,
    relative_style: bool,
    force: bool = False,
    cleanup: bool = False,
) -> ExportRequest:
    if isinstance(request, ExportRequest):
        return request

    if input_paths is None or output_path is None or fmt is None or size is None:
        raise ExportValidationError("Missing required legacy export fields")

    return ExportRequest(
        mode=request,
        input_paths=input_paths,
        style_path=style_path,
        end_style_path=end_style_path,
        output_path=output_path,
        format=fmt,
        size=size,
        audio=audio,
        frame_range=frame_range,
        relative_style=relative_style,
        force=force,
        cleanup=cleanup,
    )


def process_export(
    request: ExportRequest | str,
    input_paths: list[str] | None = None,
    style_path: str | None = None,
    end_style_path: str | None = None,
    output_path: str | None = None,
    fmt: str | None = None,
    size: str | None = None,
    *,
    audio: bool = True,
    frame_range: tuple[int, int] | None = None,
    relative_style: bool = False,
    force: bool = False,
    cleanup: bool = False,
    abort_event: threading.Event | None = None,
    on_progress: ProgressCallback | None = None,
    on_complete: CompleteCallback | None = None,
    on_error: ErrorCallback | None = None,
    on_preview: PreviewCallback | None = None,
) -> None:
    try:
        req = _normalize_request(
            request,
            input_paths,
            style_path,
            end_style_path,
            output_path,
            fmt,
            size,
            audio=audio,
            frame_range=frame_range,
            relative_style=relative_style,
            force=force,
            cleanup=cleanup,
        )

        job_folder = JobFolder(req.output_path, force=req.force)

        if req.mode == "lines":
            process_lines(
                input_paths=req.input_paths,
                style_path=req.style_path,
                end_style_path=req.end_style_path,
                output_path=req.output_path,
                fmt=req.format,
                size=req.size,
                relative_style=req.relative_style,
                style_mode=req.style_mode,
                abort_event=abort_event,
                on_progress=on_progress,
                on_preview=on_preview,
                job_folder=job_folder,
            )
        elif req.mode == "images":
            process_images(
                input_paths=req.input_paths,
                style_path=req.style_path,
                end_style_path=req.end_style_path,
                output_path=req.output_path,
                fmt=req.format,
                size=req.size,
                relative_style=req.relative_style,
                style_mode=req.style_mode,
                abort_event=abort_event,
                on_progress=on_progress,
                on_preview=on_preview,
                job_folder=job_folder,
            )
        elif req.mode == "video":
            process_video(
                input_path=req.input_paths[0] if req.input_paths else "",
                style_path=req.style_path,
                end_style_path=req.end_style_path,
                output_path=req.output_path,
                fmt=req.format,
                size=req.size,
                audio=req.audio,
                frame_range=req.frame_range,
                relative_style=req.relative_style,
                style_mode=req.style_mode,
                abort_event=abort_event,
                on_progress=on_progress,
                on_preview=on_preview,
                job_folder=job_folder,
            )
        else:
            report_error(on_error, f"Unknown mode: {req.mode}")
            return

        if req.cleanup:
            job_folder.cleanup()

        report_complete(on_complete, f"Export complete ({req.format})")
    except (ExportAborted, ExportValidationError) as exc:
        report_error(on_error, str(exc))
    except Exception as exc:
        logger.opt(exception=True).error("Export failed")
        report_error(on_error, str(exc))


_parse_size_multiplier = parse_size_multiplier
_estimate_svg_dimensions = estimate_svg_dimensions
_save_image_bytes = save_image_bytes
_save_svg_as_image = save_svg_as_image
