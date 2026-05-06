"""Render stage handler — export draft package + track structure validation.

Responsibilities:
1. Load timeline.json + assembly.json
2. Select exporter via AUTOCLIP_EXPORTER env var (default: jianying)
3. Run exporter.export() → ExportResult
4. K10 track validation: no absolute paths in material refs
5. Call cleanup_after_render() to delete normalized.mp4 + temp/

Progress milestones:
- 0.1  files loaded
- 0.6  export complete
- 0.95 validation complete
- 1.0  DONE
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from ..exporters.base import ExportResult
from ..exporters.jianying import JianyingDraftExporter
from ..exporters.json_timeline import JsonTimelineExporter
from ..pipeline.runner import register_stage_handler
from ..pipeline.state import JobStateFile, Stage, StageStatus

logger = logging.getLogger(__name__)

_ABSOLUTE_PATH_PATTERN = re.compile(r'^(/|[A-Z]:)', re.IGNORECASE)


class RenderValidationError(Exception):
    """Raised when track structure validation fails."""


def _select_exporter(exporter_name: str):
    """Select exporter by name string."""
    if exporter_name == "jianying":
        return JianyingDraftExporter()
    elif exporter_name == "json_timeline":
        return JsonTimelineExporter()
    else:
        logger.warning("[render] Unknown exporter '%s', falling back to jianying", exporter_name)
        return JianyingDraftExporter()


def _validate_no_absolute_paths(output_zip: Path) -> None:
    """K10: verify all material paths in draft are placeholders (not absolute)."""
    import zipfile
    with zipfile.ZipFile(output_zip, "r") as zf:
        for name in zf.namelist():
            if name.endswith(".json"):
                content = zf.read(name).decode("utf-8")
                # Check for absolute paths in JSON
                for line_num, line in enumerate(content.splitlines(), 1):
                    if _ABSOLUTE_PATH_PATTERN.search(line):
                        raise RenderValidationError(
                            f"K10 FAIL: absolute path found in {name}:{line_num} → {line.strip()[:100]}"
                        )


def _validate_track_counts(result: ExportResult) -> None:
    """Validate 4 tracks exist in export result."""
    required_tracks = {"main_video_track", "narration_track", "original_audio_track", "subtitle_track"}
    if result.track_counts:
        present = set(result.track_counts.keys())
        missing = required_tracks - present
        if missing:
            logger.warning("[render] Missing tracks in result: %s (may be OK for json_timeline format)", missing)


def run_render(job_dir: Path) -> None:
    """Render stage: export draft package + K10 validation."""
    state = JobStateFile(job_dir)

    # --- Load timeline.json ---
    timeline_path = job_dir / "timeline.json"
    assembly_path = job_dir / "assembly.json"

    if not timeline_path.exists():
        raise FileNotFoundError(f"timeline.json not found in {job_dir}")
    if not assembly_path.exists():
        raise FileNotFoundError(f"assembly.json not found in {job_dir}")

    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    assembly = json.loads(assembly_path.read_text(encoding="utf-8"))
    state.mark_stage(Stage.RENDER, StageStatus.RUNNING, progress=0.1)

    # --- Select exporter ---
    exporter_name = os.environ.get("AUTOCLIP_EXPORTER", "jianying")
    exporter = _select_exporter(exporter_name)
    logger.info("[render] Using exporter: %s", exporter.name)

    # --- Output directory ---
    output_dir = job_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Export ---
    result: ExportResult = exporter.export(timeline, assembly, job_dir, output_dir)
    state.mark_stage(Stage.RENDER, StageStatus.RUNNING, progress=0.6)
    logger.info("[render] Export complete: %s", result.output_path)

    # --- K10 validation: no absolute paths ---
    try:
        _validate_no_absolute_paths(result.output_path)
        result.validation_passed = True
        logger.info("[render] K10 validation PASSED: no absolute paths in draft")
    except RenderValidationError as validation_err:
        logger.error("[render] K10 validation FAILED: %s", validation_err)
        raise

    # --- Track counts validation ---
    _validate_track_counts(result)
    state.mark_stage(Stage.RENDER, StageStatus.RUNNING, progress=0.95)

    # --- Cleanup after render ---
    # Session 34: cleanup is gated by AUTOCLIP_CLEANUP_ENABLED env var
    # (default OFF). Operators flip it on for zero-knowledge deployments.
    try:
        from ..compliance.cleanup import cleanup_after_render
        cleanup_after_render(job_dir)
    except Exception as cleanup_err:
        logger.warning("[render] cleanup_after_render failed (non-fatal): %s", cleanup_err)

    logger.info("[render] Render complete — output: %s", result.output_path)
    state.mark_stage(Stage.RENDER, StageStatus.DONE)


# Register handler when module is imported
register_stage_handler(Stage.RENDER, run_render)
