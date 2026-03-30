# this_file: vexy-lines-apy/src/vexy_lines_api/video.py
"""Video processing and SVG rasterisation utilities.

Three public entry points:

- :func:`probe` — read frame count, FPS, dimensions, and audio presence.
- :func:`process_video` — re-encode with optional trim and scale (no style).
- :func:`process_video_with_style` — per-frame style transfer via the MCP API.

Per-frame pipeline in :func:`process_video_with_style`::

    cv2 decode → PIL Image → PNG bytes → MCP apply_style → PIL Image → cv2 encode

Heavy dependencies (``opencv-python-headless``, ``resvg-py``, ``Pillow``) are
imported lazily inside each function, so importing this module is cheap.
"""

from __future__ import annotations

import io
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from PIL import Image

__all__ = [
    "VideoInfo",
    "svg_to_pil",
    "probe",
    "process_video",
    "process_video_with_style",
]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VideoInfo:
    """Metadata extracted from a video file.

    Attributes:
        width: Frame width in pixels.
        height: Frame height in pixels.
        fps: Frames per second.
        total_frames: Total number of frames.
        duration: Duration in seconds.
        has_audio: Whether the file contains an audio stream.
    """

    width: int
    height: int
    fps: float
    total_frames: int
    duration: float
    has_audio: bool


# ---------------------------------------------------------------------------
# Private helpers — audio detection & merging via subprocess
# ---------------------------------------------------------------------------


