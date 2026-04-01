# this_file: vexy-lines-apy/src/vexy_lines_api/export/video.py

from __future__ import annotations

from contextlib import nullcontext
import io
import shutil
import tempfile
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

import cv2  # type: ignore[import-untyped]
import numpy as np  # type: ignore[import-untyped]
from loguru import logger
from PIL import Image as PILImage

from vexy_lines_api.client import MCPClient
from vexy_lines_api.style import StyleMode, apply_style, interpolate_style, styles_compatible
from vexy_lines_api.export.callbacks import ProgressCallback, PreviewCallback, report_preview, report_progress
from vexy_lines_api.export.errors import ExportAborted
from vexy_lines_api.export.io import estimate_svg_dimensions, parse_size_multiplier, save_image_bytes
from vexy_lines_api.export.lines import load_style
from vexy_lines_api.video import _create_video_writer, _merge_audio, probe, process_video_with_style, svg_to_pil

if TYPE_CHECKING:
    from vexy_lines_api.export.job import JobFolder


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
    job_folder: JobFolder | None = None,
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
            job_folder=job_folder,
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
        job_folder=job_folder,
    )


def _frame_pad_width(total_frames: int) -> int:
    return max(3, len(str(max(total_frames, 1))))


def _extract_source_frames(
    *,
    input_path: str,
    start: int,
    end: int,
    output_stem: str,
    job_folder: JobFolder,
    pad_width: int,
    abort_event: threading.Event | None,
    on_progress: ProgressCallback | None,
) -> None:
    expected_frames = set(range(start + 1, end + 1))
    existing_frames = job_folder.existing_src_frames(output_stem, "png")
    if expected_frames.issubset(existing_frames):
        logger.info("Skipped {} cached source frames out of {}", len(expected_frames), len(expected_frames))
        return

    total = max(end - start, 1)
    cap = cv2.VideoCapture(input_path)
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES, start)
        for i in range(total):
            if abort_event and abort_event.is_set():
                raise ExportAborted("Export aborted by user")

            ret, frame = cap.read()
            if not ret:
                break

            frame_num = start + i + 1
            if frame_num in existing_frames:
                report_progress(on_progress, i + 1, total, f"Extracting frame {frame_num} (cached)")
                continue

            ok, buf = cv2.imencode(".png", frame)
            if not ok:
                msg = f"Failed to encode frame {frame_num} as PNG"
                raise RuntimeError(msg)

            src_path = job_folder.frame_src_path(output_stem, frame_num, "png", pad_width=pad_width)
            src_path.write_bytes(buf.tobytes())
            report_progress(on_progress, i + 1, total, f"Extracting frame {frame_num}")
    finally:
        cap.release()


def _read_source_frame_bytes(
    *,
    input_path: str,
    frame_num: int,
    job_folder: JobFolder | None,
    output_stem: str,
    pad_width: int,
) -> tuple[bytes, Path | None]:
    if job_folder is not None:
        src_path = job_folder.frame_src_path(output_stem, frame_num, "png", pad_width=pad_width)
        if not src_path.exists():
            msg = f"Missing extracted source frame: {src_path}"
            raise FileNotFoundError(msg)
        return src_path.read_bytes(), src_path

    cap = cv2.VideoCapture(input_path)
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num - 1)
        ret, frame = cap.read()
        if not ret:
            msg = f"Failed to read frame {frame_num} from {input_path}"
            raise FileNotFoundError(msg)
        ok, buf = cv2.imencode(".png", frame)
        if not ok:
            msg = f"Failed to encode frame {frame_num} as PNG"
            raise RuntimeError(msg)
        return buf.tobytes(), None
    finally:
        cap.release()


def _normalize_style_mode(style_mode: str) -> StyleMode:
    if style_mode == "auto":
        return "auto"
    if style_mode == "fast":
        return "fast"
    if style_mode == "slow":
        return "slow"
    return "auto"


