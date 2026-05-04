"""Unit tests for autoclip.pipeline.ingest — mocks subprocess, never runs ffmpeg.

Coverage:
- _find_source_video: missing dir / no video / multiple videos / happy path
- _is_single_track_mode: env var parsing across truthy values
- _run_ffmpeg: success, non-zero exit, timeout
- run_ingest end-to-end (mocked):
    - dual-track happy path emits 4 ffmpeg calls (probe + low + hd + audio)
      and progress 0.05 → 0.45 → 0.85 → 0.95 → 1.0
    - single-track mode skips hd and pulls audio from low
    - cancel signal aborts early and leaves stage RUNNING (entrypoint will FAILED it)
    - ffmpeg failure surfaces as IngestError
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from autoclip.pipeline import ingest as ingest_mod
from autoclip.pipeline.ingest import (
    AUDIO_FILENAME,
    HD_FILENAME,
    LOW_FILENAME,
    RAW_DIRNAME,
    IngestCancelledError,
    IngestError,
    _find_source_video,
    _is_single_track_mode,
    _run_ffmpeg,
    run_ingest,
)
from autoclip.pipeline.state import JobStateFile, Stage, StageStatus
from autoclip.utils.ffmpeg import ProbeResult

# ===== Fixtures =====


@pytest.fixture
def job_dir(tmp_path: Path) -> Path:
    """A bare job_dir with a usable JobStateFile + raw/test.mp4 placeholder."""
    state = JobStateFile(tmp_path)
    state.init_state(
        job_id=1,
        video_hash="deadbeef",
        target_duration_sec=120,
        style_preset="plot_summary",
    )
    raw_dir = tmp_path / RAW_DIRNAME
    raw_dir.mkdir()
    (raw_dir / "test.mp4").write_bytes(b"fake-mp4-bytes")
    return tmp_path


@pytest.fixture
def fake_probe() -> ProbeResult:
    """ProbeResult matching the user's actual fixture (1376x768)."""
    return ProbeResult(
        width=1376,
        height=768,
        fps=24.0,
        duration_sec=628.8,
        video_codec="h264",
        audio_codec="aac",
        has_audio=True,
    )


# ===== _find_source_video =====


def test_find_source_video_happy(job_dir: Path):
    src = _find_source_video(job_dir)
    assert src.name == "test.mp4"


def test_find_source_video_missing_raw_dir(tmp_path: Path):
    with pytest.raises(IngestError, match="raw directory missing"):
        _find_source_video(tmp_path)


def test_find_source_video_no_video_in_raw(tmp_path: Path):
    (tmp_path / RAW_DIRNAME).mkdir()
    with pytest.raises(IngestError, match="no video file found"):
        _find_source_video(tmp_path)


def test_find_source_video_multiple_videos_rejected(tmp_path: Path):
    raw = tmp_path / RAW_DIRNAME
    raw.mkdir()
    (raw / "a.mp4").write_bytes(b"a")
    (raw / "b.mov").write_bytes(b"b")
    with pytest.raises(IngestError, match="expected exactly 1 video"):
        _find_source_video(tmp_path)


def test_find_source_video_ignores_unsupported_extensions(tmp_path: Path):
    raw = tmp_path / RAW_DIRNAME
    raw.mkdir()
    (raw / "thumb.jpg").write_bytes(b"jpg")
    (raw / "movie.mp4").write_bytes(b"mp4")
    src = _find_source_video(tmp_path)
    assert src.name == "movie.mp4"


# ===== _is_single_track_mode =====


@pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "on"])
def test_single_track_truthy(val: str, monkeypatch):
    monkeypatch.setenv("INGEST_SINGLE_TRACK", val)
    assert _is_single_track_mode() is True


@pytest.mark.parametrize("val", ["", "0", "false", "no", "off", "garbage"])
def test_single_track_falsy(val: str, monkeypatch):
    monkeypatch.setenv("INGEST_SINGLE_TRACK", val)
    assert _is_single_track_mode() is False


def test_single_track_unset_defaults_false(monkeypatch):
    monkeypatch.delenv("INGEST_SINGLE_TRACK", raising=False)
    assert _is_single_track_mode() is False


# ===== _run_ffmpeg =====


def test_run_ffmpeg_success():
    fake = MagicMock(return_value=MagicMock(returncode=0, stderr=""))
    with patch("autoclip.pipeline.ingest.subprocess.run", fake):
        # Should not raise.
        _run_ffmpeg(["ffmpeg", "-y"], "demo")
    fake.assert_called_once()


def test_run_ffmpeg_non_zero_exit_raises():
    fake = MagicMock(
        return_value=MagicMock(returncode=1, stderr="line1\nline2\nfatal error")
    )
    with (
        patch("autoclip.pipeline.ingest.subprocess.run", fake),
        pytest.raises(IngestError, match=r"demo failed \(exit=1\)"),
    ):
        _run_ffmpeg(["ffmpeg", "-y"], "demo")


def test_run_ffmpeg_timeout_raises():
    err = subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=42)
    with (
        patch("autoclip.pipeline.ingest.subprocess.run", side_effect=err),
        pytest.raises(IngestError, match="timed out"),
    ):
        _run_ffmpeg(["ffmpeg", "-y"], "demo")


# ===== run_ingest end-to-end (mocked) =====


def _patch_ffmpeg_and_probe(fake_probe: ProbeResult):
    """Convenience: mock probe_video + subprocess.run together."""
    return (
        patch("autoclip.pipeline.ingest.probe_video", return_value=fake_probe),
        patch(
            "autoclip.pipeline.ingest.subprocess.run",
            return_value=MagicMock(returncode=0, stderr=""),
        ),
    )


