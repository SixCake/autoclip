"""Tests for autoclip.pipeline.state — JobStateFile atomic R/W + state machine.

Covers M1.3 acceptance:
- init_state creates all 5 stages as PENDING
- mark_stage atomic write leaves no .tmp residue
- next_stage_to_run skips DONE stages (resume semantics)
- cancel signal: request_cancel → is_cancelled True
- Bonus: progress clamping, mark_stage timestamps, multiple FAILED handling
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from autoclip.pipeline.state import (
    CANCEL_FILENAME,
    STATE_FILENAME,
    JobStateFile,
    Stage,
    StageStatus,
)


@pytest.fixture()
def state_file(tmp_path: Path) -> JobStateFile:
    """Provide a fresh JobStateFile pointing at a unique tmp dir per test."""
    job_dir = tmp_path / "job_42"
    return JobStateFile(job_dir)


# ---------------------------------------------------------------------------
# init_state
# ---------------------------------------------------------------------------

def test_init_state_creates_all_5_stages_as_pending(state_file: JobStateFile) -> None:
    """init_state must create state.json with 5 stages, all PENDING, progress=0."""
    state = state_file.init_state(
        job_id=42,
        video_hash="a" * 64,
        target_duration_sec=60,
        style_preset="plot_summary",
    )

    # Top-level meta
    assert state["job_id"] == 42
    assert state["video_hash"] == "a" * 64
    assert state["target_duration_sec"] == 60
    assert state["style_preset"] == "plot_summary"
    assert "created_at" in state
    assert "updated_at" in state

    # All 5 stages present and PENDING
    assert set(state["stages"].keys()) == {s.value for s in Stage.ordered()}
    for stage_data in state["stages"].values():
        assert stage_data["status"] == StageStatus.PENDING.value
        assert stage_data["progress"] == 0.0
        assert stage_data["error"] is None
        assert stage_data["started_at"] is None
        assert stage_data["finished_at"] is None

    # File on disk matches
    assert state_file.path.exists()
    assert state_file.exists() is True
    on_disk = json.loads(state_file.path.read_text(encoding="utf-8"))
    assert on_disk["job_id"] == 42


# ---------------------------------------------------------------------------
# atomic write integrity
# ---------------------------------------------------------------------------

def test_mark_stage_leaves_no_tmp_residue(state_file: JobStateFile) -> None:
    """After mark_stage, only state.json exists (no .tmp leftover)."""
    state_file.init_state(job_id=1, video_hash="x" * 64, target_duration_sec=60)

    state_file.mark_stage(Stage.INGEST, StageStatus.RUNNING, progress=0.5)
    state_file.mark_stage(Stage.INGEST, StageStatus.DONE)

    files = sorted(p.name for p in state_file.job_dir.iterdir())
    assert STATE_FILENAME in files
    assert f"{STATE_FILENAME}.tmp" not in files


def test_mark_stage_updates_status_progress_timestamps(state_file: JobStateFile) -> None:
    """mark_stage with RUNNING sets started_at; with DONE sets finished_at + progress=1.0."""
    state_file.init_state(job_id=1, video_hash="x" * 64, target_duration_sec=60)

    # RUNNING sets started_at
    s = state_file.mark_stage(Stage.INGEST, StageStatus.RUNNING, progress=0.3)
    ingest = s["stages"]["ingest"]
    assert ingest["status"] == StageStatus.RUNNING.value
    assert ingest["progress"] == 0.3
    assert ingest["started_at"] is not None
    assert ingest["finished_at"] is None

    # DONE sets finished_at + auto progress=1.0
    s = state_file.mark_stage(Stage.INGEST, StageStatus.DONE)
    ingest = s["stages"]["ingest"]
    assert ingest["status"] == StageStatus.DONE.value
    assert ingest["progress"] == 1.0  # auto-set on DONE
    assert ingest["finished_at"] is not None


def test_mark_stage_progress_clamped(state_file: JobStateFile) -> None:
    """progress arg is clamped to [0.0, 1.0]."""
    state_file.init_state(job_id=1, video_hash="x" * 64, target_duration_sec=60)

    s = state_file.mark_stage(Stage.INGEST, StageStatus.RUNNING, progress=-0.5)
    assert s["stages"]["ingest"]["progress"] == 0.0

    s = state_file.mark_stage(Stage.INGEST, StageStatus.RUNNING, progress=2.5)
    assert s["stages"]["ingest"]["progress"] == 1.0


def test_mark_stage_failed_stores_error(state_file: JobStateFile) -> None:
    """FAILED status with error message preserves error string."""
    state_file.init_state(job_id=1, video_hash="x" * 64, target_duration_sec=60)
    s = state_file.mark_stage(
        Stage.INDEX, StageStatus.FAILED, error="ffmpeg returned non-zero exit code 1"
    )
    assert s["stages"]["index"]["status"] == StageStatus.FAILED.value
    assert "ffmpeg" in s["stages"]["index"]["error"]
    assert s["stages"]["index"]["finished_at"] is not None


# ---------------------------------------------------------------------------
# resume semantics — next_stage_to_run
# ---------------------------------------------------------------------------

def test_next_stage_to_run_resume_after_partial(state_file: JobStateFile) -> None:
    """ingest=DONE + index=RUNNING → next_stage_to_run() returns INDEX (re-execute)."""
    state_file.init_state(job_id=1, video_hash="x" * 64, target_duration_sec=60)
    state_file.mark_stage(Stage.INGEST, StageStatus.DONE)
    state_file.mark_stage(Stage.INDEX, StageStatus.RUNNING, progress=0.7)

    assert state_file.next_stage_to_run() == Stage.INDEX


def test_next_stage_to_run_skips_only_done(state_file: JobStateFile) -> None:
    """FAILED and PENDING are both candidates; only DONE is skipped."""
    state_file.init_state(job_id=1, video_hash="x" * 64, target_duration_sec=60)
    state_file.mark_stage(Stage.INGEST, StageStatus.DONE)
    state_file.mark_stage(Stage.INDEX, StageStatus.FAILED, error="api down")

    # INDEX is FAILED, should be re-executed
    assert state_file.next_stage_to_run() == Stage.INDEX


def test_next_stage_to_run_returns_none_when_all_done(state_file: JobStateFile) -> None:
    """All 5 DONE → returns None (pipeline complete)."""
    state_file.init_state(job_id=1, video_hash="x" * 64, target_duration_sec=60)
    for stage in Stage.ordered():
        state_file.mark_stage(stage, StageStatus.DONE)

    assert state_file.next_stage_to_run() is None


def test_next_stage_to_run_fresh_returns_ingest(state_file: JobStateFile) -> None:
    """Fresh state → first stage to run is INGEST."""
    state_file.init_state(job_id=1, video_hash="x" * 64, target_duration_sec=60)
    assert state_file.next_stage_to_run() == Stage.INGEST


# ---------------------------------------------------------------------------
# cancel signal
# ---------------------------------------------------------------------------

def test_cancel_signal_lifecycle(state_file: JobStateFile) -> None:
    """request_cancel touches .cancel; is_cancelled detects it; clear_cancel removes."""
    state_file.init_state(job_id=1, video_hash="x" * 64, target_duration_sec=60)

    # Initially not cancelled
    assert state_file.is_cancelled() is False
    assert not (state_file.job_dir / CANCEL_FILENAME).exists()

    # Request cancel
    state_file.request_cancel()
    assert state_file.is_cancelled() is True
    assert (state_file.job_dir / CANCEL_FILENAME).exists()

    # Idempotent: second request_cancel is fine
    state_file.request_cancel()
    assert state_file.is_cancelled() is True

    # Clear cancel (used on resume)
    state_file.clear_cancel()
    assert state_file.is_cancelled() is False

    # Idempotent clear: no error if already gone
    state_file.clear_cancel()
    assert state_file.is_cancelled() is False


# ---------------------------------------------------------------------------
# load / persistence
# ---------------------------------------------------------------------------

def test_state_persists_across_instances(tmp_path: Path) -> None:
    """A second JobStateFile pointing at the same dir loads existing state."""
    job_dir = tmp_path / "shared_job"

    # Process A: init + mark
    sf_a = JobStateFile(job_dir)
    sf_a.init_state(job_id=99, video_hash="z" * 64, target_duration_sec=180)
    sf_a.mark_stage(Stage.INGEST, StageStatus.DONE)

    # Process B: open same dir
    sf_b = JobStateFile(job_dir)
    state = sf_b.load()
    assert state["job_id"] == 99
    assert state["stages"]["ingest"]["status"] == StageStatus.DONE.value
    assert sf_b.next_stage_to_run() == Stage.INDEX
