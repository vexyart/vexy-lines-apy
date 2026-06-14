# this_file: vexy-lines-apy/tests/test_rename_inspection.py
"""Tests for vexy_lines_api.rename.inspection."""

from __future__ import annotations

import io

from PIL import Image

from vexy_lines_api.rename.inspection import content_bbox, make_inspection_image


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _white(size=(100, 100)) -> Image.Image:
    return Image.new("RGB", size, (255, 255, 255))


def test_content_bbox_when_blank_then_none():
    assert content_bbox(_png(_white())) is None


def test_content_bbox_when_black_square_then_tight_box():
    img = _white()
    for x in range(20, 40):
        for y in range(30, 50):
            img.putpixel((x, y), (0, 0, 0))
    box = content_bbox(_png(img))
    assert box == (20, 30, 40, 50)


def test_content_bbox_when_colored_content_then_detected():
    img = _white()
    for x in range(10, 15):
        for y in range(10, 15):
            img.putpixel((x, y), (255, 0, 0))  # red differs from white
    assert content_bbox(_png(img)) == (10, 10, 15, 15)


def test_content_bbox_when_below_threshold_then_ignored():
    img = _white()
    img.putpixel((5, 5), (250, 250, 250))  # diff of 5 < default threshold 16
    assert content_bbox(_png(img)) is None


def test_make_inspection_image_returns_png_same_size():
    single = _white()
    single.putpixel((50, 50), (0, 0, 0))
    full = Image.new("RGB", (100, 100), (200, 200, 200))
    out = make_inspection_image(_png(single), _png(full))
    result = Image.open(io.BytesIO(out))
    assert result.format == "PNG"
    assert result.size == (100, 100)


def test_make_inspection_image_draws_red_rectangle():
    single = _white()
    # content block at (40..60, 40..60)
    for x in range(40, 60):
        for y in range(40, 60):
            single.putpixel((x, y), (0, 0, 0))
    full = _white()
    out = make_inspection_image(_png(single), _png(full), rect_width=3)
    result = Image.open(io.BytesIO(out)).convert("RGB")
    # The rectangle outline near (40,40) should contain strongly-red pixels.
    found_red = any(result.getpixel((x, 40))[0] > 200 and result.getpixel((x, 40))[1] < 80 for x in range(38, 62))
    assert found_red


def test_make_inspection_image_resizes_mismatched_overlay():
    single = _white((120, 80))
    single.putpixel((10, 10), (0, 0, 0))
    full = Image.new("RGB", (60, 40), (100, 100, 100))  # different size
    out = make_inspection_image(_png(single), _png(full))
    result = Image.open(io.BytesIO(out))
    assert result.size == (120, 80)


def test_make_inspection_image_when_blank_single_then_frames_whole():
    single = _white((50, 50))
    full = _white((50, 50))
    # Should not raise and should produce a valid image even with no content.
    out = make_inspection_image(_png(single), _png(full))
    assert Image.open(io.BytesIO(out)).size == (50, 50)


def test_make_inspection_image_accepts_pil_images():
    single = _white()
    single.putpixel((25, 25), (0, 0, 0))
    full = _white()
    out = make_inspection_image(single, full)
    assert Image.open(io.BytesIO(out)).size == (100, 100)
