# this_file: vexy-lines-apy/src/vexy_lines_api/export/job.py
"""Persistent job folder for resumable export pipelines.

Instead of writing intermediate files to temp directories that vanish on
crash, a :class:`JobFolder` stores them next to the final output.  On
re-run the pipeline can skip frames / assets that already exist.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from loguru import logger

# Extensions recognised as single-file export targets (not directories).
_FILE_EXTENSIONS: frozenset[str] = frozenset({
    ".mp4", ".png", ".jpg", ".jpeg", ".svg", ".lines",
})


class JobFolder:
    """Manage a persistent folder of intermediate export artefacts.

    Args:
        output_path: The final output destination (file or directory).
        force: If ``True`` and the job folder already exists, delete it
            before creating a fresh one.
    """

    def __init__(self, output_path: str | Path, *, force: bool = False) -> None:
        output = Path(output_path).resolve()

        # Allow an env-var override for the job folder location.
        env_override = os.environ.get("VEXY_LINES_JOB_FOLDER")
        if env_override:
            self._path = Path(env_override).resolve()
        elif output.suffix.lower() in _FILE_EXTENSIONS:
            # File output: sibling folder  {parent}/{stem}-vljob/
            self._path = output.parent / f"{output.stem}-vljob"
        else:
            # Directory output: sibling folder  {path}-vljob/
            self._path = output.parent / f"{output.name}-vljob"

        self._output_stem = output.stem if output.suffix.lower() in _FILE_EXTENSIONS else output.name

        if force and self._path.exists():
            logger.info("Force-cleaning job folder: {}", self._path)
            shutil.rmtree(self._path)

        self._path.mkdir(parents=True, exist_ok=True)
        logger.debug("Job folder: {}", self._path)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def path(self) -> Path:
        """The job folder directory."""
        return self._path

    @property
    def output_stem(self) -> str:
        """Base name used for naming intermediate files."""
        return self._output_stem

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def asset_path(self, name: str, ext: str) -> Path:
        """Return ``{job_folder}/{name}.{ext}``."""
        return self._path / f"{name}.{ext}"

    def frame_path(self, name: str, frame_num: int, ext: str) -> Path:
        """Return ``{job_folder}/{name}--{frame_num}.{ext}`` (NOT zero-padded)."""
        return self._path / f"{name}--{frame_num}.{ext}"

    def existing_frames(self, name: str, ext: str) -> set[int]:
        """Scan the job folder for ``{name}--{N}.{ext}`` files.

        Returns:
            A set of frame numbers *N* already present on disk.
        """
        pattern = re.compile(rf"^{re.escape(name)}--(\d+)\.{re.escape(ext)}$")
        found: set[int] = set()
        if not self._path.exists():
            return found
        for entry in self._path.iterdir():
            m = pattern.match(entry.name)
            if m:
                found.add(int(m.group(1)))
        return found

    def copy_to_output(self, src_name: str, dest: str | Path) -> Path:
        """Copy *src_name* from the job folder to *dest*.

        Args:
            src_name: Filename (not path) inside the job folder.
            dest: Destination path.

        Returns:
            The resolved destination path.
        """
        src = self._path / src_name
        dst = Path(dest).resolve()
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return dst

    def cleanup(self) -> None:
        """Delete the entire job folder."""
        logger.info("Cleaning up job folder: {}", self._path)
        shutil.rmtree(self._path, ignore_errors=True)
