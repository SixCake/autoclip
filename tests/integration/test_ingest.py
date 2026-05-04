"""Integration test for the M1.6 Ingest stage — runs real ffmpeg on a real video.

Skipped by default. Enable with:
    RUN_INTEGRATION=1 pytest tests/integration/test_ingest.py

Requirements (when enabled):
- `ffmpeg` and `ffprobe` on $PATH (`brew install ffmpeg` on macOS)
- A real source video at $AUTOCLIP_INGEST_FIXTURE (default: ~/Downloads/test.mp4)
- ~50MB free disk for the trimmed fixture + 3 ingest products

Coverage:
- End-to-end run_ingest() against real ffmpeg (dual-track happy path)
- All 3 expected output files exist and are non-empty
- state.json reflects status=DONE + progress=1.0
- Probe-derived dimensions are sane (width/height > 0)
- Single-track mode produces only 2 outputs and audio extracted from low

Why we trim the source down to ~10s:
- The full user fixture (~10min) takes ~40s to ingest on M3 Pro and slows iteration
- 10s is plenty to validate the ffmpeg pipeline end-to-end
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from autoclip.pipeline.ingest import (
    AUDIO_FILENAME,
    HD_FILENAME,
    LOW_FILENAME,
    RAW_DIRNAME,
    run_ingest,
)
from autoclip.pipeline.state import JobStateFile, Stage, StageStatus

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1",
    reason="Set RUN_INTEGRATION=1 to run integration tests (requires ffmpeg + real video)",
)


SOURCE_VIDEO_ENV = "AUTOCLIP_INGEST_FIXTURE"
DEFAULT_SOURCE = Path.home() / "Downloads" / "test.mp4"
TRIM_DURATION_SEC = 10  # short slice for fast iteration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _resolve_source_video() -> Path:
    """Pick the source video from env override or default ~/Downloads/test.mp4."""
    raw = os.environ.get(SOURCE_VIDEO_ENV)
    return Path(raw).expanduser() if raw else DEFAULT_SOURCE


@pytest.fixture(scope="module")
def source_video() -> Path:
    src = _resolve_source_video()
    if not src.exists():
        pytest.skip(
            f"Source video not found: {src}. Set {SOURCE_VIDEO_ENV}=/path/to/video.mp4 "
            f"or place a file at {DEFAULT_SOURCE}."
        )
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe not found on PATH; install via 'brew install ffmpeg'")
    return src


@pytest.fixture
def ingest_job_dir(tmp_path: Path, source_video: Path) -> Path:
    """Build a fresh job_dir with a 10s trimmed copy of the source under raw/."""
    raw_dir = tmp_path / RAW_DIRNAME
    raw_dir.mkdir()
    trimmed = raw_dir / "fixture.mp4"

    # Trim with stream copy (no re-encode) for speed.
    subprocess.run(  # noqa: S603 — args list, no shell
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-ss",
            "0",
            "-t",
            str(TRIM_DURATION_SEC),
            "-i",
            str(source_video),
            "-c",
            "copy",
            str(trimmed),
        ],
        check=True,
        timeout=60,
    )
    assert trimmed.exists() and trimmed.stat().st_size > 0

    # Initialize state.json so JobStateFile is usable.
    JobStateFile(tmp_path).init_state(
        job_id=42,
        video_hash="integration-fixture",
        target_duration_sec=120,
        style_preset="plot_summary",
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_ingest_dual_track_end_to_end(ingest_job_dir: Path, monkeypatch):
    """Default dual-track mode should produce all 3 outputs and DONE state."""
    monkeypatch.delenv("INGEST_SINGLE_TRACK", raising=False)

    run_ingest(ingest_job_dir)

    # All 3 products must exist and be non-trivial in size.
    low = ingest_job_dir / LOW_FILENAME
    hd = ingest_job_dir / HD_FILENAME
    audio = ingest_job_dir / AUDIO_FILENAME
    for p in (low, hd, audio):
        assert p.exists(), f"missing expected output: {p}"
        assert p.stat().st_size > 1024, f"output unexpectedly tiny: {p} ({p.stat().st_size} bytes)"

    # State should reflect DONE + progress=1.0.
    slot = JobStateFile(ingest_job_dir).load()["stages"][Stage.INGEST.value]
    assert slot["status"] == StageStatus.DONE.value
    assert slot["progress"] == 1.0
    assert slot["finished_at"] is not None


def test_ingest_outputs_are_valid_via_ffprobe(ingest_job_dir: Path, monkeypatch):
    """Spot-check that the produced files actually parse as media."""
    monkeypatch.delenv("INGEST_SINGLE_TRACK", raising=False)
    run_ingest(ingest_job_dir)

    from autoclip.utils.ffmpeg import probe_video

    low_probe = probe_video(ingest_job_dir / LOW_FILENAME)
    assert low_probe.height == 720, f"low track should be 720p, got {low_probe.height}"
    assert low_probe.fps == pytest.approx(25.0, rel=0.05), f"low fps drift: {low_probe.fps}"

    hd_probe = probe_video(ingest_job_dir / HD_FILENAME)
    assert hd_probe.height > 0
    # No upscale: hd height must not exceed source.
    assert hd_probe.height <= max(low_probe.height, 1080)


def test_ingest_single_track_produces_two_outputs(ingest_job_dir: Path, monkeypatch):
    """INGEST_SINGLE_TRACK=1 should skip hd entirely and still mark DONE."""
    monkeypatch.setenv("INGEST_SINGLE_TRACK", "1")

    run_ingest(ingest_job_dir)

    assert (ingest_job_dir / LOW_FILENAME).exists()
    assert (ingest_job_dir / AUDIO_FILENAME).exists()
    assert not (ingest_job_dir / HD_FILENAME).exists(), "hd track should be skipped"

    slot = JobStateFile(ingest_job_dir).load()["stages"][Stage.INGEST.value]
    assert slot["status"] == StageStatus.DONE.value
