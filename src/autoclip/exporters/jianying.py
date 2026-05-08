"""JianyingDraftExporter — Jianying draft package exporter.

Powered by `pyJianYingDraft` (driven by community reverse-engineering of the
real Jianying draft format). MVP scope: 2 core tracks — main video + narration.
Subtitles + lowered original audio are intentionally deferred to user editing
inside Jianying.

K10 双轨制 (Session 33):
- Download branch  (`JianyingDraftExporter.export`): build draft in a temp dir,
  copy source.mp4 + tts/*.wav alongside, then zip it. The user can extract the
  zip anywhere and "导入草稿" in Jianying — paths inside the draft point to
  the materials sitting next to draft_content.json.
- Install branch  (`install_to_jianying_drafts`): build draft directly inside
  the user's local Jianying drafts folder, copy materials next to it. Jianying
  picks it up from its scan; user just opens it.

In both branches the draft references **local files next to draft_content.json**
(not absolute paths anywhere else), so the resulting draft is portable and the
user never sees a "media offline" prompt.
"""

from __future__ import annotations

import logging
import os
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pyJianYingDraft as jy

from .base import DraftExporter, ExportResult

logger = logging.getLogger(__name__)


class JianyingExportError(Exception):
    """Raised when Jianying draft export fails."""


# ---------------------------------------------------------------------------
# Build helpers — talk to pyJianYingDraft only
# ---------------------------------------------------------------------------

# Default canvas (1080p horizontal). Could be derived from source.mp4 metadata
# in a future iteration; MVP keeps it fixed.
_CANVAS_WIDTH = 1920
_CANVAS_HEIGHT = 1080
_CANVAS_FPS = 30


# Fallback chain when caller doesn't pin a specific source_video_path:
# real ingest produces normalized_hd.mp4 (and a low-res variant for ASR);
# source.mp4 is only present in test fixtures / before the normalize step.
_VIDEO_SOURCE_FALLBACK = ("source.mp4", "normalized_hd.mp4", "normalized_low.mp4")


def _resolve_video_source(job_dir: Path) -> Path | None:
    """Pick the first existing video file from the fallback chain.

    Real jobs (post-ingest) only have normalized_*.mp4; cleanup/upload tests
    may have a raw source.mp4. Returning None means we'll skip the video
    track entirely so Jianying still opens the draft cleanly.
    """
    for name in _VIDEO_SOURCE_FALLBACK:
        candidate = job_dir / name
        if candidate.exists():
            return candidate
    return None


def _materialize_assets(
    job_dir: Path,
    sentences: list[dict],
    draft_dir: Path,
    *,
    source_video_path: Path | None = None,
) -> tuple[Path | None, dict[str, Path]]:
    """Copy main video + referenced tts wavs into draft_dir. Returns
    (copied_source_path or None, {audio_rel_path -> copied_abs_path}).

    Both branches do the same thing: keep all media physically next to
    draft_content.json so the draft is self-contained and portable.
    """
    draft_dir.mkdir(parents=True, exist_ok=True)

    # 1) main video — caller pin > job_dir fallback chain
    if source_video_path is None:
        source_video_path = _resolve_video_source(job_dir)
    copied_source: Path | None = None
    if source_video_path is not None and source_video_path.exists():
        # Preserve original filename so users see "normalized_hd.mp4" in Jianying
        # rather than a confusing renamed "source.mp4".
        dst = draft_dir / source_video_path.name
        if not dst.exists():
            shutil.copy2(source_video_path, dst)
        copied_source = dst
        logger.info("[jianying] main video resolved: %s", source_video_path)
    else:
        logger.warning(
            "[jianying] no main video found in %s (tried %s) — draft will have no "
            "main video; user must add it manually in Jianying",
            job_dir, _VIDEO_SOURCE_FALLBACK,
        )

    # 2) tts wavs (de-duped on filename)
    tts_map: dict[str, Path] = {}
    for sent in sentences:
        rel = sent.get("audio_path", "")
        if not rel or rel in tts_map:
            continue
        src = job_dir / rel
        if not src.exists():
            logger.warning("[jianying] missing TTS wav: %s — skipping sentence", src)
            continue
        dst = draft_dir / src.name
        if not dst.exists():
            shutil.copy2(src, dst)
        tts_map[rel] = dst

    return copied_source, tts_map


