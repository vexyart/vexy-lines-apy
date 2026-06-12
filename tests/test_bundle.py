# this_file: vexy-lines-apy/tests/test_bundle.py
"""Tests for vexy_lines_api.bundle.export_bundle."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from vexy_lines_api.bundle import _wait_for_file, export_bundle


class TestExportBundleValidation:
    def test_export_bundle_when_unknown_format_then_raises(self, tmp_path):
        f = tmp_path / "art.lines"
        f.write_bytes(b"x")
        with pytest.raises(ValueError, match="Unsupported formats"):
            export_bundle(f, formats=("bmp",))

    def test_export_bundle_when_missing_source_then_raises(self, tmp_path):
        f = tmp_path / "art.lines"
        f.write_text("<Document></Document>")
        with pytest.raises((FileNotFoundError, ValueError)):
            export_bundle(f, formats=(), source=True)

    def test_export_bundle_when_no_formats_no_source_then_empty(self, tmp_path):
        f = tmp_path / "art.lines"
        f.write_bytes(b"x")
        assert export_bundle(f, formats=(), source=False) == {}


class TestExportBundleFormats:
    def test_export_bundle_when_pdf_and_svg_then_exports_both(self, tmp_path):
        f = tmp_path / "art.lines"
        f.write_bytes(b"x")
        svg_path = tmp_path / "art.svg"
        pdf_path = tmp_path / "art.pdf"

        client = MagicMock()

        def fake_pdf(path, dpi=None):  # noqa: ARG001
            Path(path).write_bytes(b"%PDF-fake")
            return Path(path)

        def fake_svg(path, dpi=None):  # noqa: ARG001
            Path(path).write_text("<svg/>")
            return Path(path)

        client.export_pdf.side_effect = fake_pdf
        client.export_svg.side_effect = fake_svg

        results = export_bundle(f, formats=("pdf", "svg"), source=False, client=client)

        client.open_document.assert_called_once_with(str(f))
        client.render.assert_called_once()
        assert results["pdf"] == pdf_path
        assert results["svg"] == svg_path

    def test_export_bundle_when_png_then_rasterizes_svg_locally(self, tmp_path):
        f = tmp_path / "art.lines"
        f.write_bytes(b"x")

        client = MagicMock()

        def fake_svg(path, dpi=None):  # noqa: ARG001
            Path(path).write_text('<svg viewBox="0 0 10 10"/>')
            return Path(path)

        client.export_svg.side_effect = fake_svg

        def fake_save(svg, dest, fmt, multiplier=1):  # noqa: ARG001
            Path(dest).write_bytes(b"\x89PNG")

        with patch("vexy_lines_api.export.io.save_svg_as_image") as save:
            save.side_effect = fake_save
            results = export_bundle(f, formats=("png",), source=False, client=client)

        assert results["png"] == tmp_path / "art.png"
        assert results["png"].exists()
        # SVG was an intermediate only — not requested, so removed
        assert not (tmp_path / "art.svg").exists()
        client.export_pdf.assert_not_called()


class TestWaitForFile:
    def test_wait_for_file_when_stable_then_returns(self, tmp_path):
        f = tmp_path / "out.pdf"
        f.write_bytes(b"data")
        _wait_for_file(f, timeout=2.0, poll=0.05)  # should not raise

    def test_wait_for_file_when_never_appears_then_raises(self, tmp_path):
        with pytest.raises(TimeoutError, match="did not complete"):
            _wait_for_file(tmp_path / "never.pdf", timeout=0.3, poll=0.05)

    def test_export_bundle_when_input_missing_then_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="No such .lines file"):
            export_bundle(tmp_path / "ghost.lines", formats=("pdf",), source=False, client=MagicMock())
