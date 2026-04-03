# this_file: vexy-lines-apy/src/vexy_lines_api/media.py

from __future__ import annotations

import cv2
from PIL import Image


def truncate_start(text: str, max_chars: int = 60) -> str:
    if len(text) <= max_chars:
        return text
    return f"...{text[-(max_chars - 3) :]}"


def extract_preview_from_lines(filepath: str) -> bytes | None:
    try:
        from vexy_lines import parse  # noqa: PLC0415

        doc = parse(filepath)
        return doc.preview_image_data or doc.source_image_data
    except Exception:
        return None


def extract_frame(video_path: str, frame_number: int = 1) -> Image.Image | None:
    try:
        cap = cv2.VideoCapture(video_path)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number - 1)
        ret, frame = cap.read()
        cap.release()
        if not ret:
            return None
        return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    except Exception:
        return None


def fit_image_to_box(image: Image.Image, width: int, height: int) -> Image.Image:
    img_w, img_h = image.size
    ratio = min(width / img_w, height / img_h)
    new_w = max(1, int(img_w * ratio))
    new_h = max(1, int(img_h * ratio))

    fitted = image.resize((new_w, new_h), Image.Resampling.LANCZOS)
    if fitted.mode == "RGBA":
        white = Image.new("RGBA", fitted.size, (255, 255, 255, 255))
        fitted = Image.alpha_composite(white, fitted)
    return fitted.convert("RGB")
