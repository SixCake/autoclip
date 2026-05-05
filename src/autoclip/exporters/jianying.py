"""JianyingDraftExporter — Jianying draft package exporter.

Uses pyJianYingDraft if available; falls back to a structured zip mimicking
Jianying draft format when the library is not installed (R1 risk mitigation).

K10: all material paths use placeholder './materials/source.mp4'.
"""

from __future__ import annotations

import json
import logging
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from .base import DraftExporter, ExportResult

logger = logging.getLogger(__name__)


class JianyingExportError(Exception):
    """Raised when Jianying draft export fails."""


def _try_import_pyjianyingdraft() -> bool:
    """Check if pyjianyingdraft is available."""
    try:
        import pyjianyingdraft  # noqa: F401
        return True
    except ImportError:
        return False


def _build_draft_content(
    segments: list[dict],
    sentences: list[dict],
    video_id: str = "placeholder-video-material",
) -> dict:
    """Build draft_content.json structure (Jianying format approximation).

    K10: material id uses placeholder, not real path.
    """
    tracks = []
    video_cursor_us = 0  # microseconds

    # Track 1: main video
    video_segments = []
    for seg_idx, seg in enumerate(segments):
        source_start_us = int(seg.get("source_start_sec", 0.0) * 1_000_000)
        source_end_us = int(seg.get("source_end_sec", 0.0) * 1_000_000)
        duration_us = source_end_us - source_start_us

        video_segments.append({
            "id": f"video_seg_{seg_idx:04d}",
            "material_id": video_id,
            "source_timerange": {
                "start": source_start_us,
                "duration": duration_us,
            },
            "target_timerange": {
                "start": video_cursor_us,
                "duration": duration_us,
            },
            "type": "video",
        })
        video_cursor_us += duration_us

    tracks.append({"id": "main_video_track", "type": "video", "segments": video_segments})

    # Track 2: narration (TTS audio)
    narration_segments = []
    narration_cursor_us = 0

    for sent in sentences:
        duration_sec = sent.get("actual_duration_sec", 2.0)
        duration_us = int(duration_sec * 1_000_000)
        audio_path = sent.get("audio_path", "")

        narration_segments.append({
            "id": f"narration_seg_{sent['sentence_idx']:04d}",
            "material_id": audio_path,  # relative path within job dir
            "source_timerange": {"start": 0, "duration": duration_us},
            "target_timerange": {"start": narration_cursor_us, "duration": duration_us},
            "type": "audio",
            "volume": 1.0,
        })
        narration_cursor_us += duration_us

    tracks.append({"id": "narration_track", "type": "audio", "segments": narration_segments})

    # Track 3: original audio (30% volume during video segments)
    orig_audio_segments = []
    orig_cursor_us = 0
    for seg_idx, seg in enumerate(segments):
        source_start_us = int(seg.get("source_start_sec", 0.0) * 1_000_000)
        source_end_us = int(seg.get("source_end_sec", 0.0) * 1_000_000)
        duration_us = source_end_us - source_start_us

        orig_audio_segments.append({
            "id": f"orig_audio_seg_{seg_idx:04d}",
            "material_id": video_id,
            "source_timerange": {"start": source_start_us, "duration": duration_us},
            "target_timerange": {"start": orig_cursor_us, "duration": duration_us},
            "type": "audio",
            "volume": 0.3,
        })
        orig_cursor_us += duration_us

    tracks.append({"id": "original_audio_track", "type": "audio", "segments": orig_audio_segments})

    # Track 4: subtitles
    subtitle_segments = []
    subtitle_cursor_us = 0
    for sent in sentences:
        duration_sec = sent.get("actual_duration_sec", 2.0)
        duration_us = int(duration_sec * 1_000_000)

        subtitle_segments.append({
            "id": f"subtitle_seg_{sent['sentence_idx']:04d}",
            "text": sent.get("text", ""),
            "target_timerange": {"start": subtitle_cursor_us, "duration": duration_us},
            "type": "text",
        })
        subtitle_cursor_us += duration_us

    tracks.append({"id": "subtitle_track", "type": "text", "segments": subtitle_segments})

    return {
        "version": "5.9.0",
        "tracks": tracks,
        "materials": {
            "videos": [{"id": video_id, "path": "./materials/source.mp4"}],
        },
    }


