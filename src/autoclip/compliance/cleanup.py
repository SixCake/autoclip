"""Zero-knowledge cleanup — delete raw video files after pipeline completion.

K9 contract (design.md §16.5):
- normalized.mp4 + temp/ deleted immediately after Render stage succeeds
- output/*.zip deleted 24h after creation (cron job)
- Deletions logged to audit log (filename + size + reason, no content)
"""

from __future__ import annotations

import logging
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_AUDIT_LOG_FILENAME = "audit.log"
_OUTPUT_MAX_AGE_SECONDS = 24 * 3600  # 24 hours


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


def cleanup_after_render(job_dir: Path, *, preserve_source_video: bool = False) -> None:
    """Delete raw video files immediately after Render stage succeeds.

    Deletes:
    - normalized.mp4 (large; created by ingest)
    - source.mp4 (raw upload; kept during pipeline, deleted after export)
    - temp/ directory (intermediate files)

    Args:
        preserve_source_video: when True, source.mp4 is NOT deleted. Used by
            the install-to-jianying branch (Session 33) where the local Jianying
            draft references source.mp4 via absolute path; deleting it would
            break the linked draft. normalized.mp4 + temp/ are always cleaned.
    """
    deleted_count = 0

    files_to_delete = ["normalized.mp4"]
    if not preserve_source_video:
        files_to_delete.append("source.mp4")

    for filename in files_to_delete:
        target = job_dir / filename
        if _safe_delete_file(target, "post_render_cleanup", job_dir):
            deleted_count += 1

    if preserve_source_video:
        _audit_log(
            job_dir,
            "PRESERVE source.mp4 reason=installed_to_jianying (K10 双轨制 install branch)",
        )

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
