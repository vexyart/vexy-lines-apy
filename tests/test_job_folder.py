# this_file: vexy-lines-apy/tests/test_job_folder.py
"""Tests for vexy_lines_api.export.job.JobFolder.

Covers path resolution, directory management, asset paths, frame
detection, copy-to-output, cleanup, and ExportRequest field defaults.
All filesystem operations use the tmp_path fixture.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vexy_lines_api.export.job import JobFolder
from vexy_lines_api.export.models import ExportRequest


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


class TestPathResolution:
    """Job folder location derived from the output path."""

    def test_job_folder_file_output_creates_sibling_dir(self, tmp_path: Path) -> None:
        out = tmp_path / "out" / "video.mp4"
        out.parent.mkdir(parents=True)
        jf = JobFolder(out)
        assert jf.path == tmp_path / "out" / "video-vljob"
        assert jf.path.is_dir()

    def test_job_folder_dir_output_creates_sibling_dir(self, tmp_path: Path) -> None:
        out = tmp_path / "output"
        out.mkdir()
        jf = JobFolder(out)
        assert jf.path == tmp_path / "output-vljob"
        assert jf.path.is_dir()

    def test_job_folder_env_override_when_env_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        override = tmp_path / "custom-job"
        monkeypatch.setenv("VEXY_LINES_JOB_FOLDER", str(override))
        out = tmp_path / "video.mp4"
        jf = JobFolder(out)
        assert jf.path == override.resolve()
        assert jf.path.is_dir()

    def test_job_folder_output_stem_for_file(self, tmp_path: Path) -> None:
        out = tmp_path / "video.mp4"
        jf = JobFolder(out)
        assert jf.output_stem == "video"

    def test_job_folder_output_stem_for_dir(self, tmp_path: Path) -> None:
        out = tmp_path / "output"
        out.mkdir()
        jf = JobFolder(out)
        assert jf.output_stem == "output"


# ---------------------------------------------------------------------------
# Directory management
# ---------------------------------------------------------------------------


class TestDirectoryManagement:
    """Job folder creation, force-delete, and preserve behaviour."""

    def test_job_folder_creates_directory_when_not_exists(self, tmp_path: Path) -> None:
        out = tmp_path / "render.png"
        jf = JobFolder(out)
        assert jf.path.is_dir()

    def test_job_folder_force_deletes_existing_when_force_true(self, tmp_path: Path) -> None:
        out = tmp_path / "render.mp4"
        # Pre-populate the job folder with a sentinel file.
        job_dir = tmp_path / "render-vljob"
        job_dir.mkdir()
        sentinel = job_dir / "old-file.txt"
        sentinel.write_text("old")

        jf = JobFolder(out, force=True)

        assert jf.path.is_dir()
        assert not sentinel.exists(), "force=True should have wiped the old folder"

    def test_job_folder_no_force_keeps_existing_when_force_false(self, tmp_path: Path) -> None:
        out = tmp_path / "render.mp4"
        job_dir = tmp_path / "render-vljob"
        job_dir.mkdir()
        sentinel = job_dir / "existing.txt"
        sentinel.write_text("keep me")

        jf = JobFolder(out, force=False)

        assert jf.path.is_dir()
        assert sentinel.exists(), "force=False should preserve existing files"
        assert sentinel.read_text() == "keep me"


# ---------------------------------------------------------------------------
# Asset paths
# ---------------------------------------------------------------------------


class TestAssetPaths:
    """asset_path and frame_path helpers."""

    def test_asset_path_returns_correct_path(self, tmp_path: Path) -> None:
        jf = JobFolder(tmp_path / "video.mp4")
        result = jf.asset_path("thumbnail", "png")
        assert result == jf.path / "thumbnail.png"

    def test_frame_path_not_zero_padded(self, tmp_path: Path) -> None:
        jf = JobFolder(tmp_path / "video.mp4")
        assert jf.frame_path("video", 1, "png") == jf.path / "video--1.png"
        assert jf.frame_path("video", 42, "png") == jf.path / "video--42.png"
        assert jf.frame_path("video", 1000, "png") == jf.path / "video--1000.png"


# ---------------------------------------------------------------------------
# Frame detection
# ---------------------------------------------------------------------------


class TestExistingFrames:
    """existing_frames scans for {name}--{N}.{ext} files."""

    def test_existing_frames_empty_folder_returns_empty_set(self, tmp_path: Path) -> None:
        jf = JobFolder(tmp_path / "video.mp4")
        assert jf.existing_frames("video", "png") == set()

    def test_existing_frames_finds_matching_files(self, tmp_path: Path) -> None:
        jf = JobFolder(tmp_path / "video.mp4")
        # Write frame files directly into the job folder.
        (jf.path / "video--1.png").write_bytes(b"")
        (jf.path / "video--5.png").write_bytes(b"")
        (jf.path / "video--23.png").write_bytes(b"")

        result = jf.existing_frames("video", "png")
        assert result == {1, 5, 23}

    def test_existing_frames_ignores_wrong_pattern(self, tmp_path: Path) -> None:
        jf = JobFolder(tmp_path / "video.mp4")
        # Wrong extension, wrong separator, wrong name.
        (jf.path / "video--1.jpg").write_bytes(b"")    # wrong ext
        (jf.path / "video-1.png").write_bytes(b"")     # single dash
        (jf.path / "other--1.png").write_bytes(b"")    # wrong name
        (jf.path / "video--1.png").write_bytes(b"")    # correct

        result = jf.existing_frames("video", "png")
        assert result == {1}


# ---------------------------------------------------------------------------
# Src frame paths
# ---------------------------------------------------------------------------


class TestFrameSrcPath:
    """frame_src_path returns {name}--{N}-src.{ext} paths."""

    def test_frame_src_path_format(self, tmp_path: Path) -> None:
        jf = JobFolder(tmp_path / "video.mp4")
        assert jf.frame_src_path("video", 1, "png") == jf.path / "video--1-src.png"
        assert jf.frame_src_path("video", 42, "png") == jf.path / "video--42-src.png"


class TestExistingSrcFrames:
    """existing_src_frames scans for {name}--{N}-src.{ext} files."""

    def test_existing_src_frames_finds_matching(self, tmp_path: Path) -> None:
        jf = JobFolder(tmp_path / "video.mp4")
        (jf.path / "video--1-src.png").write_bytes(b"")
        (jf.path / "video--5-src.png").write_bytes(b"")
        result = jf.existing_src_frames("video", "png")
        assert result == {1, 5}

    def test_existing_src_frames_ignores_styled_frames(self, tmp_path: Path) -> None:
        jf = JobFolder(tmp_path / "video.mp4")
        (jf.path / "video--1.png").write_bytes(b"")  # styled, not src
        (jf.path / "video--2-src.png").write_bytes(b"")  # src
        result = jf.existing_src_frames("video", "png")
        assert result == {2}


# ---------------------------------------------------------------------------
# Copy to output
# ---------------------------------------------------------------------------


class TestCopyToOutput:
    """copy_to_output copies a file from the job folder to a destination."""

    def test_copy_to_output_copies_file_and_creates_parent_dirs(self, tmp_path: Path) -> None:
        jf = JobFolder(tmp_path / "video.mp4")
        src_name = "final.mp4"
        src = jf.path / src_name
        src.write_bytes(b"video-data")

        dest = tmp_path / "deep" / "nested" / "output.mp4"
        returned = jf.copy_to_output(src_name, dest)

        assert returned == dest.resolve()
        assert dest.exists()
        assert dest.read_bytes() == b"video-data"


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


class TestCleanup:
    """cleanup() removes the entire job folder."""

    def test_cleanup_removes_folder(self, tmp_path: Path) -> None:
        jf = JobFolder(tmp_path / "video.mp4")
        assert jf.path.is_dir()
        (jf.path / "frame--1.png").write_bytes(b"")

        jf.cleanup()

        assert not jf.path.exists()

    def test_cleanup_is_idempotent_when_folder_already_gone(self, tmp_path: Path) -> None:
        """cleanup() with ignore_errors=True should not raise if folder is missing."""
        jf = JobFolder(tmp_path / "video.mp4")
        jf.cleanup()
        # Second call must not raise.
        jf.cleanup()


# ---------------------------------------------------------------------------
# ExportRequest model fields
# ---------------------------------------------------------------------------


class TestExportRequest:
    """ExportRequest dataclass includes force and cleanup with correct defaults."""

    def _make_request(self, **overrides) -> ExportRequest:
        defaults = dict(
            mode="video",
            input_paths=["/tmp/input.lines"],
            style_path=None,
            end_style_path=None,
            output_path="/tmp/output.mp4",
            format="MP4",
            size="1920x1080",
        )
        defaults.update(overrides)
        return ExportRequest(**defaults)

    def test_export_request_force_defaults_to_false(self) -> None:
        req = self._make_request()
        assert req.force is False

    def test_export_request_cleanup_defaults_to_false(self) -> None:
        req = self._make_request()
        assert req.cleanup is False

    def test_export_request_force_can_be_set_true(self) -> None:
        req = self._make_request(force=True)
        assert req.force is True

    def test_export_request_cleanup_can_be_set_true(self) -> None:
        req = self._make_request(cleanup=True)
        assert req.cleanup is True

    def test_export_request_is_frozen(self) -> None:
        req = self._make_request()
        with pytest.raises((AttributeError, TypeError)):
            req.force = True  # type: ignore[misc]