def _populate_script(
    script: jy.ScriptFile,
    segments: list[dict],
    sentences: list[dict],
    video_path: Path | None,
    tts_map: dict[str, Path],
    *,
    materials_use_basename: bool = False,
) -> jy.ScriptFile:
    """Add tracks + segments to an already-created ScriptFile, in place.

    Caller is responsible for creating the ScriptFile (typically via
    `DraftFolder.create_draft()` so the draft folder gets the official
    Jianying-compatible draft_meta_info.json template — hand-rolling that
    meta breaks Jianying's "草稿损坏" validator).

    MVP layout:
      - main video track: each timeline segment cuts [source_start..source_end]
        from `video_path` and lays it on the main track, head to tail.
      - narration track:  each sentence's tts wav, head to tail (cursor uses
        actual_duration_sec from assembly).

    `video_path` may be None when source.mp4 is unavailable; in that case the
    video track is omitted so Jianying still opens the draft cleanly.

    `materials_use_basename`: portability switch for the K10 双轨制.
      - False (default, INSTALL branch): keep absolute paths to media that
        sit next to draft_content.json in the user's Jianying drafts folder;
        Jianying never moves these files so absolute paths are stable.
      - True (DOWNLOAD branch): strip path to filename only. The zip ships
        media alongside draft_content.json, so when the user extracts it
        anywhere on disk Jianying resolves materials by sibling lookup.
    """
    if not segments:
        raise JianyingExportError("No segments in timeline — cannot build draft")

    # ----- Main video track -----
    if video_path is not None:
        video_material = jy.VideoMaterial(str(video_path))
        material_duration_us = int(video_material.duration)
        script.add_track(jy.TrackType.video)
        cursor_us = 0
        for seg in segments:
            source_start_us = int(seg.get("source_start_sec", 0.0) * 1_000_000)
            source_end_us = int(seg.get("source_end_sec", 0.0) * 1_000_000)
            # Clamp to material duration: timeline durations are computed at plan
            # time from ASR/normalize estimates and can drift a few ms past the
            # real file length. Without clamp, pyJianYingDraft raises
            # "截取的素材时间范围超出了素材时长" and aborts the whole export.
            source_start_us = max(0, min(source_start_us, material_duration_us))
            source_end_us = max(source_start_us, min(source_end_us, material_duration_us))
            duration_us = source_end_us - source_start_us
            if duration_us == 0:
                continue
            script.add_segment(
                jy.VideoSegment(
                    video_material,
                    target_timerange=jy.Timerange(cursor_us, duration_us),
                    source_timerange=jy.Timerange(source_start_us, duration_us),
                )
            )
            cursor_us += duration_us

    # ----- Narration track -----
    if sentences:
        script.add_track(jy.TrackType.audio, "narration")
        narration_cursor_us = 0
        for sent in sentences:
            rel = sent.get("audio_path", "")
            wav_path = tts_map.get(rel)
            if wav_path is None:
                continue  # already warned in _materialize_assets
            duration_us = int(float(sent.get("actual_duration_sec", 0.0)) * 1_000_000)
            if duration_us <= 0:
                continue
            audio_material = jy.AudioMaterial(str(wav_path))
            script.add_segment(
                jy.AudioSegment(
                    audio_material,
                    target_timerange=jy.Timerange(narration_cursor_us, duration_us),
                ),
                track_name="narration",
            )
            narration_cursor_us += duration_us

    # K10 portability rewrite — DOWNLOAD branch only. Jianying resolves
    # bare-filename material paths against draft_content.json's directory.
    if materials_use_basename:
        for video_mat in script.materials.videos:
            video_mat.path = Path(video_mat.path).name
        for audio_mat in script.materials.audios:
            audio_mat.path = Path(audio_mat.path).name

    return script


