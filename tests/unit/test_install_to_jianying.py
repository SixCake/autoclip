"""Unit tests for install_to_jianying_drafts (Session 35 rewrite).

Covers the INSTALL branch: build a real pyJianYingDraft draft directly inside
the user's drafts root (overridden via `drafts_root` arg in tests) and copy
media alongside.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from autoclip.exporters.jianying import (
    JianyingDraftsDirNotFound,
    JianyingExportError,
    discover_jianying_drafts_dir,
    install_to_jianying_drafts,
)

_FFMPEG = shutil.which("ffmpeg")
pytestmark = pytest.mark.skipif(_FFMPEG is None, reason="ffmpeg not installed")


# ---------------------------------------------------------------------------
# Real-media fixtures (shared shape with test_jianying_exporter.py)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def tiny_media_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("install_fixture")
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
        wav = tts_dir / f"tts_{idx:04d}.wav"
        subprocess.run(
            [
                _FFMPEG, "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", f"sine=frequency={440 + idx * 110}:duration=0.5",
                "-ar", "16000", "-ac", "1",
                str(wav),
            ],
            check=True,
        )
    return root


@pytest.fixture
def job_dir(tmp_path: Path, tiny_media_root: Path) -> Path:
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
# install_to_jianying_drafts()
# ---------------------------------------------------------------------------

class TestInstallToJianyingDrafts:
    def test_creates_draft_in_provided_drafts_root(
        self, job_dir: Path, tmp_path: Path
    ) -> None:
        drafts_root = tmp_path / "Jianying_Drafts"
        drafts_root.mkdir()
        result = install_to_jianying_drafts(
            _TIMELINE, _ASSEMBLY, job_dir,
            job_id=42, drafts_root=drafts_root,
        )

        draft_dir = Path(result["draft_dir"])
        assert draft_dir.exists()
        assert draft_dir.parent == drafts_root
        assert draft_dir.name.startswith("autoclip_42_")
        assert (draft_dir / "draft_content.json").exists()
        assert (draft_dir / "draft_meta_info.json").exists()
        assert (draft_dir / "source.mp4").exists()
        assert (draft_dir / "tts_0000.wav").exists()
        assert (draft_dir / "tts_0001.wav").exists()

    def test_returns_expected_metadata(self, job_dir: Path, tmp_path: Path) -> None:
        drafts_root = tmp_path / "Jianying_Drafts"
        drafts_root.mkdir()
        result = install_to_jianying_drafts(
            _TIMELINE, _ASSEMBLY, job_dir,
            job_id=7, drafts_root=drafts_root,
        )
        assert result["draft_name"].startswith("autoclip_7_")
        assert result["source_video_linked"] is True
        assert Path(result["source_video_path"]).exists()
        assert result["tts_files_copied"] == 2

    def test_draft_content_is_valid_json(self, job_dir: Path, tmp_path: Path) -> None:
        drafts_root = tmp_path / "Jianying_Drafts"
        drafts_root.mkdir()
        result = install_to_jianying_drafts(
            _TIMELINE, _ASSEMBLY, job_dir,
            job_id=1, drafts_root=drafts_root,
        )
        content = json.loads(
            (Path(result["draft_dir"]) / "draft_content.json").read_text(encoding="utf-8")
        )
        assert "tracks" in content
        assert "materials" in content

    def test_missing_source_video_keeps_install_alive(
        self, job_dir: Path, tmp_path: Path
    ) -> None:
        (job_dir / "source.mp4").unlink()
        drafts_root = tmp_path / "Jianying_Drafts"
        drafts_root.mkdir()
        result = install_to_jianying_drafts(
            _TIMELINE, _ASSEMBLY, job_dir,
            job_id=1, drafts_root=drafts_root,
        )
        assert result["source_video_linked"] is False
        assert result["source_video_path"] is None
        # narration still present, draft still landed
        assert (Path(result["draft_dir"]) / "draft_content.json").exists()
        assert result["tts_files_copied"] == 2

    def test_empty_timeline_raises(self, job_dir: Path, tmp_path: Path) -> None:
        drafts_root = tmp_path / "Jianying_Drafts"
        drafts_root.mkdir()
        with pytest.raises(JianyingExportError):
            install_to_jianying_drafts(
                {"segments": []}, _ASSEMBLY, job_dir,
                job_id=1, drafts_root=drafts_root,
            )

    def test_external_source_video_path_overrides_job_dir(
        self, job_dir: Path, tmp_path: Path, tiny_media_root: Path
    ) -> None:
        # Remove default source from job_dir; supply external one explicitly.
        (job_dir / "source.mp4").unlink()
        external = tmp_path / "elsewhere" / "my_movie.mp4"
        external.parent.mkdir()
        shutil.copy2(tiny_media_root / "source.mp4", external)

        drafts_root = tmp_path / "Jianying_Drafts"
        drafts_root.mkdir()
        result = install_to_jianying_drafts(
            _TIMELINE, _ASSEMBLY, job_dir,
            job_id=1, drafts_root=drafts_root,
            source_video_path=external,
        )
        assert result["source_video_linked"] is True


# ---------------------------------------------------------------------------
# discover_jianying_drafts_dir() — cheap, no fixtures needed
# ---------------------------------------------------------------------------

class TestDiscoverJianyingDraftsDir:
    def test_env_var_override_wins(self, tmp_path: Path) -> None:
        with patch.dict(os.environ, {"JIANYING_DRAFT_DIR": str(tmp_path)}):
            assert discover_jianying_drafts_dir() == tmp_path

    def test_env_var_pointing_at_missing_dir_raises(self, tmp_path: Path) -> None:
        bogus = tmp_path / "does_not_exist"
        with patch.dict(os.environ, {"JIANYING_DRAFT_DIR": str(bogus)}):
            with pytest.raises(JianyingDraftsDirNotFound):
                discover_jianying_drafts_dir()

    def test_no_candidates_raises(self, tmp_path: Path) -> None:
        # Clear env, point HOME at empty dir, scrub LOCALAPPDATA → no candidates.
        env = {k: v for k, v in os.environ.items() if k not in {"JIANYING_DRAFT_DIR", "LOCALAPPDATA"}}
        env["HOME"] = str(tmp_path)
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(JianyingDraftsDirNotFound):
                discover_jianying_drafts_dir()
