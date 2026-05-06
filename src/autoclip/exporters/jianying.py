"""JianyingDraftExporter — Jianying draft package exporter.

Uses pyJianYingDraft if available; falls back to a structured zip mimicking
Jianying draft format when the library is not installed (R1 risk mitigation).

K10 双轨制 (Session 33):
- Download branch (export()): material paths = placeholder './materials/source.mp4'
  (zero-knowledge compliance, distributable to anyone)
- Install branch (install_to_jianying_drafts()): material path = absolute path
  to user's local source.mp4 (only written into the user's own Jianying draft
  directory on their own machine — never distributed; cleanup_after_render
  must skip source.mp4 when this branch is used).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
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
    *,
    video_source_path: str = "./materials/source.mp4",
    narration_path_mode: str = "relative",  # "relative" | "absolute_in_dir"
    narration_dir_abs: Path | None = None,
) -> dict:
    """Build draft_content.json structure (Jianying format approximation).

    Args:
        video_source_path: written into materials.videos[0].path. Default is the
            K10 placeholder; install branch passes the absolute local path to
            the user's source.mp4 so Jianying opens with media linked.
        narration_path_mode: "relative" keeps audio_path as-is (zip download
            branch where wav lives at materials/tts_*.wav inside the zip);
            "absolute_in_dir" rewrites narration material_id to
            f"{narration_dir_abs}/{basename}" (install branch where wavs are
            copied next to draft_content.json under the Jianying drafts folder).
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
        audio_path_rel = sent.get("audio_path", "")

        # Resolve narration material path per mode (K10 双轨制)
        if narration_path_mode == "absolute_in_dir" and narration_dir_abs is not None:
            narration_material_id = str(narration_dir_abs / Path(audio_path_rel).name)
        else:
            narration_material_id = audio_path_rel  # relative within zip / job dir

        narration_segments.append({
            "id": f"narration_seg_{sent['sentence_idx']:04d}",
            "material_id": narration_material_id,
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
            "videos": [{"id": video_id, "path": video_source_path}],
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
        """Export as structured zip without pyjianyingdraft.

        Packs:
          draft_content.json   — 4-track timeline structure
          draft_meta_info.json — version + generator info
          materials/           — TTS wav files + README
        """
        draft_content = _build_draft_content(segments, sentences)
        draft_meta = _build_draft_meta(job_dir)

        zip_path = output_dir / "jianying_draft.zip"
        packed_audio_paths: set[str] = set()

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

            # Pack TTS audio files referenced in narration track
            for sentence in sentences:
                audio_rel = sentence.get("audio_path", "")
                if not audio_rel or audio_rel in packed_audio_paths:
                    continue
                audio_abs = job_dir / audio_rel
                if audio_abs.exists():
                    zf.write(audio_abs, arcname=f"materials/{audio_abs.name}")
                    packed_audio_paths.add(audio_rel)
                    logger.debug("[jianying] packed TTS: materials/%s", audio_abs.name)
                else:
                    logger.warning("[jianying] TTS file missing, skipping: %s", audio_abs)

        track_counts = {t["id"]: len(t["segments"]) for t in draft_content["tracks"]}
        zip_size_kb = zip_path.stat().st_size / 1024
        logger.info(
            "[jianying] fallback zip written: %s (%d tracks, %d TTS files, %.1f KB)",
            zip_path, len(draft_content["tracks"]), len(packed_audio_paths), zip_size_kb,
        )

        return ExportResult(
            output_path=zip_path,
            exporter_name=self.name,
            track_counts=track_counts,
        )


# ---------------------------------------------------------------------------
# Install branch (Session 33) — write draft directly into Jianying drafts dir
# with absolute paths to local source.mp4 (K10 双轨制 — local-only, never
# distributed).
# ---------------------------------------------------------------------------

class JianyingDraftsDirNotFound(Exception):
    """Raised when the user's Jianying drafts folder cannot be located."""


def discover_jianying_drafts_dir() -> Path:
    """Locate the Jianying drafts root directory on the current machine.

    Resolution order:
      1. Env var JIANYING_DRAFT_DIR (user override)
      2. macOS default: ~/Movies/JianyingPro/User Data/Projects/com.lveditor.draft
      3. Windows default: %LOCALAPPDATA%/JianyingPro/User Data/Projects/com.lveditor.draft

    Raises:
        JianyingDraftsDirNotFound: when no candidate exists.
    """
    override = os.environ.get("JIANYING_DRAFT_DIR")
    if override:
        path = Path(override).expanduser()
        if path.is_dir():
            return path
        raise JianyingDraftsDirNotFound(
            f"JIANYING_DRAFT_DIR is set to '{override}' but is not an existing directory"
        )

    candidates: list[Path] = []
    home = Path.home()
    # macOS
    candidates.append(home / "Movies" / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft")
    # Windows
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(
            Path(local_appdata) / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft"
        )

    for candidate in candidates:
        if candidate.is_dir():
            return candidate

    raise JianyingDraftsDirNotFound(
        "Jianying drafts directory not found. Set the JIANYING_DRAFT_DIR env var "
        f"to your draft folder (Jianying → 全局设置 → 草稿位置). Tried: "
        f"{[str(c) for c in candidates]}"
    )


def install_to_jianying_drafts(
    timeline: dict,
    assembly: dict,
    job_dir: Path,
    *,
    job_id: int,
    drafts_root: Path | None = None,
    source_video_path: Path | None = None,
) -> dict:
    """Materialize a Jianying draft directly into the user's drafts folder.

    Writes:
        <drafts_root>/autoclip_<job_id>_<timestamp>/
            draft_content.json    — materials.videos[0].path = abs source_video_path
                                    narration material_id   = abs path next to draft
            draft_meta_info.json
            tts_*.wav             — copied from job_dir/tts/

    Args:
        job_id: numeric Job.id (used in draft folder name)
        drafts_root: override discovery (mainly for tests)
        source_video_path: absolute path to user's source.mp4. If None, falls
            back to job_dir/source.mp4. If that file is missing, the install
            still proceeds but the user will see "media offline" in Jianying
            and must relink manually.

    Returns:
        {
            "draft_dir": str(absolute path),
            "draft_name": str,
            "source_video_linked": bool,    # whether source.mp4 was found
            "source_video_path": str | None,
            "tts_files_copied": int,
        }
    """
    if drafts_root is None:
        drafts_root = discover_jianying_drafts_dir()
    drafts_root.mkdir(parents=True, exist_ok=True)

    segments = timeline.get("segments", [])
    sentences = assembly.get("sentences", [])
    if not segments:
        raise JianyingExportError("No segments in timeline — cannot install draft")

    # Resolve source video absolute path
    if source_video_path is None:
        source_video_path = job_dir / "source.mp4"
    source_video_linked = source_video_path.exists()
    video_source_str = str(source_video_path.resolve())
    if not source_video_linked:
        logger.warning(
            "[jianying-install] source video not found at %s — draft will open with "
            "missing media (user must relink in Jianying)",
            source_video_path,
        )

    # Create per-job draft directory (timestamped to avoid collision on reinstall)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    draft_name = f"autoclip_{job_id}_{timestamp}"
    draft_dir = drafts_root / draft_name
    draft_dir.mkdir(parents=True, exist_ok=False)

    # Copy TTS wavs flat into draft_dir (Jianying scans subdir for media)
    tts_files_copied = 0
    for sent in sentences:
        audio_rel = sent.get("audio_path", "")
        if not audio_rel:
            continue
        src = job_dir / audio_rel
        if not src.exists():
            logger.warning("[jianying-install] missing TTS wav: %s", src)
            continue
        dst = draft_dir / src.name
        if not dst.exists():  # de-dup on shared filename
            shutil.copy2(src, dst)
            tts_files_copied += 1

    # Build draft_content with absolute paths (install branch)
    draft_content = _build_draft_content(
        segments,
        sentences,
        video_source_path=video_source_str,
        narration_path_mode="absolute_in_dir",
        narration_dir_abs=draft_dir.resolve(),
    )
    draft_meta = _build_draft_meta(draft_dir)

    (draft_dir / "draft_content.json").write_text(
        json.dumps(draft_content, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (draft_dir / "draft_meta_info.json").write_text(
        json.dumps(draft_meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    logger.info(
        "[jianying-install] draft created at %s (source_linked=%s, tts=%d)",
        draft_dir, source_video_linked, tts_files_copied,
    )

    return {
        "draft_dir": str(draft_dir),
        "draft_name": draft_name,
        "source_video_linked": source_video_linked,
        "source_video_path": video_source_str if source_video_linked else None,
        "tts_files_copied": tts_files_copied,
    }
