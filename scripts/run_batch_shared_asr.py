"""Batch runner with shared ASR model — avoids the ~8min cold-start per video.

Problem: run_v087_batch.sh calls `python _realvideo_dispatcher.py` once per video,
spawning a fresh Python process each time. faster-whisper large-v3 pays a ~8min
cold-start (ctranslate2 float16→float32 kernel compile) in every new process.

Solution: Run all videos in a single Python process. The module-level
`_MODEL_SINGLETON` in local_whisper.py is loaded ONCE for the first video and
reused for all subsequent videos. Only the INDEX stage is pulled out of the
subprocess to allow singleton sharing; INGEST and SCRIPT still run in
mp.Process (fault isolation matters there: ffmpeg crashes and LLM timeouts
should not kill the whole batch).

Usage:
    python scripts/run_batch_shared_asr.py \\
        data/realvideo_test/raw_v087 \\
        data/realvideo_test/v088_batch \\
        [target_duration_sec=60] [provider=deepseek] [whisper_model=large-v3]

    Materials are discovered automatically by globbing *.mp4 in raw_dir.
    Job dirs are named after the mp4 stem (without extension).
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing as mp
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from dotenv import load_dotenv

load_dotenv(dotenv_path=REPO_ROOT / ".env")

provider_name = os.environ.get("AUTOCLIP_LLM_PROVIDER", "deepseek")
if provider_name == "deepseek" and not os.environ.get("DEEPSEEK_API_KEY"):
    print("❌ DEEPSEEK_API_KEY not loaded from .env", file=sys.stderr)
    sys.exit(10)
if provider_name == "dashscope" and not os.environ.get("DASHSCOPE_API_KEY"):
    print("❌ DASHSCOPE_API_KEY not loaded from .env", file=sys.stderr)
    sys.exit(11)

# Import pipeline modules AFTER env is loaded
from autoclip.pipeline.index import run_index  # noqa: E402
from autoclip.pipeline.runner import _stage_entrypoint  # noqa: E402
from autoclip.pipeline.state import (  # noqa: E402
    JobStateFile,
    Stage,
    StageState,
    StageStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hash_video(raw_video: Path) -> str:
    sha = hashlib.sha256()
    with raw_video.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1 << 20), b""):
            sha.update(chunk)
    return sha.hexdigest()


def _run_subprocess_stage(
    stage: Stage,
    job_dir: Path,
    state: JobStateFile,
    label: str,
) -> bool:
    """Run a single stage in a subprocess. Returns True on success."""
    proc = mp.Process(
        target=_stage_entrypoint,
        args=(stage.value, str(job_dir)),
        name=f"autoclip-{stage.value}",
    )
    proc.start()
    proc.join()

    cur = state.load()
    slot = StageState.from_dict(cur["stages"][stage.value])

    if proc.exitcode != 0 or slot.status != StageStatus.DONE:
        error_detail = slot.error or "(no error field)"
        print(f"  ❌ [{label}] {stage.value} FAILED (exit={proc.exitcode}): {error_detail}")
        return False

    return True


def _run_index_in_process(
    job_dir: Path,
    state: JobStateFile,
    label: str,
) -> bool:
    """Run INDEX stage directly in this process (no subprocess).

    This is the key change that allows _MODEL_SINGLETON to be reused across
    multiple videos: the WhisperModel is loaded once and stays in memory.

    Tradeoff: if ASR crashes (OOM, segfault), it kills the whole batch.
    That is acceptable because: (1) the model is already loaded successfully
    after the first video; (2) a crash here almost certainly means the machine
    is out of memory for ALL subsequent videos anyway.
    """
    # Mark RUNNING manually — normally done by _stage_entrypoint before calling handler.
    # We replicate the contract from runner.py: entrypoint owns RUNNING(progress=0.0).
    state.mark_stage(Stage.INDEX, StageStatus.RUNNING, progress=0.0)

    try:
        run_index(job_dir)
        return True
    except Exception as exc:
        state.mark_stage(Stage.INDEX, StageStatus.FAILED, error=str(exc))
        print(f"  ❌ [{label}] index FAILED: {exc}")
        return False


def _process_one_video(
    raw_video: Path,
    job_dir: Path,
    target_duration_sec: int,
) -> dict:
    """Process a single video through INGEST → INDEX → SCRIPT.

    Returns a result dict with keys: name, status, elapsed_sec, error.
    """
    name = raw_video.stem
    result: dict = {"name": name, "status": "FAILED", "elapsed_sec": 0, "error": ""}
    label = name

    print(f"\n▶▶▶ {name} ◀◀◀")

    # Prepare job dir
    job_dir.mkdir(parents=True, exist_ok=True)
    raw_in_job = job_dir / "raw" / raw_video.name
    raw_in_job.parent.mkdir(parents=True, exist_ok=True)
    if not raw_in_job.exists():
        import shutil
        shutil.copy2(raw_video, raw_in_job)

    # Bootstrap state.json
    video_hash = _hash_video(raw_video)
    state = JobStateFile(job_dir)
    state.init_state(
        job_id=int(time.time()),
        video_hash=video_hash,
        target_duration_sec=target_duration_sec,
        style_preset="plot_summary",
    )
    print(f"  ✅ state.json initialized (hash={video_hash[:12]}...)")

    overall_t0 = time.time()

    # Stage 1: INGEST (subprocess — ffmpeg may crash)
    stage_t0 = time.time()
    if not _run_subprocess_stage(Stage.INGEST, job_dir, state, label):
        result["error"] = "INGEST FAILED"
        result["elapsed_sec"] = int(time.time() - overall_t0)
        return result
    print(f"  ✅ INGEST DONE in {time.time() - stage_t0:.1f}s")

    # Stage 2: INDEX (in-process — shares _MODEL_SINGLETON with other videos)
    stage_t0 = time.time()
    if not _run_index_in_process(job_dir, state, label):
        result["error"] = "INDEX FAILED"
        result["elapsed_sec"] = int(time.time() - overall_t0)
        return result
    print(f"  ✅ INDEX DONE in {time.time() - stage_t0:.1f}s  ← ASR shared model")

    # Stage 3: SCRIPT (subprocess — LLM may timeout)
    stage_t0 = time.time()
    if not _run_subprocess_stage(Stage.SCRIPT, job_dir, state, label):
        result["error"] = "SCRIPT FAILED"
        result["elapsed_sec"] = int(time.time() - overall_t0)
        return result
    print(f"  ✅ SCRIPT DONE in {time.time() - stage_t0:.1f}s")

    result["status"] = "OK"
    result["elapsed_sec"] = int(time.time() - overall_t0)
    return result


def main() -> int:
    if len(sys.argv) < 3:
        print(
            "Usage: run_batch_shared_asr.py <raw_dir> <batch_out_dir> "
            "[target_duration_sec=60] [provider=deepseek] [whisper_model=large-v3]",
            file=sys.stderr,
        )
        return 1

    raw_dir = Path(sys.argv[1])
    batch_out_dir = Path(sys.argv[2])
    target_duration_sec = int(sys.argv[3]) if len(sys.argv) > 3 else 60
    whisper_model = sys.argv[5] if len(sys.argv) > 5 else "large-v3"

    if not raw_dir.exists():
        print(f"❌ raw_dir not found: {raw_dir}", file=sys.stderr)
        return 2

    # Set whisper model env var (read by Settings.whisper_model_size)
    os.environ["WHISPER_MODEL_SIZE"] = whisper_model

    raw_videos = sorted(raw_dir.glob("*.mp4"))
    if not raw_videos:
        print(f"❌ No *.mp4 found in {raw_dir}", file=sys.stderr)
        return 3

    batch_out_dir.mkdir(parents=True, exist_ok=True)

    print("════════════════════════════════════════════════════════════")
    print("🎬 Batch Run (shared ASR model — no cold-start per video)")
    print("════════════════════════════════════════════════════════════")
    print(f"  raw_dir           : {raw_dir}")
    print(f"  batch_out_dir     : {batch_out_dir}")
    print(f"  target_duration   : {target_duration_sec}s")
    print(f"  whisper_model     : {whisper_model}")
    print(f"  videos            : {len(raw_videos)}")
    print("  INDEX stage       : in-process (shared _MODEL_SINGLETON)")
    print("  INGEST/SCRIPT     : subprocess (fault isolation)")
    print("════════════════════════════════════════════════════════════")

    all_results = []
    batch_t0 = time.time()

    for raw_video in raw_videos:
        job_dir = batch_out_dir / raw_video.stem
        result = _process_one_video(raw_video, job_dir, target_duration_sec)
        all_results.append(result)

        # Read timeline stats if available
        timeline_path = job_dir / "timeline.json"
        if result["status"] == "OK" and timeline_path.exists():
            with timeline_path.open("r", encoding="utf-8") as timeline_file:
                timeline = json.load(timeline_file)
            n_segs = len(timeline.get("segments", []))
            hc = timeline.get("hook_candidates", {})
            n_hooks = len(hc.get("candidates", []))
            persona_id = timeline.get("recommended_persona", {}).get("persona_id", "-")
            degraded = timeline.get("plot_outline_degraded", False)
            print(
                f"  📊 timeline: segments={n_segs} hooks={n_hooks} "
                f"persona={persona_id} degraded={degraded}"
            )

    batch_elapsed = int(time.time() - batch_t0)

    # Summary
    print("\n════════════════════════════════════════════════════════════")
    print("📊 Batch Summary")
    print("════════════════════════════════════════════════════════════")
    ok_count = sum(1 for r in all_results if r["status"] == "OK")
    fail_count = len(all_results) - ok_count
    for result in all_results:
        status_icon = "✅" if result["status"] == "OK" else "❌"
        error_suffix = f" — {result['error']}" if result["error"] else ""
        print(f"  {status_icon} {result['name']}: {result['status']} ({result['elapsed_sec']}s){error_suffix}")

    print(f"\n  OK: {ok_count}/{len(all_results)} | FAIL: {fail_count}/{len(all_results)}")
    print(f"  Total wall time: {batch_elapsed}s")
    print("  Note: INDEX stage ran in-process — ASR model loaded only ONCE")
    print("════════════════════════════════════════════════════════════")

    # Write results TSV
    results_tsv = batch_out_dir / "_results.tsv"
    with results_tsv.open("w", encoding="utf-8") as tsv_file:
        tsv_file.write("material\tstatus\telapsed_sec\terror\n")
        for result in all_results:
            tsv_file.write(f"{result['name']}\t{result['status']}\t{result['elapsed_sec']}\t{result['error']}\n")
    print(f"  Results TSV: {results_tsv}")

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
