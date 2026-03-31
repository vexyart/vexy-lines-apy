# this_file: vexy-lines-apy/src/vexy_lines_api/export/io.py

from __future__ import annotations

import io
import re
from pathlib import Path

from PIL import Image

from vexy_lines_api.video import svg_to_pil


def parse_size_multiplier(size: str) -> int:
    match = re.match(r"(\d+)x", size)
    return int(match.group(1)) if match else 1


def estimate_svg_dimensions(svg_string: str) -> tuple[int, int]:
    view_box = re.search(r'viewBox=["\'][\d.]+\s+[\d.]+\s+([\d.]+)\s+([\d.]+)', svg_string)
    if view_box:
        return int(float(view_box.group(1))), int(float(view_box.group(2)))
    width_match = re.search(r'width=["\'](\d+)', svg_string)
    height_match = re.search(r'height=["\'](\d+)', svg_string)
    width = int(width_match.group(1)) if width_match else 800
    height = int(height_match.group(1)) if height_match else 600
    return width, height


def save_image_bytes(data: bytes, dest: Path, fmt: str, multiplier: int = 1) -> None:
    if fmt == "SVG":
        dest.write_bytes(data)
        return
    image = Image.open(io.BytesIO(data))
    if multiplier > 1:
        image = image.resize((image.width * multiplier, image.height * multiplier), Image.Resampling.LANCZOS)
    pil_fmt = "JPEG" if fmt == "JPG" else fmt
    image.save(str(dest), format=pil_fmt)


def save_svg_as_image(svg_data: str | bytes, dest: Path, fmt: str, multiplier: int = 1) -> None:
    svg_text = svg_data if isinstance(svg_data, str) else svg_data.decode()
    width, height = estimate_svg_dimensions(svg_text)
    image = svg_to_pil(svg_text, width * multiplier, height * multiplier)
    pil_fmt = "JPEG" if fmt == "JPG" else fmt
    image.save(str(dest), format=pil_fmt)
