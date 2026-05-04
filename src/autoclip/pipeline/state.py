"""File-based state machine for pipeline job execution.

Reference: design.md §16.2 (state file as multiprocessing sync medium).

Design constraints (per M1.3 key-design):
- state.json is THE single source of truth across mp.Process workers
- Atomic write: tmp file + os.rename (POSIX atomic guarantee)
- Cancel signal: presence of `.cancel` file (poll-based, no IPC)
- Resume semantics: skip DONE stages on next_stage_to_run()
"""

from __future__ import annotations

import enum
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Stage(str, enum.Enum):
    """The 5 fixed pipeline stages, in execution order."""

    INGEST = "ingest"
    INDEX = "index"
    SCRIPT = "script"
    ASSEMBLY = "assembly"
    RENDER = "render"

    @classmethod
    def ordered(cls) -> list[Stage]:
        return [cls.INGEST, cls.INDEX, cls.SCRIPT, cls.ASSEMBLY, cls.RENDER]


class StageStatus(str, enum.Enum):
    """Per-stage lifecycle status."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Per-stage state DTO
# ---------------------------------------------------------------------------

@dataclass
class StageState:
    """In-memory representation of one stage's slot in state.json."""

    status: StageStatus = StageStatus.PENDING
    progress: float = 0.0  # 0.0 .. 1.0
    error: str | None = None
    started_at: str | None = None  # ISO 8601
    finished_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StageState:
        return cls(
            status=StageStatus(d.get("status", StageStatus.PENDING.value)),
            progress=float(d.get("progress", 0.0)),
            error=d.get("error"),
            started_at=d.get("started_at"),
            finished_at=d.get("finished_at"),
        )


# ---------------------------------------------------------------------------
# JobStateFile — atomic R/W of state.json + cancel signal
# ---------------------------------------------------------------------------

STATE_FILENAME = "state.json"
CANCEL_FILENAME = ".cancel"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class _JobMeta:
    job_id: int
    video_hash: str
    target_duration_sec: int
    style_preset: str
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)


class JobStateFile:
    """Atomic state.json + cancel signal manager for one job directory."""

    def __init__(self, job_dir: Path) -> None:
        self.job_dir = Path(job_dir)
        self.job_dir.mkdir(parents=True, exist_ok=True)

    # --- paths ---
    @property
    def path(self) -> Path:
        return self.job_dir / STATE_FILENAME

    @property
    def tmp_path(self) -> Path:
        return self.job_dir / f"{STATE_FILENAME}.tmp"

    @property
    def cancel_path(self) -> Path:
        return self.job_dir / CANCEL_FILENAME

    # --- create / load ---
    def init_state(
        self,
        job_id: int,
        video_hash: str,
        target_duration_sec: int,
        style_preset: str = "plot_summary",
    ) -> dict[str, Any]:
        """Initialize a fresh state.json with all 5 stages PENDING."""
        meta = _JobMeta(
            job_id=job_id,
            video_hash=video_hash,
            target_duration_sec=target_duration_sec,
            style_preset=style_preset,
        )
        state = {
            **asdict(meta),
            "stages": {s.value: StageState().to_dict() for s in Stage.ordered()},
        }
        self._save_atomic(state)
        return state

    def load(self) -> dict[str, Any]:
        """Load current state.json from disk. Raises FileNotFoundError if missing."""
        with self.path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def exists(self) -> bool:
        return self.path.exists()

    # --- mutate ---
    def mark_stage(
        self,
        stage: Stage,
        status: StageStatus,
        progress: float | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        """Update one stage's status (and optional progress/error). Atomic."""
        state = self.load()
        slot = StageState.from_dict(state["stages"][stage.value])
        slot.status = status
        if progress is not None:
            slot.progress = max(0.0, min(1.0, float(progress)))
        if error is not None:
            slot.error = error
        if status == StageStatus.RUNNING and slot.started_at is None:
            slot.started_at = _now_iso()
        if status in (StageStatus.DONE, StageStatus.FAILED):
            slot.finished_at = _now_iso()
            if status == StageStatus.DONE:
                slot.progress = 1.0
        state["stages"][stage.value] = slot.to_dict()
        state["updated_at"] = _now_iso()
        self._save_atomic(state)
        return state

    # --- queries ---
    def next_stage_to_run(self) -> Stage | None:
        """Return the earliest non-DONE stage (resume semantics).

        Returns None if all 5 stages are DONE.
        FAILED / RUNNING / PENDING are all candidates for re-execution.
        """
        state = self.load()
        for stage in Stage.ordered():
            slot = StageState.from_dict(state["stages"][stage.value])
            if slot.status != StageStatus.DONE:
                return stage
        return None

    # --- cancel signal (presence of .cancel file) ---
    def request_cancel(self) -> None:
        """Touch `.cancel` to request graceful cancellation."""
        self.cancel_path.touch(exist_ok=True)

    def is_cancelled(self) -> bool:
        return self.cancel_path.exists()

    def clear_cancel(self) -> None:
        """Remove the `.cancel` flag (used on resume)."""
        if self.cancel_path.exists():
            self.cancel_path.unlink()

    # --- internals ---
    def _save_atomic(self, state: dict[str, Any]) -> None:
        """Write tmp file then os.rename to state.json (POSIX atomic)."""
        with self.tmp_path.open("w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(self.tmp_path, self.path)
