"""Unit tests for autoclip.algo.shot_detector — Shot dataclass + detect_shots().

These tests must NOT invoke real PySceneDetect / cv2 decoding;
the real-binary path is exercised in M1.8's integration tests.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from autoclip.algo.shot_detector import (
    DEFAULT_MIN_SCENE_LEN_SEC,
    DEFAULT_THRESHOLD,
    FALLBACK_FPS,
    Shot,
    ShotDetectionError,
    detect_shots,
)

# ===== Constants sanity =====


def test_constants_match_design():
    """If anyone changes a tuning constant, this test forces re-reading ADR-003."""
    assert DEFAULT_THRESHOLD == 27.0
    assert DEFAULT_MIN_SCENE_LEN_SEC == 0.8
    assert FALLBACK_FPS == 25.0


# ===== Shot dataclass =====


def test_shot_basic_construction():
    s = Shot(idx=0, start_sec=1.5, end_sec=4.0)
    assert s.idx == 0
    assert s.start_sec == 1.5
    assert s.end_sec == 4.0


def test_shot_duration_property():
    s = Shot(idx=3, start_sec=10.0, end_sec=12.5)
    assert s.duration_sec == pytest.approx(2.5)


def test_shot_to_dict_round_trip():
    s = Shot(idx=7, start_sec=2.0, end_sec=5.0)
    d = s.to_dict()
    assert d == {"idx": 7, "start_sec": 2.0, "end_sec": 5.0}


def test_shot_is_frozen():
    """frozen=True dataclass must reject mutation with FrozenInstanceError."""
    from dataclasses import FrozenInstanceError

    s = Shot(idx=0, start_sec=0.0, end_sec=1.0)
    with pytest.raises(FrozenInstanceError):
        s.idx = 99  # type: ignore[misc]


def test_shot_negative_idx_rejected():
    with pytest.raises(ValueError, match="idx must be non-negative"):
        Shot(idx=-1, start_sec=0.0, end_sec=1.0)


def test_shot_negative_start_rejected():
    with pytest.raises(ValueError, match="start_sec must be non-negative"):
        Shot(idx=0, start_sec=-0.1, end_sec=1.0)


def test_shot_end_le_start_rejected():
    """end_sec must be STRICTLY greater than start_sec (zero-duration shots are invalid)."""
    with pytest.raises(ValueError, match="end_sec.*must be > start_sec"):
        Shot(idx=0, start_sec=5.0, end_sec=5.0)
    with pytest.raises(ValueError, match="end_sec.*must be > start_sec"):
        Shot(idx=0, start_sec=5.0, end_sec=4.0)


# ===== detect_shots — file errors =====


def test_detect_shots_missing_file_raises_file_not_found(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="video file not found"):
        detect_shots(tmp_path / "nope.mp4")


def test_detect_shots_open_video_failure_raises(tmp_path: Path):
    src = tmp_path / "fake.mp4"
    src.write_bytes(b"fake-not-a-real-video")
    with (
        patch("scenedetect.open_video", side_effect=RuntimeError("decode failed")),
        pytest.raises(ShotDetectionError, match="failed to open video"),
    ):
        detect_shots(src)


def test_detect_shots_detect_scenes_failure_raises(tmp_path: Path):
    src = tmp_path / "fake.mp4"
    src.write_bytes(b"fake")

    fake_video = MagicMock(frame_rate=25.0)
    fake_sm = MagicMock()
    fake_sm.detect_scenes.side_effect = RuntimeError("decode mid-stream")

    with (
        patch("scenedetect.open_video", return_value=fake_video),
        patch("scenedetect.SceneManager", return_value=fake_sm),
        patch("scenedetect.ContentDetector"),
        pytest.raises(ShotDetectionError, match="detect_scenes failed"),
    ):
        detect_shots(src)


# ===== detect_shots — happy path =====


def _make_timecode(seconds: float) -> MagicMock:
    """Build a fake FrameTimecode whose .get_seconds() returns the given value."""
    tc = MagicMock()
    tc.get_seconds.return_value = seconds
    return tc


def test_detect_shots_happy_path_three_scenes(tmp_path: Path):
    src = tmp_path / "fake.mp4"
    src.write_bytes(b"fake")

    fake_video = MagicMock(frame_rate=25.0)
    fake_video.duration = _make_timecode(120.0)
    fake_sm = MagicMock()
    fake_sm.get_scene_list.return_value = [
        (_make_timecode(0.0), _make_timecode(10.0)),
        (_make_timecode(10.0), _make_timecode(40.0)),
        (_make_timecode(40.0), _make_timecode(120.0)),
    ]

    with (
        patch("scenedetect.open_video", return_value=fake_video),
        patch("scenedetect.SceneManager", return_value=fake_sm),
        patch("scenedetect.ContentDetector") as cd_mock,
    ):
        shots = detect_shots(src)

    assert len(shots) == 3
    assert shots[0] == Shot(idx=0, start_sec=0.0, end_sec=10.0)
    assert shots[1] == Shot(idx=1, start_sec=10.0, end_sec=40.0)
    assert shots[2] == Shot(idx=2, start_sec=40.0, end_sec=120.0)

    # ContentDetector should have been built with the default threshold and
    # min_scene_len converted to frames (25 fps * 0.8s = 20 frames).
    cd_mock.assert_called_once_with(threshold=27.0, min_scene_len=20)


def test_detect_shots_idx_is_strictly_ascending(tmp_path: Path):
    src = tmp_path / "fake.mp4"
    src.write_bytes(b"fake")

    fake_video = MagicMock(frame_rate=24.0)
    fake_video.duration = _make_timecode(50.0)
    fake_sm = MagicMock()
    fake_sm.get_scene_list.return_value = [
        (_make_timecode(0.0), _make_timecode(5.0)),
        (_make_timecode(5.0), _make_timecode(20.0)),
        (_make_timecode(20.0), _make_timecode(35.0)),
        (_make_timecode(35.0), _make_timecode(50.0)),
    ]

    with (
        patch("scenedetect.open_video", return_value=fake_video),
        patch("scenedetect.SceneManager", return_value=fake_sm),
        patch("scenedetect.ContentDetector"),
    ):
        shots = detect_shots(src)

    indices = [s.idx for s in shots]
    assert indices == [0, 1, 2, 3]
    starts = [s.start_sec for s in shots]
    assert starts == sorted(starts), "Shot starts must be ascending"


def test_detect_shots_custom_threshold_and_min_len(tmp_path: Path):
    """threshold=30.0 + min_scene_len_sec=1.0 should propagate to ContentDetector."""
    src = tmp_path / "fake.mp4"
    src.write_bytes(b"fake")

    fake_video = MagicMock(frame_rate=30.0)
    fake_video.duration = _make_timecode(10.0)
    fake_sm = MagicMock()
    fake_sm.get_scene_list.return_value = [
        (_make_timecode(0.0), _make_timecode(10.0))
    ]

    with (
        patch("scenedetect.open_video", return_value=fake_video),
        patch("scenedetect.SceneManager", return_value=fake_sm),
        patch("scenedetect.ContentDetector") as cd_mock,
    ):
        detect_shots(src, threshold=30.0, min_scene_len_sec=1.0)

    # 30 fps * 1.0s = 30 frames.
    cd_mock.assert_called_once_with(threshold=30.0, min_scene_len=30)


# ===== detect_shots — fallback (zero scene boundaries) =====


def test_detect_shots_zero_scenes_falls_back_to_single_shot(tmp_path: Path):
    src = tmp_path / "fake.mp4"
    src.write_bytes(b"fake")

    fake_video = MagicMock(frame_rate=25.0)
    fake_video.duration = _make_timecode(180.5)
    fake_sm = MagicMock()
    fake_sm.get_scene_list.return_value = []  # zero scene transitions

    with (
        patch("scenedetect.open_video", return_value=fake_video),
        patch("scenedetect.SceneManager", return_value=fake_sm),
        patch("scenedetect.ContentDetector"),
    ):
        shots = detect_shots(src)

    assert len(shots) == 1
    assert shots[0].idx == 0
    assert shots[0].start_sec == 0.0
    assert shots[0].end_sec == pytest.approx(180.5)


def test_detect_shots_zero_scenes_zero_duration_raises(tmp_path: Path):
    """If we both have no scenes AND zero duration, that's an unrecoverable error."""
    src = tmp_path / "fake.mp4"
    src.write_bytes(b"fake")

    fake_video = MagicMock(frame_rate=25.0)
    fake_video.duration = _make_timecode(0.0)
    fake_sm = MagicMock()
    fake_sm.get_scene_list.return_value = []

    with (
        patch("scenedetect.open_video", return_value=fake_video),
        patch("scenedetect.SceneManager", return_value=fake_sm),
        patch("scenedetect.ContentDetector"),
        pytest.raises(ShotDetectionError, match="zero/unknown duration"),
    ):
        detect_shots(src)


# ===== detect_shots — fps fallback =====


def test_detect_shots_zero_fps_uses_fallback(tmp_path: Path):
    """If video reports 0 fps, we should fall back to FALLBACK_FPS=25.0."""
    src = tmp_path / "fake.mp4"
    src.write_bytes(b"fake")

    fake_video = MagicMock(frame_rate=0.0)  # broken metadata
    fake_video.duration = _make_timecode(10.0)
    fake_sm = MagicMock()
    fake_sm.get_scene_list.return_value = [
        (_make_timecode(0.0), _make_timecode(10.0))
    ]

    with (
        patch("scenedetect.open_video", return_value=fake_video),
        patch("scenedetect.SceneManager", return_value=fake_sm),
        patch("scenedetect.ContentDetector") as cd_mock,
    ):
        detect_shots(src)

    # 25.0 (fallback fps) * 0.8s = 20 frames.
    cd_mock.assert_called_once_with(threshold=27.0, min_scene_len=20)
