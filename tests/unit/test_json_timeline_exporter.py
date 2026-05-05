"""Unit tests for JsonTimelineExporter (M3.6)."""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

import pytest

from autoclip.exporters.json_timeline import JsonTimelineExporter

_SAMPLE_TIMELINE = {
    "segments": [
        {"source_start_sec": 0.0, "source_end_sec": 5.0},
        {"source_start_sec": 10.0, "source_end_sec": 20.0},
    ],
    "narrative_ir": {"paragraphs": []},
}

_SAMPLE_ASSEMBLY = {
    "sentences": [
        {"sentence_idx": 1, "text": "第一句解说", "actual_duration_sec": 3.0, "audio_path": "tts/tts_0001.wav"},
        {"sentence_idx": 2, "text": "第二句解说", "actual_duration_sec": 4.0, "audio_path": "tts/tts_0002.wav"},
    ]
}


class TestJsonTimelineExporter:
    def test_export_creates_zip(self, tmp_path: Path) -> None:
        exporter = JsonTimelineExporter()
        result = exporter.export(_SAMPLE_TIMELINE, _SAMPLE_ASSEMBLY, tmp_path, tmp_path / "output")
        assert result.output_path.exists()
        assert result.output_path.suffix == ".zip"

    def test_zip_contains_required_files(self, tmp_path: Path) -> None:
        exporter = JsonTimelineExporter()
        result = exporter.export(_SAMPLE_TIMELINE, _SAMPLE_ASSEMBLY, tmp_path, tmp_path / "output")
        with zipfile.ZipFile(result.output_path) as zf:
            names = zf.namelist()
        assert "timeline.json" in names
        assert "README.txt" in names

    def test_k10_no_absolute_paths(self, tmp_path: Path) -> None:
        """K10: all source paths must be placeholders, not absolute."""
        exporter = JsonTimelineExporter()
        result = exporter.export(_SAMPLE_TIMELINE, _SAMPLE_ASSEMBLY, tmp_path, tmp_path / "output")
        with zipfile.ZipFile(result.output_path) as zf:
            content = zf.read("timeline.json").decode("utf-8")
        abs_path_pattern = re.compile(r'["\'](?:/|[A-Z]:)[^"\']+["\']', re.IGNORECASE)
        assert not abs_path_pattern.search(content), "Absolute path found in JSON!"

    def test_four_tracks_present(self, tmp_path: Path) -> None:
        exporter = JsonTimelineExporter()
        result = exporter.export(_SAMPLE_TIMELINE, _SAMPLE_ASSEMBLY, tmp_path, tmp_path / "output")
        with zipfile.ZipFile(result.output_path) as zf:
            data = json.loads(zf.read("timeline.json").decode("utf-8"))
        tracks = data["tracks"]
        assert "main_video" in tracks
        assert "narration" in tracks
        assert "original_audio" in tracks
        assert "subtitle" in tracks

    def test_original_audio_volume_is_030(self, tmp_path: Path) -> None:
        exporter = JsonTimelineExporter()
        result = exporter.export(_SAMPLE_TIMELINE, _SAMPLE_ASSEMBLY, tmp_path, tmp_path / "output")
        with zipfile.ZipFile(result.output_path) as zf:
            data = json.loads(zf.read("timeline.json").decode("utf-8"))
        for seg in data["tracks"]["original_audio"]:
            assert seg["volume"] == 0.3

    def test_exporter_name(self) -> None:
        exporter = JsonTimelineExporter()
        assert exporter.name == "json_timeline"
