"""Video export regression coverage for job-folder frame extraction."""

# this_file: vexy-lines-apy/tests/test_export_video.py

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from PIL import Image

from vexy_lines_api.export.job import JobFolder
from vexy_lines_api.export.video import process_video_to_frames, process_video_to_mp4


class _FakeCapture:
    def __init__(self, frames: list[np.ndarray]) -> None:
        self._frames = frames
        self._index = 0

    def set(self, _prop: int, value: int) -> bool:
        self._index = int(value)
        return True

    def read(self) -> tuple[bool, np.ndarray | None]:
        if self._index >= len(self._frames):
            return False, None
        frame = self._frames[self._index]
        self._index += 1
        return True, frame.copy()

    def release(self) -> None:
        return None


class _FakeWriter:
    def __init__(self, output_path: Path) -> None:
        self.output_path = output_path
        self.frames: list[np.ndarray] = []

    def write(self, frame: np.ndarray) -> None:
        self.frames.append(frame.copy())

    def release(self) -> None:
        self.output_path.write_bytes(b"fake-mp4")


def _encode_png(_ext: str, frame: np.ndarray) -> tuple[bool, np.ndarray]:
    image = Image.fromarray(frame[:, :, ::-1])
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return True, np.frombuffer(buffer.getvalue(), dtype=np.uint8)


