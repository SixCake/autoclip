"""JsonTimelineExporter — defensive fallback exporter (R1 risk mitigation).

Exports a self-described JSON timeline zip that can be consumed by any tool.
K10: all source paths use placeholder './materials/source.mp4'.
"""

from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from .base import DraftExporter, ExportResult


class JsonTimelineExporter(DraftExporter):
    """Fallback exporter producing a structured JSON timeline zip."""

    @property
    def name(self) -> str:
        return "json_timeline"

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

        # Build 4 tracks
        main_video_track = []
        narration_track = []
        original_audio_track = []
        subtitle_track = []

        video_cursor = 0.0
        narration_cursor = 0.0

        for seg_idx, seg in enumerate(segments):
            source_start = seg.get("source_start_sec", 0.0)
            source_end = seg.get("source_end_sec", 0.0)
            duration = source_end - source_start

            # Main video track (K10: placeholder source path)
            main_video_track.append({
                "seg_id": f"v_{seg_idx:04d}",
                "source_path": self.PLACEHOLDER_SOURCE_PATH,
                "source_start": source_start,
                "source_end": source_end,
                "target_start": video_cursor,
                "target_end": video_cursor + duration,
            })

            # Original audio (30% volume during video segments)
            original_audio_track.append({
                "seg_id": f"a_orig_{seg_idx:04d}",
                "target_start": video_cursor,
                "target_end": video_cursor + duration,
                "volume": 0.3,
            })

            video_cursor += duration

        # Narration + subtitle tracks from assembly sentences
        for sent in sentences:
            sent_duration = sent.get("actual_duration_sec", 2.0)
            audio_rel_path = sent.get("audio_path", "")

            narration_track.append({
                "seg_id": f"n_{sent['sentence_idx']:04d}",
                "audio_path": audio_rel_path,
                "target_start": narration_cursor,
                "target_end": narration_cursor + sent_duration,
                "volume": 1.0,
            })

            subtitle_track.append({
                "seg_id": f"s_{sent['sentence_idx']:04d}",
                "text": sent.get("text", ""),
                "target_start": narration_cursor,
                "target_end": narration_cursor + sent_duration,
            })

            narration_cursor += sent_duration

        output_json = {
            "version": "1.0",
            "video_duration_sec": video_cursor,
            "tracks": {
                "main_video": main_video_track,
                "narration": narration_track,
                "original_audio": original_audio_track,
                "subtitle": subtitle_track,
            },
            "metadata": {
                "exporter": "json_timeline",
                "exporter_version": "1.0",
                "original_video_relative": self.PLACEHOLDER_SOURCE_PATH,
                "generated_at": datetime.now(UTC).isoformat(),
            },
        }

        # Pack into zip
        zip_path = output_dir / "json_timeline_draft.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("timeline.json", json.dumps(output_json, ensure_ascii=False, indent=2))
            zf.writestr("README.txt", self._make_readme())

        return ExportResult(
            output_path=zip_path,
            exporter_name=self.name,
            track_counts={
                "main_video": len(main_video_track),
                "narration": len(narration_track),
                "original_audio": len(original_audio_track),
                "subtitle": len(subtitle_track),
            },
        )
