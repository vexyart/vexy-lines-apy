# Changelog

## 2026-04-01 — Job Folder System (Issue #617)

- **feat**: New `JobFolder` class in `export/job.py` — persistent intermediate file storage alongside output, replacing temp directories. Supports resume, force-clean, and cleanup modes.
- **feat**: `ExportRequest` gains `force` and `cleanup` fields for controlling job folder lifecycle.
- **feat**: `apply_style()` gains `save_lines_to` parameter — saves the styled `.lines` document to a specified path during style transfer.
- **feat**: All export processors (lines, images, video) now save the complete artifact chain to the job folder: `.lines` → `.svg` → final format (`.png`/`.jpg`/`.mp4`).
- **feat**: Video export now extracts all requested source frames into the job folder before styling or assembly, then reuses those cached raw frames for resume.
- **feat**: Source video frames now live under `src/` with the `src--` prefix (`src/src--{stem}--{NNN}.png`), and job-folder frame artifacts use zero-padded numbering derived from the video's total frame count.
- **feat**: `VEXY_LINES_JOB_FOLDER` environment variable overrides computed job folder path.
- **test**: 24 new tests for `JobFolder` — path resolution, frame naming, resume detection, force/cleanup, copy-to-output.

## Previous releases

See [GitHub releases](https://github.com/vexyart/vexy-lines-apy/releases) for earlier versions.