def _assemble_mp4_from_frames(
    job_folder: JobFolder,
    output_stem: str,
    fps: float,
    start_frame_num: int,
    end_frame_num: int,
    pad_width: int,
    output_path: str,
    audio_source: str | None,
    include_audio: bool,
) -> None:
    """Assemble an MP4 from numbered PNG frames in the job folder.

    Reads ``{output_stem}--{N}.png`` for N in [start_frame_num, end_frame_num]
    and writes them sequentially to a VideoWriter.

    Args:
        job_folder: The job folder containing the frame PNGs.
        output_stem: Base name prefix for frame files.
        fps: Output video frame rate.
        start_frame_num: First frame number (inclusive).
        end_frame_num: Last frame number (inclusive).
        output_path: Final output MP4 path.
        audio_source: Path to original video for audio extraction, or None.
        include_audio: Whether to merge audio into the output.
    """
    # Read the first frame to determine dimensions
    first_frame_path = job_folder.frame_path(output_stem, start_frame_num, "png", pad_width=pad_width)
    if not first_frame_path.exists():
        msg = f"First frame not found: {first_frame_path}"
        raise FileNotFoundError(msg)

    first_img = PILImage.open(first_frame_path)
    width, height = first_img.size
    first_img.close()

    needs_audio = include_audio and audio_source is not None
    tmp_video_path: str | None = None

    if needs_audio:
        tmp_dir = tempfile.mkdtemp(prefix="vexy_assemble_")
        tmp_video_path = str(Path(tmp_dir) / "video_only.mp4")
        write_path = tmp_video_path
    else:
        write_path = output_path

    writer = _create_video_writer(write_path, fps, width, height)
    try:
        for frame_num in range(start_frame_num, end_frame_num + 1):
            frame_file = job_folder.frame_path(output_stem, frame_num, "png", pad_width=pad_width)
            if not frame_file.exists():
                logger.warning("Missing frame {} during assembly, skipping", frame_num)
                continue
            img = PILImage.open(frame_file).convert("RGB")
            bgr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
            writer.write(bgr)
            img.close()
    finally:
        writer.release()

    if needs_audio and tmp_video_path is not None and audio_source is not None:
        try:
            _merge_audio(tmp_video_path, audio_source, output_path)
        finally:
            shutil.rmtree(Path(tmp_video_path).parent, ignore_errors=True)


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
    job_folder: JobFolder | None = None,
) -> None:
    info = probe(input_path)
    style = load_style(style_path) if style_path else None
    end_style = load_style(end_style_path) if end_style_path else None
    effective_style_mode = _normalize_style_mode(style_mode)

    start = frame_range[0] if frame_range else 0
    end = min((frame_range[1] + 1) if frame_range else info.total_frames, info.total_frames)
    total = max(end - start, 1)
    pad_width = _frame_pad_width(info.total_frames)

    # When no job folder, delegate to the streaming approach
    if job_folder is None:
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
            style_mode=effective_style_mode,
            abort_event=abort_event,
            on_progress=_on_frame,
            on_frame_image=_on_frame_image if on_preview else None,
        )
        return

    # --- Two-phase job-folder approach ---
    multiplier = parse_size_multiplier(size)
    out_width = info.width * multiplier
    out_height = info.height * multiplier
    output_stem = job_folder.output_stem

    # Frame numbering: frame_num = internal_frame_index + 1
    # So if start=0, frames are 1,2,3...  If start=49, frames are 50,51,52...
    start_frame_num = start + 1
    end_frame_num = end  # end is exclusive internally, so last frame_num = end

    report_progress(on_progress, 0, total, "Extracting source frames...")
    _extract_source_frames(
        input_path=input_path,
        start=start,
        end=end,
        output_stem=output_stem,
        job_folder=job_folder,
        pad_width=pad_width,
        abort_event=abort_event,
        on_progress=on_progress,
    )

    existing = job_folder.existing_frames(output_stem, "png")
    skipped = 0

    report_progress(on_progress, 0, total, "Processing video frames...")
    client_context = MCPClient() if style is not None else nullcontext(None)
    with client_context as client:
        for i, frame_num in enumerate(range(start_frame_num, end_frame_num + 1), start=1):
            if abort_event and abort_event.is_set():
                raise ExportAborted("Export aborted by user")

            if frame_num in existing:
                skipped += 1
                report_progress(on_progress, i, total, f"Frame {frame_num} (cached)")
                continue

            report_progress(on_progress, i, total, f"Frame {frame_num}")
            src_path = job_folder.frame_src_path(output_stem, frame_num, "png", pad_width=pad_width)
            if not src_path.exists():
                msg = f"Missing extracted source frame: {src_path}"
                raise FileNotFoundError(msg)

            with PILImage.open(src_path) as source_img:
                pil_img = source_img.convert("RGB")

            if style is not None and client is not None:
                t = (i - 1) / total if total > 1 else 0.0
                current_style = style
                if end_style is not None and styles_compatible(style, end_style):
                    current_style = interpolate_style(style, end_style, t)

                lines_dest = job_folder.frame_path(output_stem, frame_num, "lines", pad_width=pad_width)
                svg_dest = job_folder.frame_path(output_stem, frame_num, "svg", pad_width=pad_width)

                try:
                    svg_string = apply_style(
                        client,
                        current_style,
                        str(src_path),
                        relative=relative_style,
                        style_mode=effective_style_mode,
                        save_lines_to=str(lines_dest) if not lines_dest.exists() else None,
                    )
                    if not svg_dest.exists():
                        svg_dest.write_text(svg_string, encoding="utf-8")

                    styled_img = svg_to_pil(svg_string, out_width, out_height).convert("RGB")
                except Exception:
                    logger.opt(exception=True).debug("Style failed on frame {}", frame_num)
                    styled_img = pil_img.copy()
            else:
                styled_img = pil_img.copy()

            if multiplier > 1:
                styled_img = styled_img.resize((out_width, out_height), PILImage.Resampling.LANCZOS)

            if on_preview is not None:
                preview_buf = io.BytesIO()
                styled_img.save(preview_buf, format="PNG")
                report_preview(on_preview, preview_buf.getvalue())

            styled_dest = job_folder.frame_path(output_stem, frame_num, "png", pad_width=pad_width)
            styled_img.save(str(styled_dest), format="PNG")

    if skipped > 0:
        logger.info("Skipped {} cached frames out of {}", skipped, total)

    # Phase 2: Assemble MP4 from the PNGs
    report_progress(on_progress, total, total, "Assembling video...")
    _assemble_mp4_from_frames(
        job_folder=job_folder,
        output_stem=output_stem,
        fps=info.fps,
        start_frame_num=start_frame_num,
        end_frame_num=end_frame_num,
        pad_width=pad_width,
        output_path=output_path,
        audio_source=input_path if audio and info.has_audio else None,
        include_audio=audio,
    )

    report_progress(on_progress, total, total, "Done")


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
    job_folder: JobFolder | None = None,
) -> None:
    info = probe(input_path)
    out_dir = Path(output_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    multiplier = parse_size_multiplier(size)

    style = load_style(style_path) if style_path else None
    end_style = load_style(end_style_path) if end_style_path else None
    effective_style_mode = _normalize_style_mode(style_mode)

    start = frame_range[0] if frame_range else 0
    end = min((frame_range[1] + 1) if frame_range else info.total_frames, info.total_frames)
    total = max(end - start, 1)
    ext = fmt.lower()
    pad_width = _frame_pad_width(info.total_frames)

    # Determine which frames already exist in the job folder
    existing: set[int] = set()
    output_stem: str = ""
    if job_folder is not None:
        output_stem = job_folder.output_stem
        report_progress(on_progress, 0, total, "Extracting source frames...")
        _extract_source_frames(
            input_path=input_path,
            start=start,
            end=end,
            output_stem=output_stem,
            job_folder=job_folder,
            pad_width=pad_width,
            abort_event=abort_event,
            on_progress=on_progress,
        )
        existing = job_folder.existing_frames(output_stem, ext)

    client_context = MCPClient() if style is not None else nullcontext(None)
    with client_context as client:
        for i in range(total):
            if abort_event and abort_event.is_set():
                raise ExportAborted("Export aborted by user")

            frame_num = start + i + 1

            if job_folder is not None and frame_num in existing:
                report_progress(on_progress, i + 1, total, f"Frame {frame_num} (cached)")
                continue

            report_progress(on_progress, i + 1, total, f"Frame {frame_num}")

            frame_bytes, src_path = _read_source_frame_bytes(
                input_path=input_path,
                frame_num=frame_num,
                job_folder=job_folder,
                output_stem=output_stem,
                pad_width=pad_width,
            )

            if style is None:
                report_preview(on_preview, frame_bytes)

            if style is not None and client is not None:
                try:
                    t = i / total if total > 1 else 0.0
                    current_style = style
                    svg_dest: Path | None = None
                    if end_style is not None and styles_compatible(style, end_style):
                        current_style = interpolate_style(style, end_style, t)

                    if job_folder is not None and src_path is not None:
                        lines_dest = job_folder.frame_path(output_stem, frame_num, "lines", pad_width=pad_width)
                        svg_dest = job_folder.frame_path(output_stem, frame_num, "svg", pad_width=pad_width)
                        result = apply_style(
                            client,
                            current_style,
                            str(src_path),
                            relative=relative_style,
                            style_mode=effective_style_mode,
                            save_lines_to=str(lines_dest) if not lines_dest.exists() else None,
                        )
                    else:
                        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                            tmp.write(frame_bytes)
                            tmp_path = Path(tmp.name)
                        try:
                            result = apply_style(
                                client,
                                current_style,
                                str(tmp_path),
                                relative=relative_style,
                                style_mode=effective_style_mode,
                            )
                        finally:
                            tmp_path.unlink(missing_ok=True)

                    svg_text = result if isinstance(result, str) else result.decode()
                    frame_bytes = svg_text.encode()

                    if svg_dest is not None and not svg_dest.exists():
                        svg_dest.write_text(svg_text, encoding="utf-8")

                    try:
                        fw, fh = estimate_svg_dimensions(svg_text)
                        preview_img = svg_to_pil(svg_text, fw, fh)
                        preview_buf = io.BytesIO()
                        preview_img.save(preview_buf, format="PNG")
                        report_preview(on_preview, preview_buf.getvalue())
                    except Exception:
                        pass
                except Exception:
                    logger.opt(exception=True).debug("Style failed on frame {}", frame_num)

            if job_folder is not None:
                jf_dest = job_folder.frame_path(output_stem, frame_num, ext, pad_width=pad_width)
                save_image_bytes(frame_bytes, jf_dest, fmt, multiplier)
            else:
                save_image_bytes(frame_bytes, out_dir / f"frame_{frame_num:06d}.{ext}", fmt, multiplier)

    # Copy all frames from job folder to output dir
    if job_folder is not None:
        all_frames = job_folder.existing_frames(output_stem, ext)
        for fn in sorted(all_frames):
            src_name = job_folder.frame_path(output_stem, fn, ext, pad_width=pad_width).name
            dest_name = f"frame_{fn:06d}.{ext}"
            job_folder.copy_to_output(src_name, out_dir / dest_name)

    report_progress(on_progress, total, total, "Done")


_process_video = process_video
_process_video_to_mp4 = process_video_to_mp4
_process_video_to_frames = process_video_to_frames
