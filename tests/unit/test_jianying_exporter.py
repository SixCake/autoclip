"""Unit tests for JianyingDraftExporter (Session 35 rewrite).

Covers the DOWNLOAD branch: build a real pyJianYingDraft draft in a temp dir,
copy media alongside, and zip everything.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from autoclip.exporters.jianying import (
    JianyingDraftExporter,
    JianyingExportError,
)

# ---------------------------------------------------------------------------
# Real-media fixtures (ffmpeg-generated, tiny)
# ---------------------------------------------------------------------------

_FFMPEG = shutil.which("ffmpeg")
pytestmark = pytest.mark.skipif(_FFMPEG is None, reason="ffmpeg not installed")


@pytest.fixture(scope="module")
def tiny_media_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate a 1s mp4 + 2 short wavs once per module.

    pyJianYingDraft.VideoMaterial / AudioMaterial actually probe the files via
    pymediainfo, so we need real media — not empty placeholder bytes.
    """
    root = tmp_path_factory.mktemp("jianying_fixture")
    mp4_path = root / "source.mp4"
    subprocess.run(
        [
            _FFMPEG, "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=black:s=320x240:d=2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", "2",
            str(mp4_path),
        ],
        check=True,
    )
    tts_dir = root / "tts"
    tts_dir.mkdir()
    for idx in (0, 1):
        wav_path = tts_dir / f"tts_{idx:04d}.wav"
        subprocess.run(
            [
                _FFMPEG, "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", f"sine=frequency={440 + idx * 110}:duration=0.5",
                "-ar", "16000", "-ac", "1",
                str(wav_path),
            ],
            check=True,
        )
    return root


@pytest.fixture
def job_dir(tmp_path: Path, tiny_media_root: Path) -> Path:
    """Per-test job_dir with fresh copies of source.mp4 + tts/."""
    job = tmp_path / "job"
    job.mkdir()
    shutil.copy2(tiny_media_root / "source.mp4", job / "source.mp4")
    shutil.copytree(tiny_media_root / "tts", job / "tts")
    return job


_TIMELINE = {
    "segments": [
        {"source_start_sec": 0.0, "source_end_sec": 1.0},
        {"source_start_sec": 1.0, "source_end_sec": 2.0},
    ],
}

_ASSEMBLY = {
    "sentences": [
        {"sentence_idx": 0, "text": "第一句", "audio_path": "tts/tts_0000.wav", "actual_duration_sec": 0.5},
        {"sentence_idx": 1, "text": "第二句", "audio_path": "tts/tts_0001.wav", "actual_duration_sec": 0.5},
    ],
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestJianyingDraftExporter:
    def test_exporter_name(self) -> None:
        assert JianyingDraftExporter().name == "jianying"

    def test_export_produces_zip(self, job_dir: Path, tmp_path: Path) -> None:
        exporter = JianyingDraftExporter()
        result = exporter.export(_TIMELINE, _ASSEMBLY, job_dir, tmp_path / "out")
        assert result.output_path.exists()
        assert result.output_path.suffix == ".zip"
        assert result.exporter_name == "jianying"
        assert result.track_counts == {"main_video": 2, "narration": 2}

    def test_zip_contains_draft_and_media(self, job_dir: Path, tmp_path: Path) -> None:
        result = JianyingDraftExporter().export(_TIMELINE, _ASSEMBLY, job_dir, tmp_path / "out")
        with zipfile.ZipFile(result.output_path) as zf:
            names = zf.namelist()
        # All entries live under the autoclip_<jobname>/ folder
        draft_root = f"autoclip_{job_dir.name}/"
        assert any(n.startswith(draft_root) for n in names)
        assert f"{draft_root}draft_content.json" in names
        assert f"{draft_root}draft_meta_info.json" in names
        # source video keeps its original filename (J6: fallback chain)
        assert f"{draft_root}source.mp4" in names
        assert f"{draft_root}tts_0000.wav" in names
        assert f"{draft_root}tts_0001.wav" in names

    def test_video_source_fallback_to_normalized_hd(
        self, job_dir: Path, tmp_path: Path, tiny_media_root: Path
    ) -> None:
        """J6 fallback: when source.mp4 is missing, normalized_hd.mp4 wins.

        Real production jobs (post-ingest) only have normalized_*.mp4;
        the exporter must pick that up automatically.
        """
        (job_dir / "source.mp4").unlink()
        shutil.copy2(tiny_media_root / "source.mp4", job_dir / "normalized_hd.mp4")

        result = JianyingDraftExporter().export(_TIMELINE, _ASSEMBLY, job_dir, tmp_path / "out")
        assert result.track_counts["main_video"] == 2
        draft_root = f"autoclip_{job_dir.name}/"
        with zipfile.ZipFile(result.output_path) as zf:
            names = zf.namelist()
        assert f"{draft_root}normalized_hd.mp4" in names
        assert f"{draft_root}source.mp4" not in names

    def test_video_source_fallback_to_normalized_low(
        self, job_dir: Path, tmp_path: Path, tiny_media_root: Path
    ) -> None:
        """J6 fallback: source.mp4 + normalized_hd.mp4 both missing → low-res."""
        (job_dir / "source.mp4").unlink()
        shutil.copy2(tiny_media_root / "source.mp4", job_dir / "normalized_low.mp4")

        result = JianyingDraftExporter().export(_TIMELINE, _ASSEMBLY, job_dir, tmp_path / "out")
        assert result.track_counts["main_video"] == 2
        draft_root = f"autoclip_{job_dir.name}/"
        with zipfile.ZipFile(result.output_path) as zf:
            names = zf.namelist()
        assert f"{draft_root}normalized_low.mp4" in names

    def test_draft_content_is_valid_json(self, job_dir: Path, tmp_path: Path) -> None:
        result = JianyingDraftExporter().export(_TIMELINE, _ASSEMBLY, job_dir, tmp_path / "out")
        draft_root = f"autoclip_{job_dir.name}/"
        with zipfile.ZipFile(result.output_path) as zf:
            content = json.loads(zf.read(f"{draft_root}draft_content.json").decode("utf-8"))
        # pyJianYingDraft writes a Jianying-compatible structure with at least
        # tracks + materials at the top level.
        assert "tracks" in content
        assert "materials" in content

    def test_empty_timeline_raises(self, job_dir: Path, tmp_path: Path) -> None:
        with pytest.raises(JianyingExportError):
            JianyingDraftExporter().export(
                {"segments": []}, _ASSEMBLY, job_dir, tmp_path / "out",
            )

    def test_missing_source_video_still_succeeds(
        self, job_dir: Path, tmp_path: Path
    ) -> None:
        """If source.mp4 is missing, draft is built without the video track —
        Jianying still opens it cleanly; user adds video manually."""
        (job_dir / "source.mp4").unlink()
        result = JianyingDraftExporter().export(_TIMELINE, _ASSEMBLY, job_dir, tmp_path / "out")
        assert result.output_path.exists()
        assert result.track_counts["main_video"] == 0
        # narration still present
        assert result.track_counts["narration"] == 2
