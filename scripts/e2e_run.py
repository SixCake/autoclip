"""M4.1 E2E run script — end-to-end pipeline test runner.

Usage:
    poetry run python scripts/e2e_run.py --video /path/to/video.mp4 --duration 90 --style plot_summary
    poetry run python scripts/e2e_run.py --video /path/to/video.mp4 --duration 60 --style humor_roast
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx


def _wait_for_completion(base_url: str, job_id: int, timeout_sec: int = 1200) -> dict:
    """Poll job status until done/failed or timeout."""
    start = time.time()
    while time.time() - start < timeout_sec:
        resp = httpx.get(f"{base_url}/api/jobs/{job_id}", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        job = data.get("job", {})
        state = data.get("state", {})
        status = job.get("status", "unknown")

        progress = job.get("progress", 0) * 100
        print(f"  [{datetime.now(UTC).strftime('%H:%M:%S')}] Job {job_id}: {status} ({progress:.0f}%)")

        if status in ("done", "failed", "cancelled"):
            return {"job": job, "state": state, "elapsed_sec": time.time() - start}

        time.sleep(5)

    raise TimeoutError(f"Job {job_id} did not complete within {timeout_sec}s")


def run_e2e(video_path: Path, target_duration: int, style: str, base_url: str = "http://localhost:8000") -> dict:
    """Run one E2E pipeline job and collect timing data."""
    print(f"\n{'='*60}")
    print(f"E2E Run: {video_path.name} | {target_duration}s | {style}")
    print(f"{'='*60}")

    # Upload video
    print("Uploading video...")
    start_upload = time.time()
    with open(video_path, "rb") as video_file:
        resp = httpx.post(
            f"{base_url}/api/jobs",
            data={
                "target_duration_sec": str(target_duration),
                "style_preset": style,
                "agreement_accepted": "true",
            },
            files={"file": (video_path.name, video_file, "video/mp4")},
            timeout=120,
        )
    resp.raise_for_status()
    job_data = resp.json()
    job_id = job_data["job_id"]
    upload_elapsed = time.time() - start_upload
    print(f"Job created: #{job_id} (upload: {upload_elapsed:.1f}s)")

    # Wait for completion
    print("Waiting for pipeline completion...")
    result = _wait_for_completion(base_url, job_id)
    total_elapsed = result["elapsed_sec"]

    # Collect stage timing from state.json
    state = result.get("state", {})
    stage_timings = {}
    if state:
        for stage_name, stage_data in state.get("stages", {}).items():
            started = stage_data.get("started_at")
            finished = stage_data.get("finished_at")
            if started and finished:
                s_dt = datetime.fromisoformat(started)
                f_dt = datetime.fromisoformat(finished)
                stage_timings[stage_name] = round((f_dt - s_dt).total_seconds(), 1)

    status = result["job"].get("status")
    print(f"\nResult: {status.upper()} | Total: {total_elapsed:.1f}s")
    if stage_timings:
        for stage, timing in stage_timings.items():
            print(f"  {stage:<12}: {timing:.1f}s")

    # Build e2e report
    report = {
        "job_id": job_id,
        "video": video_path.name,
        "target_duration_sec": target_duration,
        "style_preset": style,
        "status": status,
        "total_elapsed_sec": round(total_elapsed, 1),
        "upload_elapsed_sec": round(upload_elapsed, 1),
        "stage_timings_sec": stage_timings,
        "manual_tuning_time_min": None,  # Fill manually after reviewing result
        "timestamp": datetime.now(UTC).isoformat(),
    }

    # Save report
    reports_dir = Path("data/e2e_reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"e2e_job{job_id}_{video_path.stem}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nReport saved: {report_path}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="AutoClip E2E test runner")
    parser.add_argument("--video", required=True, help="Path to input video file")
    parser.add_argument("--duration", type=int, default=90, help="Target duration in seconds")
    parser.add_argument("--style", default="plot_summary", choices=["plot_summary", "humor_roast", "serious_review"])
    parser.add_argument("--server", default="http://localhost:8000", help="AutoClip server URL")
    args = parser.parse_args()

    video_path = Path(args.video)
    if not video_path.exists():
        print(f"ERROR: Video file not found: {video_path}")
        raise SystemExit(1)

    run_e2e(video_path, args.duration, args.style, args.server)


if __name__ == "__main__":
    main()
