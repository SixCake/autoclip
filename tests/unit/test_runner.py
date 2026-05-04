"""Unit tests for PipelineRunner.

Strategy (per M1.4 Q1 decision):
- DO NOT spawn real subprocesses in unit tests.
- Mock `multiprocessing.Process` to verify scheduling logic in isolation.
- Test `_stage_entrypoint` separately by calling it synchronously (it's a
  pure function — the subprocess wrapping is what we mock).

Coverage focus:
- Stage ordering (INGEST → INDEX → SCRIPT → ASSEMBLY → RENDER)
- Resume: skip DONE stages
- Failure interruption: stop on first FAILED stage
- Cancel signal: abort cleanly between stages
- Defensive failure detection: exitcode != 0 OR status != DONE
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from autoclip.pipeline import runner as runner_mod
from autoclip.pipeline.runner import (
    PipelineRunner,
    PipelineRunnerError,
    _stage_entrypoint,
    clear_stage_handlers,
    register_stage_handler,
)
from autoclip.pipeline.state import JobStateFile, Stage, StageStatus


@pytest.fixture(autouse=True)
def _clean_handlers():
    """Each test starts with an empty handler registry."""
    clear_stage_handlers()
    yield
    clear_stage_handlers()


@pytest.fixture()
def job_dir(tmp_path: Path) -> Path:
    """Initialised state.json in a fresh tmp dir."""
    state = JobStateFile(tmp_path)
    state.init_state(
        job_id=42,
        video_hash="abc123",
        target_duration_sec=60,
        style_preset="plot_summary",
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Fake Process — stand-in for mp.Process
# ---------------------------------------------------------------------------

class FakeProcess:
    """Stand-in for mp.Process. Records call + invokes target synchronously."""

    instances: list[FakeProcess] = []

    def __init__(self, target=None, args=(), name=None, **kwargs):  # noqa: ANN
        self.target = target
        self.args = args
        self.name = name
        self.kwargs = kwargs
        self.exitcode: int | None = None
        self.started = False
        FakeProcess.instances.append(self)

    def start(self) -> None:
        self.started = True

    def join(self, timeout=None) -> None:  # noqa: ARG002
        # Run target inline; let test-installed handler decide outcome
        if self.target is not None:
            try:
                self.target(*self.args)
                self.exitcode = 0
            except SystemExit as e:
                self.exitcode = e.code if isinstance(e.code, int) else 1
            except Exception:  # noqa: BLE001
                self.exitcode = 1


@pytest.fixture()
def fake_process(monkeypatch):
    """Replace mp.Process with FakeProcess; reset instance log."""
    FakeProcess.instances.clear()
    monkeypatch.setattr(runner_mod.mp, "Process", FakeProcess)
    return FakeProcess


# ---------------------------------------------------------------------------
# Tests — handler registry
# ---------------------------------------------------------------------------

def test_register_and_lookup_handler():
    def fake_handler(job_dir: Path) -> None:
        pass

    register_stage_handler(Stage.INGEST, fake_handler)
    assert runner_mod.get_stage_handler(Stage.INGEST) is fake_handler
    assert runner_mod.get_stage_handler(Stage.INDEX) is None


# ---------------------------------------------------------------------------
# Tests — _stage_entrypoint (pure function, no subprocess)
# ---------------------------------------------------------------------------

def test_stage_entrypoint_marks_done_on_success(job_dir: Path):
    """Successful handler → DONE marked automatically by entrypoint."""
    register_stage_handler(Stage.INGEST, lambda jd: None)
    _stage_entrypoint(Stage.INGEST.value, str(job_dir))

    state = JobStateFile(job_dir).load()
    assert state["stages"][Stage.INGEST.value]["status"] == StageStatus.DONE.value


def test_stage_entrypoint_marks_failed_on_exception(job_dir: Path):
    """Handler raising → FAILED marked + sys.exit(1)."""
    def crashing_handler(jd: Path) -> None:
        raise ValueError("boom")

    register_stage_handler(Stage.INGEST, crashing_handler)
    with pytest.raises(SystemExit) as exc_info:
        _stage_entrypoint(Stage.INGEST.value, str(job_dir))
    assert exc_info.value.code == 1

    state = JobStateFile(job_dir).load()
    slot = state["stages"][Stage.INGEST.value]
    assert slot["status"] == StageStatus.FAILED.value
    assert "ValueError" in slot["error"]
    assert "boom" in slot["error"]


def test_stage_entrypoint_no_handler_registered(job_dir: Path):
    """Missing handler → FAILED + sys.exit(2)."""
    with pytest.raises(SystemExit) as exc_info:
        _stage_entrypoint(Stage.INGEST.value, str(job_dir))
    assert exc_info.value.code == 2

    state = JobStateFile(job_dir).load()
    slot = state["stages"][Stage.INGEST.value]
    assert slot["status"] == StageStatus.FAILED.value
    assert "No handler registered" in slot["error"]


def test_stage_entrypoint_handler_marks_done_explicitly(job_dir: Path):
    """Handler that marks DONE itself: entrypoint shouldn't overwrite."""
    state_outer = JobStateFile(job_dir)

    def good_handler(jd: Path) -> None:
        JobStateFile(jd).mark_stage(Stage.INGEST, StageStatus.DONE, progress=1.0)

    register_stage_handler(Stage.INGEST, good_handler)
    _stage_entrypoint(Stage.INGEST.value, str(job_dir))

    slot = state_outer.load()["stages"][Stage.INGEST.value]
    assert slot["status"] == StageStatus.DONE.value
    assert slot["progress"] == 1.0


