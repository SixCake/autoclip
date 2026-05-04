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
# Tests — StageHandler contract (LIM#8 fix; see runner.StageHandler docstring)
#
# These tests pin down the 4 contract claims so future handler authors and
# future entrypoint refactors can't silently violate the docstring.
# ---------------------------------------------------------------------------

def test_entrypoint_marks_running_before_handler_invoked(job_dir: Path):
    """Contract clause 1 (RUNNING ownership): entrypoint marks
    RUNNING(progress=0.0) BEFORE the handler runs, so the handler can observe
    its own RUNNING state from the very first instruction (proving started_at
    is already stamped by the entrypoint, not the handler)."""
    observed_at_handler_entry: dict[str, object] = {}

    def observing_handler(jd: Path) -> None:
        slot = JobStateFile(jd).load()["stages"][Stage.INGEST.value]
        observed_at_handler_entry["status"] = slot["status"]
        observed_at_handler_entry["progress"] = slot["progress"]
        observed_at_handler_entry["started_at"] = slot["started_at"]

    register_stage_handler(Stage.INGEST, observing_handler)
    _stage_entrypoint(Stage.INGEST.value, str(job_dir))

    # Positive: handler observed RUNNING(0.0) on entry
    assert observed_at_handler_entry["status"] == StageStatus.RUNNING.value
    assert observed_at_handler_entry["progress"] == 0.0
    # Reverse: started_at was NOT None when the handler started running, i.e.
    # the entrypoint stamped it, NOT the handler. This is the test that would
    # have caught the Round 3 BUG#7 misconception (handler "must" mark RUNNING).
    assert observed_at_handler_entry["started_at"] is not None


def test_entrypoint_catches_failed_when_handler_does_not_self_mark(job_dir: Path):
    """Contract clause 4 (FAILED ownership): entrypoint catches the exception
    and marks FAILED on its own; handler does NOT need to call mark_stage(FAILED)
    before raising. This is the canonical FAILED transition."""
    def silent_failing_handler(jd: Path) -> None:
        # Note: deliberately does NOT call mark_stage(FAILED) before raising.
        # Per docstring contract, the entrypoint's catch-all is canonical.
        raise RuntimeError("handler crashed without self-marking FAILED")

    register_stage_handler(Stage.INGEST, silent_failing_handler)
    with pytest.raises(SystemExit) as exc_info:
        _stage_entrypoint(Stage.INGEST.value, str(job_dir))
    assert exc_info.value.code == 1

    slot = JobStateFile(job_dir).load()["stages"][Stage.INGEST.value]
    # Positive: status is FAILED with handler's exception info
    assert slot["status"] == StageStatus.FAILED.value
    assert "RuntimeError" in slot["error"]
    assert "handler crashed without self-marking FAILED" in slot["error"]
    # Reverse: the handler did NOT mark FAILED itself, yet status is still
    # FAILED — proves the entrypoint owns this transition.


def test_entrypoint_defensive_done_safety_net_when_handler_silent(job_dir: Path):
    """Contract clause 3 (DONE safety net): if a handler returns successfully
    WITHOUT calling mark_stage(DONE), the entrypoint marks DONE on its behalf
    rather than leaving status stuck at RUNNING. Documented in docstring as a
    safety net (not a feature handlers should rely on)."""
    def silent_succeeding_handler(jd: Path) -> None:
        # Returns successfully WITHOUT calling mark_stage(DONE).
        # Should NOT happen in well-written handlers, but the entrypoint must
        # handle it to prevent silent state corruption.
        return

    register_stage_handler(Stage.INGEST, silent_succeeding_handler)
    _stage_entrypoint(Stage.INGEST.value, str(job_dir))

    slot = JobStateFile(job_dir).load()["stages"][Stage.INGEST.value]
    # Positive: status is DONE despite handler not marking it
    assert slot["status"] == StageStatus.DONE.value
    # Reverse: status is NOT stuck at RUNNING (which would be the case if the
    # safety net didn't fire) — this catches a future regression where someone
    # removes the L147-150 defensive block in _stage_entrypoint.
    assert slot["status"] != StageStatus.RUNNING.value


def test_entrypoint_preserves_handler_progress_reports(job_dir: Path):
    """Contract clause 2 (RUNNING(progress>0.0) handler-owned): handler may
    call mark_stage(RUNNING, progress=N) at sub-stage milestones, and the
    entrypoint must NOT overwrite those reports with its own RUNNING(0.0).
    The entrypoint marks RUNNING(0.0) ONCE before the handler runs; afterwards
    progress >0.0 belongs to the handler."""
    progress_observations: list[float] = []

    def progressing_handler(jd: Path) -> None:
        state = JobStateFile(jd)
        for milestone_progress in (0.25, 0.5, 0.75):
            state.mark_stage(Stage.INGEST, StageStatus.RUNNING, progress=milestone_progress)
            after = state.load()["stages"][Stage.INGEST.value]["progress"]
            progress_observations.append(after)
        state.mark_stage(Stage.INGEST, StageStatus.DONE, progress=1.0)

    register_stage_handler(Stage.INGEST, progressing_handler)
    _stage_entrypoint(Stage.INGEST.value, str(job_dir))

    # Positive: every milestone the handler wrote was preserved (no
    # entrypoint clobbering between handler writes)
    assert progress_observations == [0.25, 0.5, 0.75]
    final_slot = JobStateFile(job_dir).load()["stages"][Stage.INGEST.value]
    assert final_slot["status"] == StageStatus.DONE.value
    assert final_slot["progress"] == 1.0


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
