"""Shot detection — PySceneDetect ContentDetector wrapper (M1.7).

Reference:
- design.md §6.2 + ADR-003 (algorithm choice)
- docs/plans/tasks/M1-infrastructure.md §M1.7

Design contract:
- Pure algorithm layer: input is a video file path, output is `list[Shot]`.
  No state.json, no progress reporting, no cancel checking — those belong
  to the Index stage handler (M1.8) that calls this module.
- `Shot` is a frozen dataclass; field schema matches `models.shot.Shot` ORM
  (id excluded — that's a DB primary key) so M1.8 can persist without a
  conversion layer.
- `detect_shots()` falls back to a single shot covering the whole video
  when ContentDetector finds zero scene transitions (avoids empty list
  panics downstream).
- threshold=27.0 is calibrated for live-action content (movies/TV);
  animation typically needs 30+. Exposed as a kwarg for M4 style presets.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from loguru import logger

# Default tuning — see ADR-003 + M1.7 plan.
DEFAULT_THRESHOLD = 27.0
DEFAULT_MIN_SCENE_LEN_SEC = 0.8

# Default fps used when scenedetect cannot read fps from the source file
# (some edge containers report 0 fps until the first frame is decoded).
# 25.0 matches our normalize_low.mp4 output fps from M1.6, so the fallback
# round-trips correctly for files produced by our own ingest stage.
FALLBACK_FPS = 25.0


# ---------------------------------------------------------------------------
# Shot dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Shot:
    """A continuous shot detected by PySceneDetect.

    Field schema matches `autoclip.models.shot.Shot` ORM (sans `id` and
    `video_id`, which are DB-layer concerns) so the Index stage handler
    can persist results without a conversion layer.

    Note:
        Same naming pattern as `ASRSentence` (dataclass in providers layer
        + ORM in models layer). Import path disambiguates which one is meant.
    """

    idx: int
    start_sec: float
    end_sec: float

    def __post_init__(self) -> None:
        if self.idx < 0:
            raise ValueError(f"idx must be non-negative, got {self.idx}")
        if self.start_sec < 0:
            raise ValueError(f"start_sec must be non-negative, got {self.start_sec}")
        if self.end_sec <= self.start_sec:
            raise ValueError(
                f"end_sec ({self.end_sec}) must be > start_sec ({self.start_sec})"
            )

    @property
    def duration_sec(self) -> float:
        return self.end_sec - self.start_sec

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ShotDetectionError(RuntimeError):
    """Raised when shot detection cannot complete (file missing, decode error, etc)."""


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def detect_shots(
    video_path: Path,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    min_scene_len_sec: float = DEFAULT_MIN_SCENE_LEN_SEC,
) -> list[Shot]:
    """Detect shot boundaries in a video using PySceneDetect ContentDetector.

    Args:
        video_path: Path to the (normalized_low.mp4) source video.
        threshold: ContentDetector sensitivity. 27.0 = live-action default;
                   higher = fewer cuts (more conservative); 30+ for animation.
        min_scene_len_sec: Minimum scene length in seconds; cuts closer than
                           this are merged. Default 0.8s per design.md §16.3.

    Returns:
        List of Shot ordered by `start_sec` ascending. Always non-empty:
        if ContentDetector finds zero scene boundaries, returns a single
        Shot covering the entire video.

    Raises:
        FileNotFoundError: if `video_path` does not exist.
        ShotDetectionError: on unrecoverable PySceneDetect failure.
    """
    if not video_path.exists():
        raise FileNotFoundError(f"video file not found: {video_path}")

    # Lazy import: scenedetect pulls in cv2/av which are heavy to load.
    # Module-level import would slow down ALL pipeline imports even when
    # ingest/scripting/render don't need shot detection.
    try:
        from scenedetect import ContentDetector, SceneManager, open_video
    except ImportError as exc:
        raise ShotDetectionError(
            "scenedetect not installed; run `poetry install`"
        ) from exc

    logger.info(
        "[shot_detector] start path={} threshold={} min_scene_len_sec={}",
        video_path.name,
        threshold,
        min_scene_len_sec,
    )

    try:
        video = open_video(str(video_path))
    except Exception as exc:  # scenedetect raises VideoOpenFailure (subclass of Exception)
        raise ShotDetectionError(
            f"failed to open video {video_path}: {exc}"
        ) from exc

    # Resolve fps for min_scene_len conversion (frames). Some containers report
    # 0 fps until first frame is decoded; fall back to a sane default.
    fps = float(getattr(video, "frame_rate", 0.0)) or FALLBACK_FPS
    min_scene_len_frames = max(1, int(round(min_scene_len_sec * fps)))

    scene_manager = SceneManager()
    scene_manager.add_detector(
        ContentDetector(threshold=threshold, min_scene_len=min_scene_len_frames)
    )

    try:
        scene_manager.detect_scenes(video=video, show_progress=False)
    except Exception as exc:
        raise ShotDetectionError(
            f"detect_scenes failed for {video_path}: {exc}"
        ) from exc

    scene_list = scene_manager.get_scene_list()

    # Fallback: zero scene boundaries → single shot covering the whole video.
    if not scene_list:
        # `video.duration` is a FrameTimecode; .get_seconds() returns float.
        duration_sec = float(video.duration.get_seconds())
        if duration_sec <= 0:
            raise ShotDetectionError(
                f"video {video_path} has zero/unknown duration; cannot fallback"
            )
        logger.warning(
            "[shot_detector] zero scenes detected; emitting single-shot fallback "
            "[0, {:.2f}]s",
            duration_sec,
        )
        return [Shot(idx=0, start_sec=0.0, end_sec=duration_sec)]

    shots = [
        Shot(
            idx=i,
            start_sec=float(start.get_seconds()),
            end_sec=float(end.get_seconds()),
        )
        for i, (start, end) in enumerate(scene_list)
    ]
    logger.info(
        "[shot_detector] DONE n_shots={} first=[{:.2f},{:.2f}]s last=[{:.2f},{:.2f}]s",
        len(shots),
        shots[0].start_sec,
        shots[0].end_sec,
        shots[-1].start_sec,
        shots[-1].end_sec,
    )
    return shots
