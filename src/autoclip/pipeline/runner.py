"""PipelineRunner — serial 5-stage scheduler over multiprocessing subprocesses.

Reference: design.md §16.2 (multiprocessing as fault isolation boundary).

Design contract (per M1.4 key-design):
- Each stage runs in `mp.Process(spawn)` for fault isolation + macOS/Win compat
- Global `_STAGE_HANDLERS: dict[Stage, Callable[[Path], None]]` populated via
  `register_stage_handler()` at module import time
- Subprocess MUST re-import all stage modules (spawn doesn't inherit parent state)
- Failure detection is DEFENSIVE:
    1. exitcode != 0 → mark FAILED
    2. exitcode == 0 BUT JobStateFile.status != DONE → also mark FAILED
       (defends against handlers that forget to mark DONE)
- Cancellation is checked BETWEEN stages only; in-stage cancellation is the
  handler's responsibility (per M1.4 Q3 decision)
"""

from __future__ import annotations

import contextlib
import importlib
import logging
import multiprocessing as mp
import os
import sys
from collections.abc import Callable
from pathlib import Path

from .state import JobStateFile, Stage, StageState, StageStatus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Multiprocessing start method (spawn — required for macOS/Windows compat)
# ---------------------------------------------------------------------------

# Set globally; safe to call once. force=True overrides any prior setting.
# Wrapped in suppress so re-import (e.g. in test reloads) doesn't crash.
with contextlib.suppress(RuntimeError):
    mp.set_start_method("spawn", force=True)  # already-set raises RuntimeError


# ---------------------------------------------------------------------------
# Stage handler registry
# ---------------------------------------------------------------------------

StageHandler = Callable[[Path], None]
"""Signature: handler(job_dir: Path) -> None

State transition contract (as of M1.8 LIM#8 fix; verified against `_stage_entrypoint`):

- RUNNING(progress=0.0) — initial transition is OWNED BY ``_stage_entrypoint``,
  which calls ``mark_stage(stage, RUNNING, progress=0.0)`` BEFORE invoking the
  handler. Handlers MUST NOT call ``mark_stage(RUNNING, progress=0.0)`` themselves;
  doing so is a redundant atomic write and muddles ownership of ``started_at``.

- RUNNING(progress>0.0) — handlers MAY call ``mark_stage(stage, RUNNING,
  progress=N)`` at sub-stage milestones to report progress (e.g. ingest.py uses
  0.05 / 0.45 / 0.85 / 0.95; index.py uses 0.3 / 0.95). The progress field is
  ``set`` not ``monotonic`` (see LIM#7) — callers should write monotonically by
  convention.

- DONE — handlers SHOULD call ``mark_stage(stage, DONE)`` at the end of
  successful execution. ``_stage_entrypoint`` has a defensive safety net that
  marks DONE if the handler returns without doing so, but handlers should not
  rely on it (the safety net exists to prevent silent state corruption, not as
  a feature).

- FAILED — handlers SHOULD raise an exception on failure; ``_stage_entrypoint``
  catches all exceptions, calls ``mark_stage(stage, FAILED, error=...)``, and
  exits with code 1. Handlers MAY call ``mark_stage(FAILED)`` themselves before
  raising (e.g. for richer error context), but this is not required — the
  entrypoint's catch-all is the canonical FAILED transition.

Cancellation: handlers should call ``raise_if_cancelled(state)`` (or equivalent)
at safe checkpoints. Cancellation is delivered as an exception that the
entrypoint catches and marks FAILED with a recognizable error message.
"""

_STAGE_HANDLERS: dict[Stage, StageHandler] = {}


def register_stage_handler(stage: Stage, handler: StageHandler) -> None:
    """Register a handler function for one Stage. Idempotent (last-wins)."""
    _STAGE_HANDLERS[stage] = handler


def get_stage_handler(stage: Stage) -> StageHandler | None:
    """Look up a registered handler. Returns None if not registered."""
    return _STAGE_HANDLERS.get(stage)


def clear_stage_handlers() -> None:
    """Test helper: wipe the registry."""
    _STAGE_HANDLERS.clear()


# Names of stage modules that must be imported in subprocess to trigger
# their `register_stage_handler()` side effects.
# Modules are added here as they're implemented in M1.6, M1.7, M1.8...
_STAGE_MODULES: tuple[str, ...] = (
    "autoclip.pipeline.ingest",  # M1.6 — dual-track normalize + audio extract
    "autoclip.pipeline.index",   # M1.8 — shot detection + ASR + audio.wav cleanup (K9)
    # "autoclip.pipeline.scripting",
    # "autoclip.pipeline.assembly",
    # "autoclip.pipeline.render",
)


# Env var for injecting extra stage modules (test fixtures, plugins).
# Spawn subprocesses inherit env vars, so this is the cross-process channel.
# Format: colon-separated module paths, e.g. "tests.fixtures.fake_handlers"
ENV_EXTRA_STAGE_MODULES = "AUTOCLIP_EXTRA_STAGE_MODULES"


def _load_stage_modules() -> None:
    """Import all real stage modules so their handlers register.

    Called from both the parent process (PipelineRunner.__init__) and the
    subprocess entrypoint (since spawn doesn't inherit parent's imports).

    Sources:
    - `_STAGE_MODULES` — static list compiled into the codebase (M1.6+)
    - `$AUTOCLIP_EXTRA_STAGE_MODULES` — colon-separated runtime injection
      (used by tests and future plugin systems; survives spawn boundary)
    """
    extra_env = os.environ.get(ENV_EXTRA_STAGE_MODULES, "")
    extra_mods = tuple(m for m in extra_env.split(":") if m.strip())
    for mod_name in (*_STAGE_MODULES, *extra_mods):
        try:
            importlib.import_module(mod_name)
        except ImportError as e:
            logger.warning("Failed to import stage module %s: %s", mod_name, e)


