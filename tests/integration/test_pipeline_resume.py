"""Integration test: real subprocess pipeline with resume semantics.

This is the K7 (resume primitive) end-to-end validation:
- Spawn real mp.Process subprocesses
- Use fake handlers (no real ffmpeg/asr/llm) that mark DONE + write markers
- Verify: full run all 5 markers; partial DONE + resume picks up from interruption

We pre-populate _STAGE_MODULES so the spawn entrypoint imports our fake handler
module, registering handlers in the fresh interpreter.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from autoclip.pipeline import runner as runner_mod
from autoclip.pipeline.runner import PipelineRunner
from autoclip.pipeline.state import JobStateFile, Stage, StageStatus


@pytest.fixture(autouse=True)
def _wire_fake_handlers(monkeypatch):
    """Make subprocess auto-import fake handlers via env-var injection.

    Why env var? Spawn subprocesses are fresh interpreters that re-import
    `runner.py` (so any monkeypatch on module-level constants is invisible
    to them). Env vars survive the spawn boundary.
    """
    monkeypatch.setenv(
        runner_mod.ENV_EXTRA_STAGE_MODULES,
        "tests.integration._fixtures.fake_stage_handlers",
    )
    # Also load in this (parent) process for direct entrypoint testing
    runner_mod._load_stage_modules()
    yield
    runner_mod.clear_stage_handlers()


@pytest.fixture()
def fresh_job_dir(tmp_path: Path) -> Path:
    state = JobStateFile(tmp_path)
    state.init_state(
        job_id=1,
        video_hash="hash123",
        target_duration_sec=60,
    )
    return tmp_path


def test_full_pipeline_runs_all_5_stages_in_real_subprocesses(fresh_job_dir: Path):
    """Happy path: 5 real subprocesses spawned, each writes its marker."""
    runner = PipelineRunner(fresh_job_dir)
    result = runner.run()

    assert result == StageStatus.DONE

    # Verify all 5 marker files exist (proof handler executed in subprocess)
    for stage in Stage.ordered():
        marker = fresh_job_dir / f"{stage.value}.marker"
        assert marker.exists(), f"Missing marker for {stage.value}"
        assert marker.read_text() == stage.value

    # Verify state.json reflects all DONE
    final = JobStateFile(fresh_job_dir).load()
    for stage in Stage.ordered():
        slot = final["stages"][stage.value]
        assert slot["status"] == StageStatus.DONE.value
        assert slot["progress"] == 1.0
        assert slot["finished_at"] is not None


def test_resume_skips_done_stages_in_real_subprocesses(fresh_job_dir: Path):
    """K7 main: pre-mark INGEST+INDEX+SCRIPT DONE, run, only 2 markers should appear."""
    state = JobStateFile(fresh_job_dir)
    state.mark_stage(Stage.INGEST, StageStatus.DONE)
    state.mark_stage(Stage.INDEX, StageStatus.DONE)
    state.mark_stage(Stage.SCRIPT, StageStatus.DONE)

    runner = PipelineRunner(fresh_job_dir)
    result = runner.run(resume=True)

    assert result == StageStatus.DONE

    # Markers only for ASSEMBLY + RENDER (the only stages that re-ran)
    assert not (fresh_job_dir / "ingest.marker").exists()
    assert not (fresh_job_dir / "index.marker").exists()
    assert not (fresh_job_dir / "script.marker").exists()
    assert (fresh_job_dir / "assembly.marker").exists()
    assert (fresh_job_dir / "render.marker").exists()

    # All 5 stages now DONE in state.json
    final = JobStateFile(fresh_job_dir).load()
    for stage in Stage.ordered():
        assert final["stages"][stage.value]["status"] == StageStatus.DONE.value


def test_resume_after_failed_stage_reruns_it(fresh_job_dir: Path):
    """If SCRIPT was FAILED, resume should re-spawn it (not skip)."""
    state = JobStateFile(fresh_job_dir)
    state.mark_stage(Stage.INGEST, StageStatus.DONE)
    state.mark_stage(Stage.INDEX, StageStatus.DONE)
    state.mark_stage(Stage.SCRIPT, StageStatus.FAILED, error="prior crash")

    runner = PipelineRunner(fresh_job_dir)
    result = runner.run(resume=True)

    assert result == StageStatus.DONE
    # SCRIPT marker SHOULD exist (handler reran and overwrote)
    assert (fresh_job_dir / "script.marker").exists()
    # Final SCRIPT slot is DONE (error cleared)
    final_script = JobStateFile(fresh_job_dir).load()["stages"][Stage.SCRIPT.value]
    assert final_script["status"] == StageStatus.DONE.value
