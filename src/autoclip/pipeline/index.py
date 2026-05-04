"""Index stage handler — shot detection + ASR + audio.wav cleanup (M1.8).

Reference:
- design.md §6 (Index stage products: shots.json + asr.json)
- design.md Part IV §16.5 (K9 zero-knowledge: audio.wav deleted after Index)
- docs/plans/tasks/M1-infrastructure.md §M1.8

Responsibilities:
1. Locate normalized_low.mp4 and audio.wav (produced by Ingest stage M1.6).
2. detect_shots(normalized_low.mp4) -> shots.json   [progress 0.0 -> 0.3]
3. ASR transcribe(audio.wav)        -> asr.json     [progress 0.3 -> 0.95]
4. unlink audio.wav (K9 zero-knowledge)             [progress 0.95 -> 1.0]
5. mark Stage.INDEX DONE.

Resume semantics (key design decision #8):
- If shots.json already exists from a prior failed run, skip re-detection
  (saves ~30s CPU on a 90min movie). asr.json is NEVER reused — partial
  writes from a crash mid-transcription would be silently corrupt.

Cancel checkpoints:
- Before shot detection (cheap to abort).
- After shot detection / before ASR (ASR can run for minutes).

Contract with PipelineRunner (see runner.py `_stage_entrypoint`):
- We do NOT wrap our body in try/except — `_stage_entrypoint` already
  catches and marks FAILED for us.
- We DO actively call `mark_stage(DONE)` at the end (rather than rely on
  the defensive auto-DONE) for clarity and explicit progress=1.0 semantics.
- Cancellation is signaled by raising IndexStageCancelledError.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from loguru import logger

from autoclip.algo.shot_detector import Shot, detect_shots
from autoclip.config import get_settings
from autoclip.pipeline.ingest import AUDIO_FILENAME, LOW_FILENAME
from autoclip.pipeline.runner import register_stage_handler
from autoclip.pipeline.state import JobStateFile, Stage, StageStatus
from autoclip.providers.asr.base import ASRProvider, ASRResult
from autoclip.providers.asr.local_whisper import LocalWhisperProvider

# Output filenames (constants so tests + downstream stages stay in sync).
SHOTS_FILENAME = "shots.json"
ASR_FILENAME = "asr.json"

# JSON dump style (match state.json: utf-8, indent=2, no ASCII escapes).
_JSON_DUMP_KWARGS: dict[str, Any] = {
    "ensure_ascii": False,
    "indent": 2,
    "sort_keys": False,
}


# Note: NOT a custom IndexError subclass. Python's builtin IndexError
# (raised by list[i] when out-of-range) is unrelated to our pipeline stage,
# but a name collision would mask real bugs in stack traces. Use the
# IndexStage* prefix everywhere instead.
class IndexStageError(RuntimeError):
    """Raised when the Index stage cannot complete."""


class IndexStageCancelledError(IndexStageError):
    """Raised when `.cancel` flag is observed mid-stage."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_cancel(state: JobStateFile, where: str) -> None:
    """Raise IndexStageCancelledError if user requested cancellation."""
    if state.is_cancelled():
        raise IndexStageCancelledError(f"cancelled before {where}")


def _build_asr_provider() -> ASRProvider:
    """Construct the default ASR provider from Settings.

    Module-level seam so unit tests can monkeypatch
    `autoclip.pipeline.index._build_asr_provider` to inject fakes
    (otherwise tests would have to monkeypatch faster_whisper which is
    much more invasive).
    """
    settings = get_settings()
    return LocalWhisperProvider(
        model_size=settings.whisper_model_size,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
    )


def _load_existing_shots(shots_path: Path) -> list[Shot] | None:
    """Try to reload shots.json from a prior run. Returns None on data corruption.

    Used for crash-recovery: if a previous Index run completed shot detection
    but failed during ASR, we skip the (expensive) re-detection on retry.

    We swallow ONLY data-corruption errors (malformed JSON, missing fields,
    wrong types). Real OS-level failures (PermissionError, IsADirectoryError,
    disk I/O errors) are deliberately allowed to propagate — silently treating
    a permission-denied error as "corrupt file → re-detect" would let
    detect_shots run for 30s only to fail at the same write step, hiding
    the real root cause.
    """
    if not shots_path.exists():
        return None
    try:
        payload = json.loads(shots_path.read_text(encoding="utf-8"))
        shots = [
            Shot(
                idx=int(s["idx"]),
                start_sec=float(s["start_sec"]),
                end_sec=float(s["end_sec"]),
            )
            for s in payload["shots"]
        ]
    except (json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
        # Note: json.JSONDecodeError is a subclass of ValueError; listed
        # explicitly for clarity. OSError is intentionally NOT caught here.
        logger.warning(
            "[index] existing {} unreadable ({}); will re-detect",
            shots_path.name,
            exc,
        )
        return None
    if not shots:
        # An empty list passed schema but contains no usable data — re-detect.
        return None
    logger.info(
        "[index] reusing existing {} ({} shots) — skipping re-detection",
        shots_path.name,
        len(shots),
    )
    return shots


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON crash-safely: tmp + flush + fsync + os.replace.

    Mirrors the write strategy in `state.py::_save_atomic` so all
    pipeline-produced JSON artifacts share identical durability guarantees.
    Without fsync, an OS crash between write() and the next sync could leave
    the tmp file empty, after which os.replace would atomically install an
    empty file as the "atomic" output.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, **_JSON_DUMP_KWARGS)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _shots_to_payload(shots: list[Shot]) -> dict[str, Any]:
    """Build the shots.json payload from an ordered list of Shot."""
    total_duration = sum(s.duration_sec for s in shots) if shots else 0.0
    return {
        "n_shots": len(shots),
        "total_duration_sec": round(total_duration, 3),
        "shots": [s.to_dict() for s in shots],
    }