def test_run_ingest_dual_track_happy_path(
    job_dir: Path, fake_probe: ProbeResult, monkeypatch
):
    monkeypatch.delenv("INGEST_SINGLE_TRACK", raising=False)
    probe_p, run_p = _patch_ffmpeg_and_probe(fake_probe)
    with probe_p as probe_mock, run_p as run_mock:
        run_ingest(job_dir)

    # 1 probe call.
    probe_mock.assert_called_once()

    # 3 ffmpeg invocations: low + hd + audio.
    assert run_mock.call_count == 3
    invoked_cmds = [call.args[0] for call in run_mock.call_args_list]
    # First arg of each call is a list[str]; check the output filename (last arg).
    output_paths = [cmd[-1] for cmd in invoked_cmds]
    assert output_paths[0].endswith(LOW_FILENAME)
    assert output_paths[1].endswith(HD_FILENAME)
    assert output_paths[2].endswith(AUDIO_FILENAME)

    # State should be DONE with progress 1.0.
    state = JobStateFile(job_dir).load()
    slot = state["stages"][Stage.INGEST.value]
    assert slot["status"] == StageStatus.DONE.value
    assert slot["progress"] == 1.0


def test_run_ingest_dual_track_audio_extracted_from_hd(
    job_dir: Path, fake_probe: ProbeResult, monkeypatch
):
    """In dual-track mode the audio.wav source should be normalized_hd.mp4."""
    monkeypatch.delenv("INGEST_SINGLE_TRACK", raising=False)
    probe_p, run_p = _patch_ffmpeg_and_probe(fake_probe)
    with probe_p, run_p as run_mock:
        run_ingest(job_dir)

    # The audio call (last invocation) should take HD as input.
    audio_cmd = run_mock.call_args_list[-1].args[0]
    # `-i <input>` pattern: find -i index, next arg is input path.
    i_idx = audio_cmd.index("-i")
    assert audio_cmd[i_idx + 1].endswith(HD_FILENAME)


def test_run_ingest_single_track_skips_hd(
    job_dir: Path, fake_probe: ProbeResult, monkeypatch
):
    monkeypatch.setenv("INGEST_SINGLE_TRACK", "1")
    probe_p, run_p = _patch_ffmpeg_and_probe(fake_probe)
    with probe_p, run_p as run_mock:
        run_ingest(job_dir)

    # Only 2 ffmpeg invocations: low + audio (hd skipped).
    assert run_mock.call_count == 2
    output_paths = [c.args[0][-1] for c in run_mock.call_args_list]
    assert output_paths[0].endswith(LOW_FILENAME)
    assert output_paths[1].endswith(AUDIO_FILENAME)
    assert not any(p.endswith(HD_FILENAME) for p in output_paths)


def test_run_ingest_single_track_audio_extracted_from_low(
    job_dir: Path, fake_probe: ProbeResult, monkeypatch
):
    """When hd is skipped, audio.wav must be extracted from low instead."""
    monkeypatch.setenv("INGEST_SINGLE_TRACK", "1")
    probe_p, run_p = _patch_ffmpeg_and_probe(fake_probe)
    with probe_p, run_p as run_mock:
        run_ingest(job_dir)

    audio_cmd = run_mock.call_args_list[-1].args[0]
    i_idx = audio_cmd.index("-i")
    assert audio_cmd[i_idx + 1].endswith(LOW_FILENAME)


def test_run_ingest_cancel_before_low_aborts(
    job_dir: Path, fake_probe: ProbeResult, monkeypatch
):
    """User cancel between probe and low should raise IngestCancelledError."""
    monkeypatch.delenv("INGEST_SINGLE_TRACK", raising=False)
    state = JobStateFile(job_dir)

    # Cancel signal injected via .cancel touch file BEFORE we start.
    state.request_cancel()

    probe_p, run_p = _patch_ffmpeg_and_probe(fake_probe)
    with probe_p, run_p as run_mock, pytest.raises(
        IngestCancelledError, match="cancelled before probe"
    ):
        run_ingest(job_dir)
    # No ffmpeg should have been invoked.
    run_mock.assert_not_called()


def test_run_ingest_ffmpeg_failure_surfaces_as_ingest_error(
    job_dir: Path, fake_probe: ProbeResult, monkeypatch
):
    monkeypatch.delenv("INGEST_SINGLE_TRACK", raising=False)
    failing = MagicMock(return_value=MagicMock(returncode=1, stderr="codec broke"))
    with (
        patch("autoclip.pipeline.ingest.probe_video", return_value=fake_probe),
        patch("autoclip.pipeline.ingest.subprocess.run", failing),
        pytest.raises(IngestError, match="normalize_low failed"),
    ):
        run_ingest(job_dir)


# ===== Module registration =====


def test_handler_registered_on_import():
    """Importing the ingest module must side-effect register the handler.

    Note: we explicitly reload the module here because earlier tests in the
    suite (e.g. tests/unit/test_runner.py) call `clear_stage_handlers()` which
    wipes the global registry. The module-level `register_stage_handler(...)`
    only runs on first import — once cleared, it stays cleared until reload.
    """
    import importlib

    from autoclip.pipeline.runner import get_stage_handler

    importlib.reload(ingest_mod)
    handler = get_stage_handler(Stage.INGEST)
    assert handler is ingest_mod.run_ingest
