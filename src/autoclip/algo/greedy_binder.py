"""Greedy binder for M2a baseline (M2a.5).

Implements the simplest possible binding from NarrativeIR sentences to source
shots: uniformly split each paragraph's [approx_source_start_sec,
approx_source_end_sec] window into N equal sub-windows (N = number of
sentences in the paragraph), then attach all shots overlapping each
sub-window.

This is the M2a baseline; M2b will replace ``bind_naively`` with an
evidence-based binder (BM25 over evidence_keywords). The data structures
``BoundSegment`` and ``BindingResult`` are stable across M2a/M2b — only the
``binding_method`` field differentiates the strategy.

Design notes (per docs/plans/tasks/M2a-scripting-main.md §M2a.5):
- Pure algorithm layer: no I/O, no ORM, no state.json.
- Reuses ``autoclip.models.timeline.BindingMethod`` (single source of truth
  for enum values across algo + ORM + JSON serialization).
- ``BindingResult.fallback_ratio`` is a property tied to KPI K3
  (target ≤ 0.3 in M2b.5 acceptance).
- M2a baseline always writes ``HINT_UNIFORM`` — fallback_count stays 0
  because there's no evidence-resolution attempt to fall back from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from autoclip.algo.narrative_ir import NarrativeIR
from autoclip.algo.shot_detector import Shot
from autoclip.models.timeline import BindingMethod

# Minimum duration (seconds) for a single bound segment. Below this,
# narration playback feels jarring (sub-second cuts). Per M2a.5 plan.
DEFAULT_MIN_SEGMENT_SEC = 0.8


@dataclass(frozen=True)
class BoundSegment:
    """One sentence bound to a source-time window + matching shot ids.

    Carries ONLY source-side info (source_start_sec / source_end_sec /
    source_shot_ids). Target-side timing (the final cut's timeline) is
    computed downstream by M2a.6 / M3.4 from sentence durations.
    """

    paragraph_idx: int
    sentence_idx: int
    sentence_text: str
    source_start_sec: float
    source_end_sec: float
    source_shot_ids: list[int] = field(default_factory=list)
    binding_method: BindingMethod = BindingMethod.HINT_UNIFORM

    @property
    def duration_sec(self) -> float:
        return self.source_end_sec - self.source_start_sec

    def to_dict(self) -> dict[str, Any]:
        return {
            "paragraph_idx": self.paragraph_idx,
            "sentence_idx": self.sentence_idx,
            "sentence_text": self.sentence_text,
            "source_start_sec": self.source_start_sec,
            "source_end_sec": self.source_end_sec,
            "source_shot_ids": list(self.source_shot_ids),
            "binding_method": self.binding_method.value,
        }


@dataclass(frozen=True)
class BindingResult:
    """Aggregate output of a binder run.

    fallback_count tracks how many segments had to fall back to a
    less-confident strategy. M2a baseline always = 0 (HINT_UNIFORM is the
    only strategy used). M2b will populate this for K3 monitoring.
    """

    segments: list[BoundSegment]
    fallback_count: int = 0

    @property
    def total_count(self) -> int:
        return len(self.segments)

    @property
    def fallback_ratio(self) -> float:
        """K3-related: fraction of segments using fallback strategy.

        Returns 0.0 for empty result (avoid division-by-zero; an empty
        binding has no fallback by definition).
        """
        if self.total_count == 0:
            return 0.0
        return self.fallback_count / self.total_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "segments": [s.to_dict() for s in self.segments],
            "fallback_count": self.fallback_count,
            "total_count": self.total_count,
            "fallback_ratio": self.fallback_ratio,
        }


def _video_end_sec(shots: list[Shot]) -> float:
    """Total video duration = end of last shot. Empty shots → 0.0."""
    if not shots:
        return 0.0
    return max(s.end_sec for s in shots)


def _clamp_window(
    start: float, end: float, video_end: float, min_segment_sec: float
) -> tuple[float, float]:
    """Clamp [start, end] into [0, video_end] and ensure non-negative width.

    If the clamped window collapses to zero width, expand symmetrically
    (within bounds) up to ``min_segment_sec``.
    """
    s = max(0.0, min(start, video_end))
    e = max(s, min(end, video_end))
    if e - s < min_segment_sec and video_end > 0:
        # Try to expand to at least min_segment_sec, staying in [0, video_end]
        target = min(min_segment_sec, video_end)
        deficit = target - (e - s)
        # Expand right first, then left
        right_room = video_end - e
        grow_right = min(deficit, right_room)
        e += grow_right
        deficit -= grow_right
        if deficit > 0:
            grow_left = min(deficit, s)
            s -= grow_left
    return s, e


def _shots_overlapping(
    seg_start: float, seg_end: float, shots: list[Shot]
) -> list[int]:
    """Return ids of shots whose [start_sec, end_sec] overlaps [seg_start, seg_end].

    Uses ``Shot.idx`` as the id (algo-layer Shot has ``idx`` not ``id``;
    matches the order_idx persisted by the Index stage).
    """
    return [
        s.idx
        for s in shots
        if s.start_sec < seg_end and s.end_sec > seg_start
    ]


def _nearest_shot_id(target_sec: float, shots: list[Shot]) -> int | None:
    """Find shot whose start_sec is closest to target_sec. None if shots empty.

    Used as the extreme fallback when a segment overlaps no shot at all
    (e.g. paragraph hint window falls entirely in a gap that all shots
    miss — shouldn't happen with PySceneDetect output but guards against it).
    """
    if not shots:
        return None
    nearest = min(shots, key=lambda s: abs(s.start_sec - target_sec))
    return nearest.idx


def bind_naively(
    ir: NarrativeIR,
    shots: list[Shot],
    min_segment_sec: float = DEFAULT_MIN_SEGMENT_SEC,
) -> BindingResult:
    """Bind each NarrativeIR sentence to a source-time window + matching shots.

    Algorithm (per M2a.5 plan §6 steps):
        1. Determine video_end_sec from shots.
        2. For each paragraph: clamp [approx_source_start_sec,
           approx_source_end_sec] into [0, video_end_sec].
        3. Uniformly split into N sub-windows (N = len(sentences)).
        4. Ensure each sub-window ≥ min_segment_sec (expand within parent
           paragraph bounds if possible).
        5. For each sub-window, collect overlapping shot ids.
        6. Extreme fallback: if no shot overlaps, attach the single nearest
           shot (by start_sec) to avoid empty source_shot_ids downstream.

    Args:
        ir: NarrativeIR from M2a.3.
        shots: List of Shot from M1.7 shot_detector output.
        min_segment_sec: Per-sentence minimum window duration.

    Returns:
        BindingResult with segments in (paragraph_idx, sentence_idx) order.
        fallback_count is always 0 in M2a baseline (HINT_UNIFORM has no
        fallback path); M2b will populate it.
    """
    if min_segment_sec <= 0:
        raise ValueError(
            f"min_segment_sec must be positive, got {min_segment_sec}"
        )

    video_end = _video_end_sec(shots)
    if video_end <= 0:
        logger.warning(
            "bind_naively: video has zero duration (no shots); returning empty result"
        )
        return BindingResult(segments=[], fallback_count=0)

    segments: list[BoundSegment] = []

    for para in ir.paragraphs:
        n = len(para.sentences)
        if n == 0:
            continue

        p_start, p_end = _clamp_window(
            para.approx_source_start_sec,
            para.approx_source_end_sec,
            video_end,
            min_segment_sec,
        )

        per = (p_end - p_start) / n

        for i, sent in enumerate(para.sentences):
            raw_start = p_start + i * per
            raw_end = p_start + (i + 1) * per if i < n - 1 else p_end

            # Per-sentence min duration enforcement (within parent paragraph)
            if raw_end - raw_start < min_segment_sec:
                # Expand within [p_start, p_end]
                deficit = min_segment_sec - (raw_end - raw_start)
                right_room = p_end - raw_end
                grow_right = min(deficit, right_room)
                raw_end += grow_right
                deficit -= grow_right
                if deficit > 0:
                    grow_left = min(deficit, raw_start - p_start)
                    raw_start -= grow_left

            shot_ids = _shots_overlapping(raw_start, raw_end, shots)
            if not shot_ids:
                # Extreme fallback: nearest shot by start_sec
                nearest = _nearest_shot_id(
                    (raw_start + raw_end) / 2, shots
                )
                if nearest is not None:
                    shot_ids = [nearest]
                    logger.warning(
                        "bind_naively: paragraph={} sentence={} window=[{:.2f},{:.2f}] "
                        "had no overlapping shot; falling back to nearest shot id={}",
                        para.paragraph_idx,
                        sent.sentence_idx,
                        raw_start,
                        raw_end,
                        nearest,
                    )

            segments.append(
                BoundSegment(
                    paragraph_idx=para.paragraph_idx,
                    sentence_idx=sent.sentence_idx,
                    sentence_text=sent.text,
                    source_start_sec=raw_start,
                    source_end_sec=raw_end,
                    source_shot_ids=shot_ids,
                    binding_method=BindingMethod.HINT_UNIFORM,
                )
            )

    # M2a baseline: fallback_count always 0 (HINT_UNIFORM has no
    # less-confident strategy to fall back from). M2b will populate.
    return BindingResult(segments=segments, fallback_count=0)