def test_process_video_to_frames_when_job_folder_used_then_extracts_src_first_with_padded_names(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from vexy_lines_api.export import video as video_module

    frames = [np.full((2, 3, 3), fill_value=index, dtype=np.uint8) for index in range(12)]
    output_dir = tmp_path / "frames"
    job_folder = JobFolder(output_dir)

    monkeypatch.setattr(
        video_module,
        "probe",
        lambda _path: type(
            "VideoInfoStub",
            (),
            {"total_frames": 12, "width": 3, "height": 2, "fps": 24.0, "has_audio": False},
        )(),
    )
    monkeypatch.setattr(video_module.cv2, "VideoCapture", lambda _path: _FakeCapture(frames))
    monkeypatch.setattr(video_module.cv2, "imencode", _encode_png)

    original_save_image_bytes = video_module.save_image_bytes

    def _assert_extract_first(data: bytes, dest: Path, fmt: str, multiplier: int = 1) -> None:
        assert job_folder.existing_src_frames(job_folder.output_stem, "png") == {1, 2, 3}
        original_save_image_bytes(data, dest, fmt, multiplier)

    monkeypatch.setattr(video_module, "save_image_bytes", _assert_extract_first)

    process_video_to_frames(
        input_path=str(tmp_path / "input.mp4"),
        style_path=None,
        end_style_path=None,
        output_path=str(output_dir),
        fmt="PNG",
        size="1x",
        frame_range=(0, 2),
        relative_style=False,
        style_mode="auto",
        abort_event=None,
        on_progress=None,
        on_preview=None,
        job_folder=job_folder,
    )

    assert sorted(path.name for path in job_folder.src_path.iterdir()) == [
        "src--frames--001.png",
        "src--frames--002.png",
        "src--frames--003.png",
    ]
    assert sorted(path.name for path in job_folder.path.glob("frames--*.png")) == [
        "frames--001.png",
        "frames--002.png",
        "frames--003.png",
    ]
    assert sorted(path.name for path in output_dir.glob("frame_*.png")) == [
        "frame_000001.png",
        "frame_000002.png",
        "frame_000003.png",
    ]


def test_process_video_to_mp4_when_job_folder_used_then_extracts_src_first_and_assembles_padded_frames(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from vexy_lines_api.export import video as video_module

    frames = [np.full((2, 3, 3), fill_value=index, dtype=np.uint8) for index in range(12)]
    output_path = tmp_path / "styled.mp4"
    job_folder = JobFolder(output_path)
    created_fps = 0.0
    created_size = (0, 0)
    created_writer: _FakeWriter | None = None

    monkeypatch.setattr(
        video_module,
        "probe",
        lambda _path: type(
            "VideoInfoStub",
            (),
            {"total_frames": 12, "width": 3, "height": 2, "fps": 24.0, "has_audio": False},
        )(),
    )
    monkeypatch.setattr(video_module.cv2, "VideoCapture", lambda _path: _FakeCapture(frames))
    monkeypatch.setattr(video_module.cv2, "imencode", _encode_png)

    original_open = video_module.PILImage.open

    def _assert_extract_first(path, *args, **kwargs):
        if Path(path).parent == job_folder.src_path:
            assert job_folder.existing_src_frames(job_folder.output_stem, "png") == {1, 2, 3}
        return original_open(path, *args, **kwargs)

    def _create_writer(path: str, fps: float, width: int, height: int) -> _FakeWriter:
        nonlocal created_fps, created_size, created_writer

        created_fps = fps
        created_size = (width, height)
        writer = _FakeWriter(Path(path))
        created_writer = writer
        return writer

    monkeypatch.setattr(video_module.PILImage, "open", _assert_extract_first)
    monkeypatch.setattr(video_module, "_create_video_writer", _create_writer)

    process_video_to_mp4(
        input_path=str(tmp_path / "input.mp4"),
        style_path=None,
        end_style_path=None,
        output_path=str(output_path),
        size="1x",
        audio=False,
        frame_range=(0, 2),
        relative_style=False,
        style_mode="auto",
        abort_event=None,
        on_progress=None,
        on_preview=None,
        job_folder=job_folder,
    )

    assert sorted(path.name for path in job_folder.src_path.iterdir()) == [
        "src--styled--001.png",
        "src--styled--002.png",
        "src--styled--003.png",
    ]
    assert sorted(path.name for path in job_folder.path.glob("styled--*.png")) == [
        "styled--001.png",
        "styled--002.png",
        "styled--003.png",
    ]
    assert output_path.exists()
    assert created_fps == 24.0
    assert created_size == (3, 2)
    assert created_writer is not None
    assert len(created_writer.frames) == 3


def test_process_video_to_mp4_when_end_range_exceeds_video_then_clamps_to_available_frames(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from vexy_lines_api.export import video as video_module

    frames = [np.full((2, 3, 3), fill_value=index, dtype=np.uint8) for index in range(12)]
    output_path = tmp_path / "clamped.mp4"
    job_folder = JobFolder(output_path)
    created_writer: _FakeWriter | None = None

    monkeypatch.setattr(
        video_module,
        "probe",
        lambda _path: type(
            "VideoInfoStub",
            (),
            {"total_frames": 12, "width": 3, "height": 2, "fps": 24.0, "has_audio": False},
        )(),
    )
    monkeypatch.setattr(video_module.cv2, "VideoCapture", lambda _path: _FakeCapture(frames))
    monkeypatch.setattr(video_module.cv2, "imencode", _encode_png)

    def _create_writer(path: str, _fps: float, _width: int, _height: int) -> _FakeWriter:
        nonlocal created_writer

        writer = _FakeWriter(Path(path))
        created_writer = writer
        return writer

    monkeypatch.setattr(video_module, "_create_video_writer", _create_writer)

    process_video_to_mp4(
        input_path=str(tmp_path / "input.mp4"),
        style_path=None,
        end_style_path=None,
        output_path=str(output_path),
        size="1x",
        audio=False,
        frame_range=(4, 1_000_003),
        relative_style=False,
        style_mode="auto",
        abort_event=None,
        on_progress=None,
        on_preview=None,
        job_folder=job_folder,
    )

    assert sorted(path.name for path in job_folder.src_path.iterdir()) == [
        "src--clamped--005.png",
        "src--clamped--006.png",
        "src--clamped--007.png",
        "src--clamped--008.png",
        "src--clamped--009.png",
        "src--clamped--010.png",
        "src--clamped--011.png",
        "src--clamped--012.png",
    ]
    assert created_writer is not None
    assert len(created_writer.frames) == 8
    assert output_path.exists()
