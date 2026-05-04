"""Ingest stage handler — dual-track normalize + audio extract (M1.6).

Reference:
- design.md Part IV §24 (ADR-010 dual-track normalize)
- docs/plans/tasks/M1-infrastructure.md §M1.6

Responsibilities:
1. Locate the user-uploaded raw video at `job_dir/raw/<filename>`.
2. ffprobe → ProbeResult (also gives source height for hd no-upscale logic).
3. Run 3 ffmpeg passes (or 2 in single-track emergency mode):
     - normalize_low.mp4   (720p / 25fps for PySceneDetect + Whisper feed)
     - normalize_hd.mp4    (≤1080p / orig fps for render)  — skipped if INGEST_SINGLE_TRACK=1
     - audio.wav           (16kHz mono pcm_s16le for ASR)
4. Report progress at each milestone (0.05 / 0.45 / 0.85 / 0.95 / 1.0).
5. Check `is_cancelled()` between every ffmpeg pass.

Contract with PipelineRunner (see runner.py `_stage_entrypoint`):
- We intentionally do NOT wrap our body in try/except — `_stage_entrypoint`
  already catches and marks FAILED for us.
- We DO actively call `mark_stage(DONE)` at the end (rather than relying on
  the defensive auto-DONE) for clarity and explicit progress=1.0 semantics.
- Cancellation is signaled by raising `IngestCancelledError` (subclass of
  RuntimeError); the entrypoint will mark FAILED with this error message.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from loguru import logger

from autoclip.pipeline.runner import register_stage_handler
from autoclip.pipeline.state import JobStateFile, Stage, StageStatus
from autoclip.utils.ffmpeg import (
    ProbeResult,
    build_extract_audio_cmd,
    build_normalize_hd_cmd,
    build_normalize_low_cmd,
    probe_video,
)

# Output filenames (constants so tests + downstream stages stay in sync).
RAW_DIRNAME = "raw"
LOW_FILENAME = "normalized_low.mp4"
HD_FILENAME = "normalized_hd.mp4"
AUDIO_FILENAME = "audio.wav"

# Emergency switch (R18): when disk is tight, skip the hd track entirely.
# Render stage will then have to fall back to low (with quality loss).
ENV_SINGLE_TRACK = "INGEST_SINGLE_TRACK"

# Recognized raw video extensions (used to glob job_dir/raw/).
SUPPORTED_VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".m4v", ".webm", ".avi")

# Hard wall-clock cap for any single ffmpeg pass (defense vs hung pipes).
# 30min should comfortably handle a 90min source on M3 Pro.
FFMPEG_TIMEOUT_SEC = 30 * 60


class IngestError(RuntimeError):
    """Raised when ingest cannot complete (missing input, ffmpeg failure, etc)."""


class IngestCancelledError(IngestError):
    """Raised when `.cancel` flag is observed mid-pass."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_source_video(job_dir: Path) -> Path:
    """Locate the single uploaded raw video file under `job_dir/raw/`.

    Raises IngestError if the directory is missing or contains 0 / >1 videos.
    """
    raw_dir = job_dir / RAW_DIRNAME
    if not raw_dir.is_dir():
        raise IngestError(
            f"raw directory missing: {raw_dir}. Upload step must place the "
            f"original file at {raw_dir}/<filename>."
        )

    candidates = sorted(
        p
        for p in raw_dir.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_VIDEO_EXTS
    )
    if not candidates:
        raise IngestError(
            f"no video file found in {raw_dir}. "
            f"Supported extensions: {', '.join(SUPPORTED_VIDEO_EXTS)}"
        )
    if len(candidates) > 1:
        names = ", ".join(p.name for p in candidates)
        raise IngestError(
            f"expected exactly 1 video in {raw_dir}, found {len(candidates)}: {names}"
        )
    return candidates[0]


