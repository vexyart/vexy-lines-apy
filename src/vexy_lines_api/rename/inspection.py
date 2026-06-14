# this_file: vexy-lines-apy/src/vexy_lines_api/rename/inspection.py
"""Build "inspection images" that help a VLM locate a single fill.

A single-fill render shows only one fill's strokes on a white canvas. To make
it easy for a vision model to say *what* and *where* the fill is, we:

1. find the bounding box of the visible (non-white) content,
2. superimpose the full, all-fills render at low opacity for context,
3. draw a thick red rectangle around the bounding box.

Everything here is pure Pillow image processing — no app or network needed.
"""

from __future__ import annotations

import io

from PIL import Image, ImageChops, ImageDraw

_WHITE = (255, 255, 255)


def _load(data: bytes | Image.Image) -> Image.Image:
    """Return an RGB :class:`PIL.Image.Image` from PNG bytes or an image."""
    if isinstance(data, Image.Image):
        return data.convert("RGB")
    return Image.open(io.BytesIO(data)).convert("RGB")


def content_bbox(
    image: bytes | Image.Image,
    *,
    bg: tuple[int, int, int] = _WHITE,
    threshold: int = 16,
) -> tuple[int, int, int, int] | None:
    """Return the bounding box of visible content, or ``None`` if blank.

    Visible content is any pixel that differs from the background colour by
    more than *threshold* in any channel. The box is ``(left, top, right,
    bottom)`` in pixel coordinates (right/bottom exclusive, matching Pillow's
    :meth:`PIL.Image.Image.getbbox`).

    Args:
        image: Single-fill render as PNG bytes or a PIL image.
        bg: Background colour to treat as empty (default white).
        threshold: Per-channel difference above which a pixel counts as content.

    Returns:
        ``(left, top, right, bottom)`` or ``None`` when nothing is visible.
    """
    rgb = _load(image)
    background = Image.new("RGB", rgb.size, bg)
    diff = ImageChops.difference(rgb, background).convert("L")
    # Binarise via a 256-entry lookup table (faster and better-typed than a lambda).
    lut = [255 if value > threshold else 0 for value in range(256)]
    mask = diff.point(lut)
    return mask.getbbox()


def make_inspection_image(
    single_fill: bytes | Image.Image,
    full_filled: bytes | Image.Image,
    *,
    overlay_opacity: float = 0.2,
    rect_color: tuple[int, int, int] = (255, 0, 0),
    rect_width: int = 5,
    bg: tuple[int, int, int] = _WHITE,
    threshold: int = 16,
) -> bytes:
    """Compose an inspection image for one fill.

    Starts from the *single_fill* render, blends the *full_filled* render on
    top at *overlay_opacity*, then draws a *rect_width*-px rectangle in
    *rect_color* around the bounding box of the single fill's visible content.
    When the single fill is blank, the rectangle frames the whole image.

    Args:
        single_fill: Render with only the target fill visible (PNG bytes/image).
        full_filled: Render with all fills visible (PNG bytes/image).
        overlay_opacity: Opacity of the full render overlay, ``0.0`` to ``1.0``.
        rect_color: RGB colour of the bounding-box rectangle.
        rect_width: Rectangle line thickness in pixels.
        bg: Background colour used for bounding-box detection.
        threshold: Per-channel content-detection threshold.

    Returns:
        PNG-encoded bytes of the inspection image.
    """
    base = _load(single_fill)
    width, height = base.size

    box = content_bbox(base, bg=bg, threshold=threshold)

    overlay = _load(full_filled)
    if overlay.size != base.size:
        overlay = overlay.resize(base.size, Image.Resampling.LANCZOS)

    opacity = max(0.0, min(1.0, overlay_opacity))
    blended = Image.blend(base, overlay, opacity)

    draw = ImageDraw.Draw(blended)
    if box is None:
        box = (0, 0, width, height)
    left, top, right, bottom = box
    # Clamp the (right, bottom)-exclusive box to the last drawable pixel.
    right = min(right, width - 1)
    bottom = min(bottom, height - 1)
    draw.rectangle((left, top, right, bottom), outline=rect_color, width=rect_width)

    buf = io.BytesIO()
    blended.save(buf, format="PNG")
    return buf.getvalue()