# ---------------------------------------------------------------------------
# Subprocess entrypoint (top-level for pickling under spawn)
# ---------------------------------------------------------------------------

def _stage_entrypoint(stage_name: str, job_dir_str: str) -> None:
    """Subprocess entrypoint. Runs ONE stage handler.

    MUST be top-level (module-scope) so it pickles cleanly under spawn.
    Re-imports stage modules to populate _STAGE_HANDLERS in this fresh
    interpreter, then dispatches to the handler.
    """
    stage = Stage(stage_name)
    job_dir = Path(job_dir_str)
    state = JobStateFile(job_dir)

    # Re-import stage modules in this fresh interpreter
    _load_stage_modules()

    handler = get_stage_handler(stage)
    if handler is None:
        state.mark_stage(
            stage,
            StageStatus.FAILED,
            error=f"No handler registered for stage {stage.value!r}",
        )
        sys.exit(2)

    state.mark_stage(stage, StageStatus.RUNNING, progress=0.0)
    try:
        handler(job_dir)
    except Exception as exc:  # noqa: BLE001
        # Handler crashed — record error and signal failure to parent
        state.mark_stage(stage, StageStatus.FAILED, error=f"{type(exc).__name__}: {exc}")
        # Re-raise via sys.exit to set exitcode != 0
        logger.exception("Stage %s handler raised", stage.value)
        sys.exit(1)

    # Defensive: if handler returned without marking DONE, mark it now
    # (handlers SHOULD mark DONE themselves, but this is the safety net)
    final = StageState.from_dict(state.load()["stages"][stage.value])
    if final.status != StageStatus.DONE:
        state.mark_stage(stage, StageStatus.DONE)


# ---------------------------------------------------------------------------
# PipelineRunner — main scheduler
# ---------------------------------------------------------------------------

class PipelineRunnerError(Exception):
    """Raised when pipeline cannot complete (cancelled / stage failed / etc)."""


class PipelineRunner:
    """Serial 5-stage pipeline scheduler.

    Usage:
        runner = PipelineRunner(job_dir)
        runner.run()  # blocks until all stages DONE or one FAILED
    """

    def __init__(self, job_dir: Path) -> None:
        self.job_dir = Path(job_dir)
        self.state = JobStateFile(self.job_dir)
        # Eagerly load stage modules in parent (so dispatch bookkeeping works)
        _load_stage_modules()

    def run(self, *, resume: bool = True) -> StageStatus:
        """Run the pipeline to completion.

        Args:
            resume: If True (default), skip stages already marked DONE.
                    If False, run from INGEST regardless of prior state.

        Returns:
            StageStatus.DONE if all 5 stages succeeded.
            StageStatus.FAILED if any stage failed.

        Raises:
            PipelineRunnerError: If cancelled mid-run or no state.json present.
        """
        if not self.state.exists():
            raise PipelineRunnerError(f"state.json missing in {self.job_dir}")

        if not resume:
            # Reset all stages to PENDING (does not touch metadata)
            current = self.state.load()
            for s in Stage.ordered():
                current["stages"][s.value] = StageState().to_dict()
            self.state._save_atomic(current)  # noqa: SLF001 — internal helper

        # Clear any stale cancel signal at start
        self.state.clear_cancel()

        while True:
            # Cancel check BEFORE picking next stage
            if self.state.is_cancelled():
                logger.info("Pipeline cancelled at job_dir=%s", self.job_dir)
                raise PipelineRunnerError("Pipeline cancelled by user")

            stage = self.state.next_stage_to_run()
            if stage is None:
                logger.info("Pipeline complete: all stages DONE")
                return StageStatus.DONE

            logger.info("Running stage %s in subprocess", stage.value)
            failed = self._spawn_stage(stage)
            if failed:
                logger.error("Stage %s failed — pipeline aborted", stage.value)
                return StageStatus.FAILED

    def _spawn_stage(self, stage: Stage) -> bool:
        """Spawn one stage subprocess and wait. Returns True if stage failed."""
        proc = mp.Process(
            target=_stage_entrypoint,
            args=(stage.value, str(self.job_dir)),
            name=f"autoclip-stage-{stage.value}",
        )
        proc.start()
        proc.join()

        # Defensive failure detection: BOTH exitcode AND state.json must agree
        slot = StageState.from_dict(self.state.load()["stages"][stage.value])

        if proc.exitcode != 0:
            # Subprocess crashed; ensure FAILED is recorded (entrypoint may
            # have failed before getting to mark_stage)
            if slot.status != StageStatus.FAILED:
                self.state.mark_stage(
                    stage,
                    StageStatus.FAILED,
                    error=slot.error or f"Subprocess exited with code {proc.exitcode}",
                )
            return True

        if slot.status != StageStatus.DONE:
            # Subprocess returned 0 but didn't mark DONE — handler bug
            self.state.mark_stage(
                stage,
                StageStatus.FAILED,
                error=f"Handler exited cleanly but stage not marked DONE (got {slot.status.value})",
            )
            return True

        return False