def _is_single_track_mode() -> bool:
    """Read INGEST_SINGLE_TRACK env var (R18 emergency switch)."""
    raw = os.environ.get(ENV_SINGLE_TRACK, "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _check_cancel(state: JobStateFile, where: str) -> None:
    """Raise IngestCancelledError if user requested cancellation."""
    if state.is_cancelled():
        raise IngestCancelledError(f"cancelled before {where}")


def _run_ffmpeg(cmd: list[str], step_label: str) -> None:
    """Invoke ffmpeg synchronously with a hard timeout. Raises IngestError on failure."""
    logger.info("[ingest] {} : {}", step_label, " ".join(cmd))
    try:
        result = subprocess.run(  # noqa: S603 — args list, no shell
            cmd,
            capture_output=True,
            text=True,
            timeout=FFMPEG_TIMEOUT_SEC,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise IngestError(
            f"{step_label} timed out after {FFMPEG_TIMEOUT_SEC}s"
        ) from exc

    if result.returncode != 0:
        # ffmpeg's useful diagnostics live on stderr.
        tail = (result.stderr or "").strip().splitlines()[-10:]
        raise IngestError(
            f"{step_label} failed (exit={result.returncode}): "
            + " | ".join(tail)
        )


# ---------------------------------------------------------------------------
# Stage handler
# ---------------------------------------------------------------------------


def run_ingest(job_dir: Path) -> None:
    """Stage handler entrypoint registered with `Stage.INGEST`."""
    state = JobStateFile(job_dir)
    single_track = _is_single_track_mode()

    logger.info(
        "[ingest] start job_dir={} single_track={}",
        job_dir,
        single_track,
    )

    # --- Step 1: locate raw + probe (progress 0.05) ---
    _check_cancel(state, "probe")
    src = _find_source_video(job_dir)
    probe: ProbeResult = probe_video(src)
    logger.info(
        "[ingest] probed src={} {}x{}@{:.2f}fps duration={:.2f}s",
        src.name,
        probe.width,
        probe.height,
        probe.fps,
        probe.duration_sec,
    )
    state.mark_stage(Stage.INGEST, StageStatus.RUNNING, progress=0.05)

    # --- Step 2: normalize low (720p) — required (progress 0.45) ---
    _check_cancel(state, "normalize_low")
    low_dst = job_dir / LOW_FILENAME
    _run_ffmpeg(build_normalize_low_cmd(src, low_dst), "normalize_low")
    state.mark_stage(Stage.INGEST, StageStatus.RUNNING, progress=0.45)

    # --- Step 3: normalize hd (≤1080p) — skipped in single-track mode (progress 0.85) ---
    if single_track:
        logger.warning(
            "[ingest] INGEST_SINGLE_TRACK=1 — skipping hd track (R18 mitigation). "
            "Render stage will need to use {} as source.",
            LOW_FILENAME,
        )
    else:
        _check_cancel(state, "normalize_hd")
        hd_dst = job_dir / HD_FILENAME
        _run_ffmpeg(
            build_normalize_hd_cmd(src, hd_dst, source_height=probe.height),
            "normalize_hd",
        )
    state.mark_stage(Stage.INGEST, StageStatus.RUNNING, progress=0.85)

    # --- Step 4: extract audio.wav from hd (or low if single-track) (progress 0.95) ---
    _check_cancel(state, "extract_audio")
    audio_src = job_dir / (LOW_FILENAME if single_track else HD_FILENAME)
    audio_dst = job_dir / AUDIO_FILENAME
    _run_ffmpeg(build_extract_audio_cmd(audio_src, audio_dst), "extract_audio")
    state.mark_stage(Stage.INGEST, StageStatus.RUNNING, progress=0.95)

    # --- Step 5: mark DONE (progress 1.0) ---
    state.mark_stage(Stage.INGEST, StageStatus.DONE)
    logger.info("[ingest] DONE job_dir={}", job_dir)


# Register on import (PipelineRunner imports this module via _STAGE_MODULES).
register_stage_handler(Stage.INGEST, run_ingest)