# ---------------------------------------------------------------------------
# Stage handler
# ---------------------------------------------------------------------------


def run_index(job_dir: Path) -> None:
    """Stage handler entrypoint registered with `Stage.INDEX`."""
    state = JobStateFile(job_dir)

    low_path = job_dir / LOW_FILENAME
    audio_path = job_dir / AUDIO_FILENAME
    shots_path = job_dir / SHOTS_FILENAME
    asr_path = job_dir / ASR_FILENAME

    logger.info("[index] start job_dir={}", job_dir)

    # --- Pre-flight: required inputs from Ingest stage ---
    if not low_path.exists():
        raise IndexStageError(
            f"required input missing: {low_path} (Ingest stage M1.6 produces this)"
        )
    if not audio_path.exists():
        raise IndexStageError(
            f"required input missing: {audio_path} (Ingest stage M1.6 produces this)"
        )

    # NOTE on RUNNING state: runner._stage_entrypoint already calls
    # `mark_stage(stage, RUNNING, progress=0.0)` BEFORE invoking this handler
    # (see runner.py `_stage_entrypoint`), so `started_at` is already stamped.
    # We deliberately do NOT call mark_stage(RUNNING) here — that would be a
    # redundant atomic write with fsync, and would muddle the contract about
    # who owns the RUNNING transition (the runner does).

    # --- Step 1: shot detection (or reuse from prior run) — progress 0.3 ---
    _check_cancel(state, "shot_detection")
    shots = _load_existing_shots(shots_path)
    if shots is None:
        logger.info("[index] running detect_shots on {}", low_path.name)
        shots = detect_shots(low_path)
        # Defensive: detect_shots currently has a zero-scene → single-shot fallback,
        # but we don't want to silently depend on that contract. Empty shots is a
        # hard error here because downstream (M2a scripting) cannot operate on it.
        if not shots:
            raise IndexStageError(
                f"detect_shots returned empty list for {low_path.name}; "
                "video may be unreadable or all-black"
            )
        _atomic_write_json(shots_path, _shots_to_payload(shots))
        logger.info(
            "[index] shots.json written: n_shots={} first=[{:.2f},{:.2f}]s "
            "last=[{:.2f},{:.2f}]s",
            len(shots),
            shots[0].start_sec,
            shots[0].end_sec,
            shots[-1].start_sec,
            shots[-1].end_sec,
        )
    state.mark_stage(Stage.INDEX, StageStatus.RUNNING, progress=0.3)

    # --- Step 2: ASR transcription — progress 0.95 ---
    _check_cancel(state, "asr_transcribe")
    provider = _build_asr_provider()
    logger.info(
        "[index] transcribing {} via provider={}",
        audio_path.name,
        type(provider).__name__,
    )
    asr_result: ASRResult = provider.transcribe(audio_path)
    _atomic_write_json(asr_path, asr_result.to_dict())
    logger.info(
        "[index] asr.json written: n_sentences={} language={} provider={}",
        len(asr_result.sentences),
        asr_result.language,
        asr_result.provider,
    )
    state.mark_stage(Stage.INDEX, StageStatus.RUNNING, progress=0.95)

    # --- Step 3: K9 zero-knowledge — delete audio.wav (progress 1.0) ---
    # Use missing_ok=True so a manual partial cleanup between retries doesn't
    # blow up the stage; the post-condition is "audio.wav does not exist",
    # which is satisfied either way.
    audio_path.unlink(missing_ok=True)
    logger.info("[index] deleted {} (K9 zero-knowledge)", audio_path.name)

    # --- Step 4: mark DONE (progress=1.0 set automatically) ---
    state.mark_stage(Stage.INDEX, StageStatus.DONE)
    logger.info("[index] DONE job_dir={}", job_dir)


# Register on import (PipelineRunner imports this module via _STAGE_MODULES).
register_stage_handler(Stage.INDEX, run_index)