# ---------------------------------------------------------------------------
# Tests — PipelineRunner.run() scheduling logic (mocked subprocesses)
# ---------------------------------------------------------------------------

def test_run_executes_all_5_stages_in_order(job_dir: Path, fake_process):
    """Happy path: 5 stages all succeed, in correct order."""
    # Register handlers that mark DONE for every stage
    for stage in Stage.ordered():
        def make_handler(s):
            return lambda jd: JobStateFile(jd).mark_stage(s, StageStatus.DONE)
        register_stage_handler(stage, make_handler(stage))

    runner = PipelineRunner(job_dir)
    result = runner.run()

    assert result == StageStatus.DONE
    # Verify exactly 5 subprocesses spawned, in correct stage order
    assert len(fake_process.instances) == 5
    spawned_stages = [p.args[0] for p in fake_process.instances]
    assert spawned_stages == [s.value for s in Stage.ordered()]

    # Verify all stages marked DONE
    final = JobStateFile(job_dir).load()
    for s in Stage.ordered():
        assert final["stages"][s.value]["status"] == StageStatus.DONE.value


def test_run_resume_skips_done_stages(job_dir: Path, fake_process):
    """Resume: pre-mark INGEST+INDEX as DONE; only 3 subprocesses should spawn."""
    state = JobStateFile(job_dir)
    state.mark_stage(Stage.INGEST, StageStatus.DONE)
    state.mark_stage(Stage.INDEX, StageStatus.DONE)

    for stage in Stage.ordered():
        def make_handler(s):
            return lambda jd: JobStateFile(jd).mark_stage(s, StageStatus.DONE)
        register_stage_handler(stage, make_handler(stage))

    runner = PipelineRunner(job_dir)
    result = runner.run(resume=True)

    assert result == StageStatus.DONE
    assert len(fake_process.instances) == 3  # SCRIPT + ASSEMBLY + RENDER only
    spawned_stages = [p.args[0] for p in fake_process.instances]
    assert spawned_stages == [Stage.SCRIPT.value, Stage.ASSEMBLY.value, Stage.RENDER.value]


def test_run_resume_false_reruns_all(job_dir: Path, fake_process):
    """resume=False: even if stages are DONE, re-execute all 5."""
    state = JobStateFile(job_dir)
    state.mark_stage(Stage.INGEST, StageStatus.DONE)
    state.mark_stage(Stage.INDEX, StageStatus.DONE)

    for stage in Stage.ordered():
        def make_handler(s):
            return lambda jd: JobStateFile(jd).mark_stage(s, StageStatus.DONE)
        register_stage_handler(stage, make_handler(stage))

    runner = PipelineRunner(job_dir)
    result = runner.run(resume=False)

    assert result == StageStatus.DONE
    assert len(fake_process.instances) == 5


def test_run_aborts_on_failed_stage(job_dir: Path, fake_process):
    """If SCRIPT stage fails, ASSEMBLY/RENDER must not be spawned."""
    for stage in Stage.ordered():
        if stage == Stage.SCRIPT:
            def crash(jd: Path) -> None:
                raise RuntimeError("script boom")
            register_stage_handler(stage, crash)
        else:
            def make_handler(s):
                return lambda jd: JobStateFile(jd).mark_stage(s, StageStatus.DONE)
            register_stage_handler(stage, make_handler(stage))

    runner = PipelineRunner(job_dir)
    result = runner.run()

    assert result == StageStatus.FAILED
    spawned_stages = [p.args[0] for p in fake_process.instances]
    assert spawned_stages == [Stage.INGEST.value, Stage.INDEX.value, Stage.SCRIPT.value]
    assert Stage.ASSEMBLY.value not in spawned_stages

    # SCRIPT stage error captured
    slot = JobStateFile(job_dir).load()["stages"][Stage.SCRIPT.value]
    assert slot["status"] == StageStatus.FAILED.value
    assert "script boom" in slot["error"]


