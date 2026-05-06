"""Unit tests for install_to_jianying_drafts() (Session 33 — install branch).

Covers:
- discover_jianying_drafts_dir(): env override / default macOS / not-found
- install_to_jianying_drafts(): writes draft folder with absolute paths,
  copies TTS wavs, returns metadata dict
- _build_draft_content(): install mode paths differ from placeholder mode

Design references: K10 双轨制 — install branch writes ABSOLUTE paths into
the local Jianying drafts dir; download branch keeps placeholder paths.
"""

from __future__ import annotations

import json
import wave
from pathlib import Path

import pytest

from autoclip.exporters.jianying import (
    JianyingDraftsDirNotFound,
    JianyingExportError,
    _build_draft_content,
    discover_jianying_drafts_dir,
    install_to_jianying_drafts,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def fake_job_dir(tmp_path: Path) -> Path:
    """Create a minimal job dir with source.mp4 + tts/*.wav."""
    job_dir = tmp_path / "job_42"
    job_dir.mkdir()

    # Fake source.mp4 (just any non-empty file; install never reads contents)
    (job_dir / "source.mp4").write_bytes(b"\x00" * 1024)

    # Two TTS wav files (well-formed silent PCM so wave module can read them)
    tts_dir = job_dir / "tts"
    tts_dir.mkdir()
    for name in ("tts_0000.wav", "tts_0001.wav"):
        with wave.open(str(tts_dir / name), "w") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            w.writeframes(b"\x00\x00" * 1000)

    return job_dir


@pytest.fixture()
def sample_timeline() -> dict:
    return {
        "segments": [
            {"source_start_sec": 0.0, "source_end_sec": 5.0},
            {"source_start_sec": 10.0, "source_end_sec": 15.0},
        ]
    }


@pytest.fixture()
def sample_assembly() -> dict:
    return {
        "sentences": [
            {"sentence_idx": 0, "text": "第一句", "actual_duration_sec": 3.0,
             "audio_path": "tts/tts_0000.wav"},
            {"sentence_idx": 1, "text": "第二句", "actual_duration_sec": 2.5,
             "audio_path": "tts/tts_0001.wav"},
        ]
    }


# ---------------------------------------------------------------------------
# discover_jianying_drafts_dir
# ---------------------------------------------------------------------------

class TestDiscoverDraftsDir:
    def test_env_override_wins_when_dir_exists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        custom_dir = tmp_path / "my_drafts"
        custom_dir.mkdir()
        monkeypatch.setenv("JIANYING_DRAFT_DIR", str(custom_dir))
        result = discover_jianying_drafts_dir()
        assert result == custom_dir

    def test_env_override_invalid_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("JIANYING_DRAFT_DIR", str(tmp_path / "does_not_exist"))
        with pytest.raises(JianyingDraftsDirNotFound, match="not an existing directory"):
            discover_jianying_drafts_dir()

    def test_no_env_no_default_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Force HOME to an empty tmp_path so default macOS path won't exist
        monkeypatch.delenv("JIANYING_DRAFT_DIR", raising=False)
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        with pytest.raises(JianyingDraftsDirNotFound, match="not found"):
            discover_jianying_drafts_dir()


# ---------------------------------------------------------------------------
# _build_draft_content — install mode vs placeholder mode
# ---------------------------------------------------------------------------

class TestBuildDraftContentInstallMode:
    def test_placeholder_mode_keeps_relative_paths(
        self, sample_timeline: dict, sample_assembly: dict
    ) -> None:
        content = _build_draft_content(
            sample_timeline["segments"], sample_assembly["sentences"]
        )
        assert content["materials"]["videos"][0]["path"] == "./materials/source.mp4"
        narration_seg = content["tracks"][1]["segments"][0]
        assert narration_seg["material_id"] == "tts/tts_0000.wav"

    def test_install_mode_writes_absolute_paths(
        self, sample_timeline: dict, sample_assembly: dict
    ) -> None:
        content = _build_draft_content(
            sample_timeline["segments"],
            sample_assembly["sentences"],
            video_source_path="/abs/path/to/source.mp4",
            narration_path_mode="absolute_in_dir",
            narration_dir_abs=Path("/abs/draft/dir"),
        )
        assert content["materials"]["videos"][0]["path"] == "/abs/path/to/source.mp4"
        narration_seg = content["tracks"][1]["segments"][0]
        # narration material_id = draft_dir + basename
        assert narration_seg["material_id"] == "/abs/draft/dir/tts_0000.wav"
        # second sentence too
        assert content["tracks"][1]["segments"][1]["material_id"] == "/abs/draft/dir/tts_0001.wav"


# ---------------------------------------------------------------------------
# install_to_jianying_drafts — happy path + edge cases
# ---------------------------------------------------------------------------

class TestInstallToJianyingDrafts:
    def test_creates_per_job_subfolder_with_expected_files(
        self,
        tmp_path: Path,
        fake_job_dir: Path,
        sample_timeline: dict,
        sample_assembly: dict,
    ) -> None:
        drafts_root = tmp_path / "drafts"
        drafts_root.mkdir()
        result = install_to_jianying_drafts(
            timeline=sample_timeline,
            assembly=sample_assembly,
            job_dir=fake_job_dir,
            job_id=42,
            drafts_root=drafts_root,
        )
        # Returned metadata
        assert result["draft_name"].startswith("autoclip_42_")
        assert result["source_video_linked"] is True
        assert result["tts_files_copied"] == 2

        # Folder layout
        draft_dir = Path(result["draft_dir"])
        assert draft_dir.exists()
        assert (draft_dir / "draft_content.json").exists()
        assert (draft_dir / "draft_meta_info.json").exists()
        assert (draft_dir / "tts_0000.wav").exists()
        assert (draft_dir / "tts_0001.wav").exists()

    def test_draft_content_references_absolute_source_video(
        self,
        tmp_path: Path,
        fake_job_dir: Path,
        sample_timeline: dict,
        sample_assembly: dict,
    ) -> None:
        drafts_root = tmp_path / "drafts"
        drafts_root.mkdir()
        result = install_to_jianying_drafts(
            timeline=sample_timeline,
            assembly=sample_assembly,
            job_dir=fake_job_dir,
            job_id=42,
            drafts_root=drafts_root,
        )
        draft_dir = Path(result["draft_dir"])
        content = json.loads((draft_dir / "draft_content.json").read_text(encoding="utf-8"))

        # Video path = absolute path to fake source.mp4
        expected_source = str((fake_job_dir / "source.mp4").resolve())
        assert content["materials"]["videos"][0]["path"] == expected_source

        # Narration material_id = absolute path next to draft_content.json
        narration_seg = content["tracks"][1]["segments"][0]
        assert narration_seg["material_id"].startswith(str(draft_dir.resolve()))
        assert narration_seg["material_id"].endswith("tts_0000.wav")

    def test_missing_source_video_proceeds_with_warning_flag(
        self,
        tmp_path: Path,
        sample_timeline: dict,
        sample_assembly: dict,
    ) -> None:
        # Job dir without source.mp4 (only tts/)
        job_dir = tmp_path / "job_no_source"
        job_dir.mkdir()
        tts_dir = job_dir / "tts"
        tts_dir.mkdir()
        for name in ("tts_0000.wav", "tts_0001.wav"):
            with wave.open(str(tts_dir / name), "w") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
                w.writeframes(b"\x00\x00" * 100)

        drafts_root = tmp_path / "drafts"
        drafts_root.mkdir()
        result = install_to_jianying_drafts(
            timeline=sample_timeline,
            assembly=sample_assembly,
            job_dir=job_dir,
            job_id=99,
            drafts_root=drafts_root,
        )
        assert result["source_video_linked"] is False
        assert result["source_video_path"] is None
        # Install still proceeds
        assert Path(result["draft_dir"]).exists()

    def test_empty_segments_raises(
        self, tmp_path: Path, fake_job_dir: Path, sample_assembly: dict
    ) -> None:
        drafts_root = tmp_path / "drafts"
        drafts_root.mkdir()
        with pytest.raises(JianyingExportError, match="No segments"):
            install_to_jianying_drafts(
                timeline={"segments": []},
                assembly=sample_assembly,
                job_dir=fake_job_dir,
                job_id=42,
                drafts_root=drafts_root,
            )

    def test_missing_tts_file_skipped_not_fatal(
        self,
        tmp_path: Path,
        fake_job_dir: Path,
        sample_timeline: dict,
    ) -> None:
        # Reference a tts file that doesn't exist
        assembly = {"sentences": [
            {"sentence_idx": 0, "text": "存在", "actual_duration_sec": 3.0,
             "audio_path": "tts/tts_0000.wav"},
            {"sentence_idx": 1, "text": "缺失", "actual_duration_sec": 2.0,
             "audio_path": "tts/tts_missing.wav"},
        ]}
        drafts_root = tmp_path / "drafts"
        drafts_root.mkdir()
        result = install_to_jianying_drafts(
            timeline=sample_timeline,
            assembly=assembly,
            job_dir=fake_job_dir,
            job_id=42,
            drafts_root=drafts_root,
        )
        # Only one wav copied (missing one skipped, install continues)
        assert result["tts_files_copied"] == 1
        draft_dir = Path(result["draft_dir"])
        assert (draft_dir / "tts_0000.wav").exists()
        assert not (draft_dir / "tts_missing.wav").exists()
