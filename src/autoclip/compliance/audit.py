"""Audit CLI — inspect and purge autoclip data (zero-knowledge compliance).

Usage:
    python -m autoclip.audit list
    python -m autoclip.audit purge --job-id N
    python -m autoclip.audit purge --all --confirm
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from ..config import get_settings


def _get_data_dir() -> Path:
    return get_settings().data_dir


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 ** 2:
        return f"{size_bytes/1024:.1f}KB"
    elif size_bytes < 1024 ** 3:
        return f"{size_bytes/1024**2:.1f}MB"
    else:
        return f"{size_bytes/1024**3:.2f}GB"


def _list_job_files(job_dir: Path) -> list[tuple[str, int]]:
    """List all files in a job directory with sizes."""
    files = []
    for path in sorted(job_dir.rglob("*")):
        if path.is_file():
            rel = path.relative_to(job_dir)
            files.append((str(rel), path.stat().st_size))
    return files


def cmd_list(data_dir: Path) -> None:
    """List all data held by autoclip."""
    jobs_dir = data_dir / "jobs"
    if not jobs_dir.exists():
        print("No jobs directory found.")
        return

    job_dirs = sorted(jobs_dir.iterdir(), key=lambda p: p.name)
    if not job_dirs:
        print("No jobs found.")
        return

    total_size = 0
    for job_dir in job_dirs:
        if not job_dir.is_dir():
            continue
        files = _list_job_files(job_dir)
        job_total = sum(size for _, size in files)
        total_size += job_total
        print(f"\nJob {job_dir.name}  [{_format_size(job_total)}]")
        for filename, size in files:
            print(f"  {filename:<40} {_format_size(size):>10}")

    print(f"\nTotal: {_format_size(total_size)} across {len(job_dirs)} jobs")


def cmd_purge_job(data_dir: Path, job_id: int) -> None:
    """Immediately delete all data for one job."""
    job_dir = data_dir / "jobs" / str(job_id)
    if not job_dir.exists():
        print(f"Job {job_id} not found at {job_dir}")
        sys.exit(1)

    files = _list_job_files(job_dir)
    total_size = sum(size for _, size in files)
    print(f"Purging job {job_id}: {len(files)} files, {_format_size(total_size)}")
    shutil.rmtree(job_dir)
    print(f"Job {job_id} data purged.")


def cmd_purge_all(data_dir: Path) -> None:
    """Nuclear option: delete all job data."""
    jobs_dir = data_dir / "jobs"
    if not jobs_dir.exists():
        print("Nothing to purge.")
        return

    total = sum(1 for d in jobs_dir.iterdir() if d.is_dir())
    shutil.rmtree(jobs_dir)
    jobs_dir.mkdir()
    print(f"All data purged: {total} jobs deleted.")


def main() -> None:
    parser = argparse.ArgumentParser(description="AutoClip Audit CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List all held data")

    purge_parser = subparsers.add_parser("purge", help="Delete data")
    purge_group = purge_parser.add_mutually_exclusive_group(required=True)
    purge_group.add_argument("--job-id", type=int, help="Purge specific job")
    purge_group.add_argument("--all", action="store_true", help="Purge all jobs")
    purge_parser.add_argument("--confirm", action="store_true", help="Required for --all")

    args = parser.parse_args()
    data_dir = _get_data_dir()

    if args.command == "list":
        cmd_list(data_dir)
    elif args.command == "purge":
        if args.all:
            if not args.confirm:
                print("ERROR: --all requires --confirm flag")
                sys.exit(1)
            cmd_purge_all(data_dir)
        else:
            cmd_purge_job(data_dir, args.job_id)


if __name__ == "__main__":
    main()
