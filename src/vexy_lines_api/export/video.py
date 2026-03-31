# this_file: vexy-lines-apy/src/vexy_lines_api/export/video.py

from __future__ import annotations

import io
import tempfile
import threading
from pathlib import Path
from typing import Any

import cv2  # type: ignore[import-untyped]
from loguru import logger

from vexy_lines_api.client import MCPClient
from vexy_lines_api.style import apply_style, interpolate_style, styles_compatible
from vexy_lines_api.export.callbacks import ProgressCallback, PreviewCallback, report_preview, report_progress
from vexy_lines_api.export.errors import ExportAborted
from vexy_lines_api.export.io import estimate_svg_dimensions, parse_size_multiplier, save_image_bytes
from vexy_lines_api.export.lines import load_style
from vexy_lines_api.video import probe, process_video_with_style, svg_to_pil


def process_video(
    *,
    input_path: str,
    style_path: str | None,
    end_style_path: str | None,
    output_path: str,
    fmt: str,
    size: str,
    audio: bool,
    frame_range: tuple[int, int] | None,
    relative_style: bool = False,
    style_mode: str = "auto",
    abort_event: threading.Event | None = None,
    on_progress: ProgressCallback | None,
    on_preview: PreviewCallback | None = None,
) -> None:
    if fmt == "MP4":
        process_video_to_mp4(
            input_path=input_path,
            style_path=style_path,
            end_style_path=end_style_path,
            output_path=output_path,
            size=size,
            audio=audio,
            frame_range=frame_range,
            relative_style=relative_style,
            style_mode=style_mode,
            abort_event=abort_event,
            on_progress=on_progress,
            on_preview=on_preview,
        )
        return

    process_video_to_frames(
        input_path=input_path,
        style_path=style_path,
        end_style_path=end_style_path,
        output_path=output_path,
        fmt=fmt,
        size=size,
        frame_range=frame_range,
        relative_style=relative_style,
        style_mode=style_mode,
        abort_event=abort_event,
        on_progress=on_progress,
        on_preview=on_preview,
    )


def process_video_to_mp4(
    *,
    input_path: str,
    style_path: str | None,
    end_style_path: str | None,
    output_path: str,
    size: str,
    audio: bool,
    frame_range: tuple[int, int] | None,
    relative_style: bool = False,
    style_mode: str = "auto",
    abort_event: threading.Event | None = None,
    on_progress: ProgressCallback | None,
    on_preview: PreviewCallback | None = None,
) -> None:
    info = probe(input_path)
    style = load_style(style_path) if style_path else None
    end_style = load_style(end_style_path) if end_style_path else None

    start = frame_range[0] if frame_range else 0
    end = (frame_range[1] + 1) if frame_range else info.total_frames
    total = max(end - start, 1)

    report_progress(on_progress, 0, total, "Processing video...")

    def _on_frame(current: int, _total: int) -> None:
        report_progress(on_progress, current, total, "Processing video...")

    def _on_frame_image(pil_image: Any) -> None:
        buf = io.BytesIO()
        pil_image.save(buf, format="PNG")
        report_preview(on_preview, buf.getvalue())

    process_video_with_style(
        input_path=input_path,
        output_path=output_path,
        style=style,
        end_style=end_style,
        start_frame=start,
        end_frame=end,
        include_audio=audio,
        size_multiplier=parse_size_multiplier(size),
        relative=relative_style,
        style_mode=style_mode,
        abort_event=abort_event,
        on_progress=_on_frame,
        on_frame_image=_on_frame_image if on_preview else None,
    )


def process_video_to_frames(
    *,
    input_path: str,
    style_path: str | None,
    end_style_path: str | None,
    output_path: str,
    fmt: str,
    size: str,
    frame_range: tuple[int, int] | None,
    relative_style: bool = False,
    style_mode: str = "auto",
    abort_event: threading.Event | None = None,
    on_progress: ProgressCallback | None,
    on_preview: PreviewCallback | None = None,
) -> None:
    info = probe(input_path)
    out_dir = Path(output_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    multiplier = parse_size_multiplier(size)

    style = load_style(style_path) if style_path else None
    end_style = load_style(end_style_path) if end_style_path else None

    start = frame_range[0] if frame_range else 0
    end = min((frame_range[1] + 1) if frame_range else info.total_frames, info.total_frames)
    total = max(end - start, 1)

    cap = cv2.VideoCapture(input_path)
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES, start)

        with MCPClient() as client:
            for i in range(total):
                if abort_event and abort_event.is_set():
                    raise ExportAborted("Export aborted by user")

                ret, frame = cap.read()
                if not ret:
                    break

                report_progress(on_progress, i, total, f"Frame {start + i}")
                _, buf = cv2.imencode(".png", frame)
                frame_bytes: bytes = buf.tobytes()
                if style is None:
                    report_preview(on_preview, frame_bytes)

                if style is not None:
                    try:
                        t = i / total if total > 1 else 0.0
                        current_style = style
                        if end_style is not None and styles_compatible(style, end_style):
                            current_style = interpolate_style(style, end_style, t)

                        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                            tmp.write(frame_bytes)
                            tmp_path = Path(tmp.name)
                        try:
                            result = apply_style(client, current_style, str(tmp_path), relative=relative_style, style_mode=style_mode)
                            frame_bytes = result if isinstance(result, bytes) else result.encode()
                            try:
                                svg_str = frame_bytes.decode() if isinstance(frame_bytes, bytes) else frame_bytes
                                fw, fh = estimate_svg_dimensions(svg_str)
                                preview_img = svg_to_pil(svg_str, fw, fh)
                                preview_buf = io.BytesIO()
                                preview_img.save(preview_buf, format="PNG")
                                report_preview(on_preview, preview_buf.getvalue())
                            except Exception:
                                pass
                        finally:
                            tmp_path.unlink(missing_ok=True)
                    except Exception:
                        logger.opt(exception=True).debug("Style failed on frame {}", start + i)

                ext = fmt.lower()
                save_image_bytes(frame_bytes, out_dir / f"frame_{start + i:06d}.{ext}", fmt, multiplier)
    finally:
        cap.release()

    report_progress(on_progress, total, total, "Done")


_process_video = process_video
_process_video_to_mp4 = process_video_to_mp4
_process_video_to_frames = process_video_to_frames