def _build_draft_meta(job_dir: Path) -> dict:
    """Build draft_meta_info.json."""
    return {
        "version": "5.9.0",
        "draft_id": job_dir.name,
        "created_at": datetime.now(UTC).isoformat(),
        "generator": "autoclip",
    }


class JianyingDraftExporter(DraftExporter):
    """Jianying draft package exporter.

    Attempts to use pyjianyingdraft if installed; falls back to a hand-crafted
    zip with the same 4-track structure when the library is unavailable.
    """

    @property
    def name(self) -> str:
        return "jianying"

    def export(
        self,
        timeline: dict,
        assembly: dict,
        job_dir: Path,
        output_dir: Path,
    ) -> ExportResult:
        output_dir.mkdir(parents=True, exist_ok=True)

        segments = timeline.get("segments", [])
        sentences = assembly.get("sentences", [])

        if not segments:
            raise JianyingExportError("No segments in timeline.json — cannot build Jianying draft")

        has_pyjianyingdraft = _try_import_pyjianyingdraft()
        if has_pyjianyingdraft:
            logger.info("[jianying] pyjianyingdraft available — using library export")
            return self._export_with_library(segments, sentences, job_dir, output_dir)
        else:
            logger.warning("[jianying] pyjianyingdraft not installed — using fallback zip export")
            return self._export_fallback_zip(segments, sentences, job_dir, output_dir)

    def _export_with_library(
        self,
        segments: list[dict],
        sentences: list[dict],
        job_dir: Path,
        output_dir: Path,
    ) -> ExportResult:
        """Export using pyJianYingDraft library."""
        try:
            import pyjianyingdraft as pjy

            draft = pjy.Script_file(1080, 1920)
            for seg in segments:
                source_start = int(seg.get("source_start_sec", 0.0) * 1_000_000)
                source_end = int(seg.get("source_end_sec", 0.0) * 1_000_000)
                draft.add_segment(
                    pjy.Segment(
                        material_id=self.PLACEHOLDER_SOURCE_PATH,
                        source_timerange=pjy.tim(source_start, source_end - source_start),
                    )
                )

            zip_path = output_dir / "jianying_draft.zip"
            draft.dumps(str(zip_path))

            return ExportResult(
                output_path=zip_path,
                exporter_name=self.name,
                track_counts={"main_video": len(segments)},
            )
        except Exception as exc:
            raise JianyingExportError(f"pyjianyingdraft export failed: {exc}") from exc

    def _export_fallback_zip(
        self,
        segments: list[dict],
        sentences: list[dict],
        job_dir: Path,
        output_dir: Path,
    ) -> ExportResult:
        """Export as structured zip without pyjianyingdraft."""
        draft_content = _build_draft_content(segments, sentences)
        draft_meta = _build_draft_meta(job_dir)

        zip_path = output_dir / "jianying_draft.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "draft_content.json",
                json.dumps(draft_content, ensure_ascii=False, indent=2),
            )
            zf.writestr(
                "draft_meta_info.json",
                json.dumps(draft_meta, ensure_ascii=False, indent=2),
            )
            zf.writestr("materials/README.txt", self._make_readme())

        track_counts = {t["id"]: len(t["segments"]) for t in draft_content["tracks"]}
        logger.info("[jianying] fallback zip written: %s (%d tracks)", zip_path, len(draft_content["tracks"]))

        return ExportResult(
            output_path=zip_path,
            exporter_name=self.name,
            track_counts=track_counts,
        )