def test_run_aborts_on_cancel_between_stages(job_dir: Path, fake_process):
    """Cancel signal raised after INGEST → INDEX should NOT spawn."""

    def ingest_then_cancel(jd: Path) -> None:
        JobStateFile(jd).mark_stage(Stage.INGEST, StageStatus.DONE)
        # Simulate user clicking cancel mid-pipeline
        JobStateFile(jd).request_cancel()

    register_stage_handler(Stage.INGEST, ingest_then_cancel)
    for stage in [Stage.INDEX, Stage.SCRIPT, Stage.ASSEMBLY, Stage.RENDER]:
        register_stage_handler(stage, lambda jd: None)

    runner = PipelineRunner(job_dir)
    with pytest.raises(PipelineRunnerError, match="cancelled"):
        runner.run()

    # Only INGEST spawned; INDEX never reached
    spawned_stages = [p.args[0] for p in fake_process.instances]
    assert spawned_stages == [Stage.INGEST.value]


def test_run_defensive_failure_when_handler_silent(job_dir: Path, monkeypatch):
    """If subprocess exits 0 but stage status != DONE → marked FAILED defensively."""
    # Custom FakeProcess that does NOT invoke the target (simulating handler
    # that mysteriously didn't mark DONE despite exiting cleanly)
    class SilentProcess:
        def __init__(self, target=None, args=(), name=None, **kwargs):  # noqa: ANN
            self.target = target
            self.args = args
            self.exitcode: int | None = None

        def start(self) -> None:
            pass

        def join(self, timeout=None) -> None:  # noqa: ARG002
            self.exitcode = 0  # exit clean WITHOUT invoking target

    monkeypatch.setattr(runner_mod.mp, "Process", SilentProcess)

    runner = PipelineRunner(job_dir)
    result = runner.run()

    assert result == StageStatus.FAILED
    # INGEST should be marked FAILED with helpful error
    slot = JobStateFile(job_dir).load()["stages"][Stage.INGEST.value]
    assert slot["status"] == StageStatus.FAILED.value
    assert "not marked DONE" in slot["error"]


def test_run_subprocess_crash_with_no_state_update(job_dir: Path, monkeypatch):
    """Subprocess exits non-zero AND state.json untouched → FAILED with synthetic error."""
    class CrashProcess:
        def __init__(self, target=None, args=(), name=None, **kwargs):  # noqa: ANN
            self.target = target
            self.args = args
            self.exitcode: int | None = None

        def start(self) -> None:
            pass

        def join(self, timeout=None) -> None:  # noqa: ARG002
            self.exitcode = 137  # SIGKILL — no chance to update state

    monkeypatch.setattr(runner_mod.mp, "Process", CrashProcess)

    runner = PipelineRunner(job_dir)
    result = runner.run()

    assert result == StageStatus.FAILED
    slot = JobStateFile(job_dir).load()["stages"][Stage.INGEST.value]
    assert slot["status"] == StageStatus.FAILED.value
    assert "137" in slot["error"]


def test_run_raises_when_state_missing(tmp_path: Path):
    """Empty job_dir without state.json → PipelineRunnerError."""
    runner = PipelineRunner(tmp_path)  # no init_state called
    with pytest.raises(PipelineRunnerError, match="state.json missing"):
        runner.run()


def test_run_clears_stale_cancel_at_start(job_dir: Path, fake_process):
    """If .cancel exists from prior session, runner should clear it on run()."""
    state = JobStateFile(job_dir)
    state.request_cancel()
    assert state.is_cancelled()

    for stage in Stage.ordered():
        def make_handler(s):
            return lambda jd: JobStateFile(jd).mark_stage(s, StageStatus.DONE)
        register_stage_handler(stage, make_handler(stage))

    runner = PipelineRunner(job_dir)
    result = runner.run()

    assert result == StageStatus.DONE
    assert not state.is_cancelled()


# Suppress sys.modules pollution warning when running under pytest
assert sys is not None  # noqa: S101
