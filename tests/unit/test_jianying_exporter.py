"""Unit tests for JianyingDraftExporter (M3.4)."""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

import pytest

from autoclip.exporters.jianying import JianyingDraftExporter, _build_draft_content


_SAMPLE_SEGMENTS = [
    {"source_start_sec": 0.0, "source_end_sec": 5.0},
    {"source_start_sec": 10.0, "source_end_sec": 20.0},
]

_SAMPLE_SENTENCES = [
    {"sentence_idx": 1, "text": "第一句", "actual_duration_sec": 3.0, "audio_path": "tts/t1.wav"},
    {"sentence_idx": 2, "text": "第二句", "actual_duration_sec": 2.5, "audio_path": "tts/t2.wav"},
]

_SAMPLE_TIMELINE = {"segments": _SAMPLE_SEGMENTS}
_SAMPLE_ASSEMBLY = {"sentences": _SAMPLE_SENTENCES}


class TestBuildDraftContent:
    def test_four_tracks_in_draft(self) -> None:
        content = _build_draft_content(_SAMPLE_SEGMENTS, _SAMPLE_SENTENCES)
        track_ids = [t["id"] for t in content["tracks"]]
        assert "main_video_track" in track_ids
        assert "narration_track" in track_ids
        assert "original_audio_track" in track_ids
        assert "subtitle_track" in track_ids

    def test_k10_placeholder_video_path(self) -> None:
        """K10: video material must use placeholder path, not absolute."""
        content = _build_draft_content(_SAMPLE_SEGMENTS, _SAMPLE_SENTENCES)
        video_material = content["materials"]["videos"][0]
        assert video_material["path"] == "./materials/source.mp4"
        # Must NOT contain absolute path
        assert not video_material["path"].startswith("/")

    def test_version_field_present(self) -> None:
        content = _build_draft_content(_SAMPLE_SEGMENTS, _SAMPLE_SENTENCES)
        assert "version" in content
        assert content["version"] == "5.9.0"

    def test_segment_count_matches_input(self) -> None:
        content = _build_draft_content(_SAMPLE_SEGMENTS, _SAMPLE_SENTENCES)
        video_track = next(t for t in content["tracks"] if t["id"] == "main_video_track")
        assert len(video_track["segments"]) == len(_SAMPLE_SEGMENTS)


class TestJianyingDraftExporter:
    def test_export_creates_zip(self, tmp_path: Path) -> None:
        exporter = JianyingDraftExporter()
        result = exporter.export(_SAMPLE_TIMELINE, _SAMPLE_ASSEMBLY, tmp_path, tmp_path / "output")
        assert result.output_path.exists()
        assert result.output_path.suffix == ".zip"

    def test_zip_contains_draft_content_json(self, tmp_path: Path) -> None:
        exporter = JianyingDraftExporter()
        result = exporter.export(_SAMPLE_TIMELINE, _SAMPLE_ASSEMBLY, tmp_path, tmp_path / "output")
        with zipfile.ZipFile(result.output_path) as zf:
            names = zf.namelist()
        assert "draft_content.json" in names
        assert "draft_meta_info.json" in names

    def test_k10_no_absolute_paths_in_zip(self, tmp_path: Path) -> None:
        """K10: verify no absolute paths leak into draft JSON."""
        exporter = JianyingDraftExporter()
        result = exporter.export(_SAMPLE_TIMELINE, _SAMPLE_ASSEMBLY, tmp_path, tmp_path / "output")
        abs_path_pattern = re.compile(r'["\'](?:/|[A-Z]:)[^"\']+["\']', re.IGNORECASE)
        with zipfile.ZipFile(result.output_path) as zf:
            draft_content = zf.read("draft_content.json").decode("utf-8")
        assert not abs_path_pattern.search(draft_content), "Absolute path found in draft_content.json!"

    def test_exporter_name(self) -> None:
        exporter = JianyingDraftExporter()
        assert exporter.name == "jianying"

    def test_empty_segments_raises(self, tmp_path: Path) -> None:
        from autoclip.exporters.jianying import JianyingExportError
        exporter = JianyingDraftExporter()
        with pytest.raises(JianyingExportError):
            exporter.export({"segments": []}, _SAMPLE_ASSEMBLY, tmp_path, tmp_path / "output")
