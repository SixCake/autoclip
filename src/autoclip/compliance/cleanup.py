"""Zero-knowledge cleanup — delete raw video files after pipeline completion.

K9 contract (design.md §16.5):
- normalized.mp4 + source.mp4 + temp/ deleted immediately after Render stage succeeds
- output/*.zip deleted 24h after creation (cron job)
- Deletions logged to audit log (filename + size + reason, no content)

Session 34: cleanup is now gated by the AUTOCLIP_CLEANUP_ENABLED env var.
Default OFF — operators flip it on per-deployment when zero-knowledge
guarantees are required. When OFF, ALL artifacts (source.mp4, normalized.mp4,
tts/, temp/) are kept; only the audit-log line "CLEANUP_DISABLED" is written.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_AUDIT_LOG_FILENAME = "audit.log"
_OUTPUT_MAX_AGE_SECONDS = 24 * 3600  # 24 hours
_CLEANUP_ENABLED_ENV = "AUTOCLIP_CLEANUP_ENABLED"


def _cleanup_enabled() -> bool:
    """Read AUTOCLIP_CLEANUP_ENABLED env var. Default: False (cleanup OFF).

    Truthy values: "1", "true", "yes", "on" (case-insensitive).
    Anything else (including unset / empty) → False.
    """
    raw = os.environ.get(_CLEANUP_ENABLED_ENV, "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _audit_log(job_dir: Path | None, message: str) -> None:
    """Append one line to the audit log."""
    timestamp = datetime.now(UTC).isoformat()
    entry = f"[{timestamp}] {message}\n"

    if job_dir is not None:
        log_path = job_dir / _AUDIT_LOG_FILENAME
    else:
        # Global audit log in data root
        log_path = Path("data/audit.log")

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(entry)

    logger.info("AUDIT: %s", message)


def _safe_delete_file(path: Path, reason: str, job_dir: Path | None = None) -> bool:
    """Delete one file, logging the operation. Returns True if deleted."""
    if not path.exists():
        return False
    size = path.stat().st_size
    path.unlink()
    _audit_log(job_dir, f"DELETE_FILE path={path.name} size={size} reason={reason}")
    return True


def _safe_delete_dir(path: Path, reason: str, job_dir: Path | None = None) -> bool:
    """Delete a directory tree, logging the operation. Returns True if deleted."""
    if not path.exists():
        return False
    size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    shutil.rmtree(path)
    _audit_log(job_dir, f"DELETE_DIR path={path.name} total_size={size} reason={reason}")
    return True


def cleanup_after_render(job_dir: Path) -> None:
    """Delete raw video files immediately after Render stage succeeds.

    Gated by env var AUTOCLIP_CLEANUP_ENABLED (default OFF). When disabled,
    all artifacts are preserved and a single CLEANUP_DISABLED audit line is
    written. When enabled, deletes:
    - normalized.mp4 (large; created by ingest)
    - source.mp4 (raw upload)
    - temp/ directory (intermediate files)
    """
    if not _cleanup_enabled():
        _audit_log(
            job_dir,
            f"CLEANUP_DISABLED env={_CLEANUP_ENABLED_ENV} reason=default_off",
        )
        logger.info(
            "[cleanup] Skipped (AUTOCLIP_CLEANUP_ENABLED not set / falsy); "
            "all artifacts preserved at %s",
            job_dir,
        )
        return

    deleted_count = 0
    for filename in ("normalized.mp4", "source.mp4"):
        target = job_dir / filename
        if _safe_delete_file(target, "post_render_cleanup", job_dir):
            deleted_count += 1

    temp_dir = job_dir / "temp"
    if _safe_delete_dir(temp_dir, "post_render_cleanup", job_dir):
        deleted_count += 1

    logger.info("[cleanup] Post-render cleanup: %d items deleted from %s", deleted_count, job_dir)


def cron_cleanup_temp(data_dir: Path, max_age_hours: int = 24) -> int:
    """Scan output zips older than max_age_hours and delete them.

    Intended to run hourly as a background task. Returns count of deleted files.
    """
    max_age_seconds = max_age_hours * 3600
    now = time.time()
    deleted_count = 0

    jobs_dir = data_dir / "jobs"
    if not jobs_dir.exists():
        return 0

    for output_dir in jobs_dir.glob("*/output"):
        for zip_file in output_dir.glob("*.zip"):
            file_age = now - zip_file.stat().st_mtime
            if file_age > max_age_seconds:
                size = zip_file.stat().st_size
                zip_file.unlink()
                _audit_log(
                    None,
                    f"CRON_DELETE_OUTPUT path={zip_file} size={size} age_hours={file_age/3600:.1f}",
                )
                deleted_count += 1

    logger.info("[cleanup] Cron cleanup: %d expired output zips deleted", deleted_count)
    return deleted_count