def _detect_audio(path: str) -> bool:
    """Detect whether *path* contains an audio stream (best-effort via ffprobe)."""
    import shutil  # noqa: PLC0415
    import subprocess  # noqa: PLC0415

    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return False
    try:
        result = subprocess.run(
            [ffprobe, "-v", "quiet", "-select_streams", "a",
             "-show_entries", "stream=index", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=10,
        )
        return bool(result.stdout.strip())
    except Exception:  # noqa: BLE001
        return False


def _merge_audio(video_only: str, audio_source: str, output_path: str) -> None:
    """Merge audio from *audio_source* into *video_only*, writing to *output_path*.

    Falls back to using the video-only file if ffmpeg is unavailable or fails.
    """
    import shutil  # noqa: PLC0415
    import subprocess  # noqa: PLC0415

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        logger.warning("ffmpeg not found; output will have no audio")
        shutil.move(video_only, output_path)
        return
    try:
        subprocess.run(
            [ffmpeg, "-y",
             "-i", video_only,
             "-i", audio_source,
             "-c:v", "copy", "-c:a", "aac",
             "-map", "0:v:0", "-map", "1:a:0",
             "-shortest", output_path],
            capture_output=True, timeout=300, check=True,
        )
    except Exception:  # noqa: BLE001
        logger.warning("Audio merge failed; using video-only output")
        shutil.move(video_only, output_path)


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------


def probe(path: str) -> VideoInfo:
    """Read video metadata from *path* using OpenCV.

    Audio detection requires ``ffprobe`` on PATH; when unavailable,
    :attr:`VideoInfo.has_audio` will be ``False``.

    Args:
        path: Filesystem path to the video file.

    Returns:
        A :class:`VideoInfo` with the extracted metadata.

    Raises:
        ImportError: If ``opencv-python-headless`` is not installed.
        RuntimeError: If the file cannot be opened or has no video stream.
    """
    try:
        import cv2  # type: ignore[import-untyped]  # noqa: PLC0415
    except ImportError as exc:
        msg = "opencv-python-headless is required for video probing: pip install opencv-python-headless"
        raise ImportError(msg) from exc

    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        msg = f"Cannot open video file: {path}"
        raise RuntimeError(msg)
    try:
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        duration = total_frames / fps if fps > 0 else 0.0
    finally:
        cap.release()

    return VideoInfo(
        width=width,
        height=height,
        fps=fps,
        total_frames=total_frames,
        duration=duration,
        has_audio=_detect_audio(path),
    )


# ---------------------------------------------------------------------------
# SVG rasterisation
# ---------------------------------------------------------------------------


def svg_to_pil(svg_string: str, width: int, height: int) -> Image.Image:
    """Rasterise an SVG string to a PIL Image via ``resvg_py``.

    Patches mm dimensions to px (resvg cannot parse mm units), then
    calls ``resvg_py.svg_to_bytes`` directly with the SVG string.
    Falls back to a blank white image if resvg_py is not installed.

    Args:
        svg_string: The SVG markup.
        width: Target pixel width.
        height: Target pixel height.

    Returns:
        A PIL ``Image.Image`` in RGBA mode.
    """
    import re  # noqa: PLC0415

    from PIL import Image as _PILImage  # noqa: PLC0415

    try:
        import resvg_py  # type: ignore[import-untyped]  # noqa: PLC0415

        # Patch mm dimensions to px (resvg cannot parse mm units)
        svg_fixed = re.sub(r'width="[^"]*mm"', f'width="{width}px"', svg_string, count=1)
        svg_fixed = re.sub(r'height="[^"]*mm"', f'height="{height}px"', svg_fixed, count=1)

        png_bytes = resvg_py.svg_to_bytes(svg_fixed)
        img = _PILImage.open(io.BytesIO(bytes(png_bytes)))
        if img.size != (width, height):
            img = img.resize((width, height), _PILImage.Resampling.LANCZOS)
        return img.convert("RGBA")
    except ImportError:
        pass
    except Exception:
        logger.opt(exception=True).debug("resvg_py rasterisation failed")

    # Fallback: blank image
    logger.warning("No SVG rasteriser available; returning blank {}x{} image", width, height)
    return _PILImage.new("RGBA", (width, height), (255, 255, 255, 255))


# ---------------------------------------------------------------------------
# Video processing
# ---------------------------------------------------------------------------


def _create_video_writer(
    path: str, fps: float, width: int, height: int,
) -> Any:
    """Create a cv2.VideoWriter, trying H.264 (avc1) first, falling back to mp4v."""
    import cv2  # type: ignore[import-untyped]  # noqa: PLC0415

    for fourcc_code in ("avc1", "mp4v"):
        fourcc = cv2.VideoWriter_fourcc(*fourcc_code)
        writer = cv2.VideoWriter(path, fourcc, fps, (width, height))
        if writer.isOpened():
            return writer
        writer.release()

    msg = f"Cannot create video writer for: {path}"
    raise RuntimeError(msg)


def process_video(
    input_path: str,
    output_path: str,
    *,
    start_frame: int = 0,
    end_frame: int | None = None,
    include_audio: bool = True,
    size_multiplier: int = 1,
    abort_event: Any = None,
) -> VideoInfo:
    """Basic pass-through video processing (no style transfer).

    Re-encodes the video, optionally trimming to a frame range and scaling.

    Args:
        input_path: Source video path.
        output_path: Destination video path.
        start_frame: First frame to include.
        end_frame: Last frame (exclusive), or ``None`` for all.
        include_audio: Copy the audio stream if present.
        size_multiplier: Integer scale factor for output resolution.
        abort_event: Optional threading.Event to stop processing early.

    Returns:
        A :class:`VideoInfo` for the *output* file.

    Raises:
        ImportError: If ``opencv-python-headless`` is not installed.
    """
    try:
        import cv2  # type: ignore[import-untyped]  # noqa: PLC0415
    except ImportError as exc:
        msg = "opencv-python-headless is required for video processing: pip install opencv-python-headless"
        raise ImportError(msg) from exc

    info = probe(input_path)
    actual_end = min(end_frame, info.total_frames) if end_frame is not None else info.total_frames

    out_width = info.width * size_multiplier
    out_height = info.height * size_multiplier

    # Decide whether to write to a temp file (audio merge needed) or directly
    needs_audio = include_audio and info.has_audio
    tmp_dir: str | None = None
    if needs_audio:
        tmp_dir = tempfile.mkdtemp(prefix="vexy_video_")
        video_only_path = str(Path(tmp_dir) / "video_only.mp4")
    else:
        video_only_path = output_path

    cap = cv2.VideoCapture(input_path)
    writer = _create_video_writer(video_only_path, info.fps, out_width, out_height)
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        frame_idx = start_frame

        while True:
            if abort_event and abort_event.is_set():
                break
            ret, frame = cap.read()
            if not ret or frame_idx >= actual_end:
                break

            if size_multiplier > 1:
                frame = cv2.resize(frame, (out_width, out_height), interpolation=cv2.INTER_LANCZOS4)

            writer.write(frame)
            frame_idx += 1
    finally:
        cap.release()
        writer.release()

    # Audio merge pass
    if needs_audio and tmp_dir is not None:
        try:
            _merge_audio(video_only_path, input_path, output_path)
        finally:
            import shutil  # noqa: PLC0415

            shutil.rmtree(tmp_dir, ignore_errors=True)

    return probe(output_path)


def process_video_with_style(
    input_path: str,
    output_path: str,
    *,
    style: Any = None,
    end_style: Any = None,
    start_frame: int = 0,
    end_frame: int | None = None,
    include_audio: bool = True,
    size_multiplier: int = 1,
    relative: bool = False,
    abort_event: Any = None,
    on_progress: Any = None,
) -> VideoInfo:
    """Process a video with per-frame style transfer.

    Each frame is encoded to PNG, styled via the MCP API, and then written
    to the output video.  If *end_style* is provided, the style is
    interpolated linearly across the frame range.

    Args:
        input_path: Source video path.
        output_path: Destination video path.
        style: A ``Style`` object from ``vexy_lines_api``, or ``None``.
        end_style: Optional end ``Style`` for interpolation.
        start_frame: First frame to include.
        end_frame: Last frame (exclusive), or ``None`` for all.
        include_audio: Copy the audio stream if present.
        size_multiplier: Integer scale factor for output resolution.
        relative: Scale spatial fill parameters to match the target frame
            dimensions.  Default ``False`` (absolute mode).
        abort_event: Optional threading.Event to stop processing early.
        on_progress: Optional callback ``(current, total) -> None``
            invoked after each frame is processed.

    Returns:
        A :class:`VideoInfo` for the output file.
    """
    if style is None:
        return process_video(
            input_path,
            output_path,
            start_frame=start_frame,
            end_frame=end_frame,
            include_audio=include_audio,
            size_multiplier=size_multiplier,
            abort_event=abort_event,
        )

    try:
        import cv2  # type: ignore[import-untyped]  # noqa: PLC0415
    except ImportError as exc:
        msg = "opencv-python-headless is required for video processing: pip install opencv-python-headless"
        raise ImportError(msg) from exc

    import numpy as np  # noqa: PLC0415
    from PIL import Image as PILImage  # noqa: PLC0415

    from vexy_lines_api import MCPClient, apply_style, interpolate_style, styles_compatible

    info = probe(input_path)
    actual_end = min(end_frame, info.total_frames) if end_frame is not None else info.total_frames
    total = max(actual_end - start_frame, 1)

    out_width = info.width * size_multiplier
    out_height = info.height * size_multiplier

    # Decide whether to write to a temp file (audio merge needed) or directly
    needs_audio = include_audio and info.has_audio
    tmp_dir: str | None = None
    if needs_audio:
        tmp_dir = tempfile.mkdtemp(prefix="vexy_video_")
        video_only_path = str(Path(tmp_dir) / "video_only.mp4")
    else:
        video_only_path = output_path

    cap = cv2.VideoCapture(input_path)
    writer = _create_video_writer(video_only_path, info.fps, out_width, out_height)
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        frame_idx = start_frame

        with MCPClient() as client:
            while True:
                if abort_event and abort_event.is_set():
                    break
                ret, frame = cap.read()
                if not ret or frame_idx >= actual_end:
                    break

                # Convert BGR frame to PIL Image
                pil_img = PILImage.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

                # Save to temp file for MCP
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    pil_img.save(tmp, format="PNG")
                    tmp_path = tmp.name

                # Interpolate style across frame range
                t = (frame_idx - start_frame) / total
                current_style = style
                if end_style is not None and styles_compatible(style, end_style):
                    current_style = interpolate_style(style, end_style, t)

                try:
                    svg_string = apply_style(client, current_style, tmp_path, relative=relative)
                    styled_img = svg_to_pil(svg_string, out_width, out_height).convert("RGB")
                except Exception:
                    logger.opt(exception=True).debug("Style failed on frame {}", frame_idx)
                    styled_img = pil_img.convert("RGB")
                finally:
                    Path(tmp_path).unlink(missing_ok=True)

                if size_multiplier > 1:
                    styled_img = styled_img.resize((out_width, out_height), PILImage.Resampling.LANCZOS)

                # Convert PIL back to BGR numpy array for cv2
                styled_bgr = cv2.cvtColor(np.array(styled_img), cv2.COLOR_RGB2BGR)
                writer.write(styled_bgr)

                frame_idx += 1
                if on_progress is not None:
                    on_progress(frame_idx - start_frame, total)
    finally:
        cap.release()
        writer.release()

    # Audio merge pass
    if needs_audio and tmp_dir is not None:
        try:
            _merge_audio(video_only_path, input_path, output_path)
        finally:
            import shutil  # noqa: PLC0415

            shutil.rmtree(tmp_dir, ignore_errors=True)

    return probe(output_path)
