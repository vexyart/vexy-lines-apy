# this_file: vexy-lines-apy/tests/test_media.py

from __future__ import annotations

from unittest.mock import patch

from vexy_lines.types import LinesDocument
from vexy_lines_api.media import extract_preview_from_lines


class TestExtractPreviewFromLines:
    def test_returns_preview_bytes_when_present(self):
        doc = LinesDocument(preview_image_data=b"preview", source_image_data=b"source")
        with patch("vexy_lines.parse", return_value=doc):
            assert extract_preview_from_lines("test.lines") == b"preview"

    def test_returns_source_bytes_when_preview_missing(self):
        doc = LinesDocument(preview_image_data=None, source_image_data=b"source")
        with patch("vexy_lines.parse", return_value=doc):
            assert extract_preview_from_lines("test.lines") == b"source"

    def test_returns_none_when_parser_returns_no_embedded_images(self):
        with patch("vexy_lines.parse", return_value=LinesDocument()):
            assert extract_preview_from_lines("test.lines") is None

    def test_returns_none_when_parser_raises(self):
        with patch("vexy_lines.parse", side_effect=ValueError("bad lines")):
            assert extract_preview_from_lines("bad.lines") is None
