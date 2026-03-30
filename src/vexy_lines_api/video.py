# this_file: vexy-lines-apy/src/vexy_lines_api/video.py
"""Video processing and SVG rasterisation utilities.

Three public entry points:

- :func:`probe` — read frame count, FPS, dimensions, and audio presence.
- :func:`process_video` — re-encode with optional trim and scale (no style).
- :func:`process_video_with_style` — per-frame style transfer via the MCP API.

Per-frame pipeline in :func:`process_video_with_style`::

    av decode → PIL Image → PNG bytes → MCP apply_style → PIL Image → av encode

Heavy dependencies (``av``, ``resvg-py``, ``svglab``, ``opencv-python``) are
imported lazily inside each function, so importing this module is cheap.
"""

from __future__ import annotations

import io
import tempfile
from dataclasses import dataclass
from fractions import Fraction
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
# Probe
# ---------------------------------------------------------------------------


def probe(path: str) -> VideoInfo:
    """Read video metadata from *path* using PyAV.

    Args:
        path: Filesystem path to the video file.

    Returns:
        A :class:`VideoInfo` with the extracted metadata.

    Raises:
        ImportError: If ``av`` is not installed.
        RuntimeError: If the file cannot be opened or has no video stream.
    """
    try:
        import av  # type: ignore[import-untyped]
    except ImportError as exc:
        msg = "PyAV (av) is required for video probing: pip install av"
        raise ImportError(msg) from exc

    container = av.open(path)
    try:
        video_stream = container.streams.video[0]
        fps = float(video_stream.average_rate) if video_stream.average_rate else 30.0
        total_frames = video_stream.frames or 0
        duration = float(video_stream.duration * video_stream.time_base) if video_stream.duration else 0.0
        if total_frames == 0 and duration > 0:
            total_frames = int(duration * fps)

        has_audio = len(container.streams.audio) > 0

        return VideoInfo(
            width=video_stream.width,
            height=video_stream.height,
            fps=fps,
            total_frames=total_frames,
            duration=duration,
            has_audio=has_audio,
        )
    finally:
        container.close()


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

    Returns:
        A :class:`VideoInfo` for the *output* file.

    Raises:
        ImportError: If ``av`` is not installed.
    """
    try:
        import av  # type: ignore[import-untyped]
    except ImportError as exc:
        msg = "PyAV (av) is required for video processing: pip install av"
        raise ImportError(msg) from exc

    info = probe(input_path)
    actual_end = min(end_frame, info.total_frames) if end_frame is not None else info.total_frames

    in_container = av.open(input_path)
    out_container = av.open(output_path, mode="w")

    in_video = in_container.streams.video[0]
    out_width = in_video.width * size_multiplier
    out_height = in_video.height * size_multiplier

    fps_rational = Fraction(info.fps).limit_denominator(10000)
    out_video = out_container.add_stream("libx264", rate=fps_rational)
    out_video.width = out_width
    out_video.height = out_height
    out_video.pix_fmt = "yuv420p"

    # Audio passthrough (best-effort — skip on failure)
    out_audio = None
    if include_audio and info.has_audio:
        try:
            in_audio = in_container.streams.audio[0]
            out_audio = out_container.add_stream_from_template(in_audio)
        except Exception:
            logger.warning("Could not copy audio stream, proceeding without audio")
            out_audio = None

    frame_idx = 0
    for packet in in_container.demux():
        if abort_event and abort_event.is_set():
            break

        if packet.stream.type == "video":
            for frame in packet.decode():
                if abort_event and abort_event.is_set():
                    break
                if frame_idx < start_frame:
                    frame_idx += 1
                    continue
                if frame_idx >= actual_end:
                    break

                if size_multiplier > 1:
                    frame = frame.reformat(width=out_width, height=out_height)

                for out_packet in out_video.encode(frame):
                    out_container.mux(out_packet)

                frame_idx += 1

        elif packet.stream.type == "audio" and out_audio is not None:
            # Re-mux audio packets directly
            packet.stream = out_audio
            out_container.mux(packet)

    # Flush encoder
    for out_packet in out_video.encode():
        out_container.mux(out_packet)

    out_container.close()
    in_container.close()

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
        import av  # type: ignore[import-untyped]
    except ImportError as exc:
        msg = "PyAV (av) is required for video processing: pip install av"
        raise ImportError(msg) from exc

    from PIL import Image as PILImage

    from vexy_lines_api import MCPClient, apply_style, interpolate_style, styles_compatible

    info = probe(input_path)
    actual_end = min(end_frame, info.total_frames) if end_frame is not None else info.total_frames
    total = max(actual_end - start_frame, 1)

    in_container = av.open(input_path)
    out_container = av.open(output_path, mode="w")

    in_video = in_container.streams.video[0]
    out_width = in_video.width * size_multiplier
    out_height = in_video.height * size_multiplier

    fps_rational = Fraction(info.fps).limit_denominator(10000)
    out_video = out_container.add_stream("libx264", rate=fps_rational)
    out_video.width = out_width
    out_video.height = out_height
    out_video.pix_fmt = "yuv420p"

    out_audio = None
    if include_audio and info.has_audio:
        try:
            in_audio = in_container.streams.audio[0]
            out_audio = out_container.add_stream_from_template(in_audio)
        except Exception:
            logger.warning("Could not copy audio stream, proceeding without audio")
            out_audio = None

    frame_idx = 0
    with MCPClient() as client:
        for packet in in_container.demux():
            if abort_event and abort_event.is_set():
                break

            if packet.stream.type == "video":
                for frame in packet.decode():
                    if abort_event and abort_event.is_set():
                        break

                    if frame_idx < start_frame:
                        frame_idx += 1
                        continue
                    if frame_idx >= actual_end:
                        break

                    # Convert to PIL, save to temp file for MCP
                    pil_img = frame.to_image()
                    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                        pil_img.save(tmp, format="PNG")
                        tmp_path = tmp.name

                    # Apply style
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

                    # Convert back to av.VideoFrame
                    out_frame = av.VideoFrame.from_image(styled_img)
                    for out_packet in out_video.encode(out_frame):
                        out_container.mux(out_packet)

                    frame_idx += 1
                    if on_progress is not None:
                        on_progress(frame_idx - start_frame, total)

            elif packet.stream.type == "audio" and out_audio is not None:
                packet.stream = out_audio
                out_container.mux(packet)

    for out_packet in out_video.encode():
        out_container.mux(out_packet)

    out_container.close()
    in_container.close()

    return probe(output_path)