class JianyingDraftExporter(DraftExporter):
    """Jianying draft exporter — DOWNLOAD branch.

    Builds a real Jianying draft (via pyJianYingDraft) inside a temporary
    folder, copies source.mp4 + tts wavs alongside it, then zips the entire
    draft folder for the user to download. The zip is self-contained: extract
    anywhere → "导入草稿" in Jianying → opens cleanly.
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

        # Stage the draft inside output/_draft_staging so users can also grab the
        # un-zipped version if they wish; the canonical deliverable is the zip.
        staging_root = output_dir / "_draft_staging"
        if staging_root.exists():
            shutil.rmtree(staging_root)
        staging_root.mkdir(parents=True)
        draft_name = f"autoclip_{job_dir.name}"

        # 1) Use DraftFolder so pyJianYingDraft copies the official Jianying
        #    draft_meta_info.json template (30+ fields). Hand-rolling the meta
        #    used to fail Jianying's validator with "草稿损坏".
        folder = jy.DraftFolder(str(staging_root))
        script = folder.create_draft(
            draft_name, _CANVAS_WIDTH, _CANVAS_HEIGHT, _CANVAS_FPS,
            maintrack_adsorb=True,
        )
        draft_dir = staging_root / draft_name

        # 2) Materialize media next to the draft (after create_draft so the
        #    folder exists and meta is already in place).
        copied_video, tts_map = _materialize_assets(job_dir, sentences, draft_dir)

        # 3) Populate the script with tracks/segments. DOWNLOAD branch uses
        #    basename so the zip stays portable — extract anywhere → Jianying
        #    resolves media via sibling lookup against draft_content.json.
        try:
            _populate_script(
                script, segments, sentences, copied_video, tts_map,
                materials_use_basename=True,
            )
        except Exception as exc:
            raise JianyingExportError(f"pyJianYingDraft build failed: {exc}") from exc

        script.save()

        # 4) Zip the entire draft folder
        zip_path = output_dir / "jianying_draft.zip"
        if zip_path.exists():
            zip_path.unlink()
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in draft_dir.rglob("*"):
                if path.is_file():
                    zf.write(path, arcname=str(path.relative_to(staging_root)))

        zip_size_kb = zip_path.stat().st_size / 1024
        logger.info(
            "[jianying] draft zip written: %s (video=%s, tts=%d files, %.1f KB)",
            zip_path, copied_video is not None, len(tts_map), zip_size_kb,
        )

        return ExportResult(
            output_path=zip_path,
            exporter_name=self.name,
            track_counts={
                "main_video": len(segments) if copied_video is not None else 0,
                "narration": len(tts_map),
            },
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

    # Per-install timestamped folder (avoids collision when user re-installs)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    draft_name = f"autoclip_{job_id}_{timestamp}"

    # 1) DraftFolder.create_draft creates the folder AND copies the official
    #    Jianying-compatible draft_meta_info.json template. Without this,
    #    Jianying's drafts list rejects our entry with "草稿损坏".
    folder = jy.DraftFolder(str(drafts_root))
    script = folder.create_draft(
        draft_name, _CANVAS_WIDTH, _CANVAS_HEIGHT, _CANVAS_FPS,
        maintrack_adsorb=True,
    )
    draft_dir = drafts_root / draft_name

    # 2) Copy source video + tts wavs next to draft_content.json
    copied_video, tts_map = _materialize_assets(
        job_dir, sentences, draft_dir, source_video_path=source_video_path,
    )

    # 3) Populate the script with tracks/segments. INSTALL branch keeps
    #    absolute paths — Jianying never moves these files so the paths
    #    stay valid forever.
    try:
        _populate_script(script, segments, sentences, copied_video, tts_map)
    except Exception as exc:
        # Roll back the half-built draft folder so the user doesn't see
        # a corrupt entry in Jianying's drafts list.
        shutil.rmtree(draft_dir, ignore_errors=True)
        raise JianyingExportError(f"pyJianYingDraft build failed: {exc}") from exc

    script.save()

    source_video_linked = copied_video is not None
    logger.info(
        "[jianying-install] draft created at %s (source_linked=%s, tts=%d)",
        draft_dir, source_video_linked, len(tts_map),
    )

    return {
        "draft_dir": str(draft_dir),
        "draft_name": draft_name,
        "source_video_linked": source_video_linked,
        "source_video_path": str(copied_video) if copied_video is not None else None,
        "tts_files_copied": len(tts_map),
    }
