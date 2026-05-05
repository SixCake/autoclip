"""Internal helper for test_scripting_realvideo.sh — bootstrap state + dispatch 3 stages + acceptance report.

Must be a real .py file (NOT stdin heredoc) because mp.Process(spawn) on macOS
re-imports __main__ in subprocess; stdin source can't be re-imported, leading
to FileNotFoundError on '<stdin>'.

Usage:
    python scripts/_realvideo_dispatcher.py <job_dir> <raw_video> <target_duration_sec>

Env vars consumed:
    AUTOCLIP_LLM_PROVIDER     — passed through to factory.get_llm
    WHISPER_MODEL_SIZE        — passed through to Settings.whisper_model_size
    DEEPSEEK_API_KEY          — required if provider=deepseek
    DASHSCOPE_API_KEY         — required if provider=dashscope
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

# Load .env BEFORE importing autoclip (Settings reads at import time)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(dotenv_path=REPO_ROOT / ".env")

# Validate API key for selected provider early
provider = os.environ.get("AUTOCLIP_LLM_PROVIDER", "deepseek")
if provider == "deepseek" and not os.environ.get("DEEPSEEK_API_KEY"):
    print("❌ DEEPSEEK_API_KEY not loaded from .env", file=sys.stderr)
    sys.exit(10)
if provider == "dashscope" and not os.environ.get("DASHSCOPE_API_KEY"):
    print("❌ DASHSCOPE_API_KEY not loaded from .env", file=sys.stderr)
    sys.exit(11)

# Now safe to import autoclip
from autoclip.pipeline.runner import _stage_entrypoint  # noqa: E402
from autoclip.pipeline.state import (  # noqa: E402
    JobStateFile,
    Stage,
    StageState,
    StageStatus,
)


def main() -> int:
    if len(sys.argv) != 4:
        print(
            "Usage: _realvideo_dispatcher.py <job_dir> <raw_video> <target_duration_sec>",
            file=sys.stderr,
        )
        return 1

    job_dir = Path(sys.argv[1])
    raw_video = Path(sys.argv[2])
    target_duration_sec = int(sys.argv[3])

    # Step 0: hash + bootstrap state.json
    print("[0/4] 📋 Bootstrapping state.json ...")
    sha = hashlib.sha256()
    with raw_video.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            sha.update(chunk)
    video_hash = sha.hexdigest()
    print(f"   video sha256: {video_hash[:16]}...")

    state = JobStateFile(job_dir)
    state.init_state(
        job_id=int(time.time()),  # ad-hoc, not in DB
        video_hash=video_hash,
        target_duration_sec=target_duration_sec,
        style_preset="plot_summary",
    )
    print(f"   ✅ state.json initialized at {state.path}")
    print()

    # Step 1-3: dispatch INGEST / INDEX / SCRIPT, skip ASSEMBLY/RENDER
    stages_to_run = [Stage.INGEST, Stage.INDEX, Stage.SCRIPT]
    for i, stage in enumerate(stages_to_run, start=1):
        print(f"[{i}/4] 🚀 Stage: {stage.value.upper()}")
        stage_t0 = time.time()
        proc = mp.Process(
            target=_stage_entrypoint,
            args=(stage.value, str(job_dir)),
            name=f"autoclip-stage-{stage.value}",
        )
        proc.start()
        proc.join()
        stage_elapsed = time.time() - stage_t0

        cur = state.load()
        slot = StageState.from_dict(cur["stages"][stage.value])

        if proc.exitcode != 0 or slot.status != StageStatus.DONE:
            print(
                f"   ❌ Stage {stage.value} FAILED "
                f"(exitcode={proc.exitcode}, status={slot.status.value})"
            )
            if slot.error:
                print(f"      error: {slot.error}")
            print(f"   debug: cat {state.path}")
            return 20 + i

        print(f"   ✅ Stage {stage.value} DONE in {stage_elapsed:.1f}s")
        print()

    # Step 4: acceptance report
    print("[4/4] 📊 Acceptance Report")
    print("════════════════════════════════════════════════════════════")

    timeline_path = job_dir / "timeline.json"
    if not timeline_path.exists():
        print(f"❌ timeline.json missing at {timeline_path}")
        return 30

    with timeline_path.open("r", encoding="utf-8") as f:
        timeline = json.load(f)

    # K3 LLM callback files
    llm_calls_dir = job_dir / "llm_calls"
    llm_call_files = (
        sorted(llm_calls_dir.glob("scripting_*.json"))
        if llm_calls_dir.exists()
        else []
    )
    print(f"  K3 LLM callback : {len(llm_call_files)} files in {llm_calls_dir.name}/")
    for p in llm_call_files:
        print(f"    - {p.name}")

    # Timeline summary stats — 字段名以 src/autoclip/models/timeline.py + scripting.py 写出 schema 为准
    segments = timeline.get("segments", [])
    n_segments = len(segments)
    total_bound = sum(
        seg.get("source_end_sec", 0) - seg.get("source_start_sec", 0)
        for seg in segments
    )
    # binding_stats 已由 scripting.py 算好, 优先读官方值; 退化方法只为 schema 异常兜底
    bstats = timeline.get("binding_stats", {})
    fallback_count = bstats.get(
        "fallback_count",
        sum(1 for seg in segments if str(seg.get("binding_method", "")).startswith("fallback")),
    )
    fallback_ratio = bstats.get(
        "fallback_ratio",
        (fallback_count / n_segments) if n_segments else 0.0,
    )

    print()
    print(f"  n_segments      : {n_segments}")
    print(f"  total bound     : {total_bound:.2f}s (target was {target_duration_sec}s)")
    print(f"  fallback_count  : {fallback_count} (M2a HINT_UNIFORM baseline 应为 0)")
    print(f"  fallback_ratio  : {fallback_ratio:.2%}  (KPI K3 target: <30% in M2b.5)")
    print()
    print("  📝 Plot Outline (top-level):")
    plot = timeline.get("plot_outline", {})
    print(f"    - title_guess   : {plot.get('title_guess', '?')}")
    print(f"    - genre         : {plot.get('genre', '?')}")
    print(f"    - plot_summary  : {plot.get('plot_summary', '?')}")
    chars = plot.get("main_characters", [])
    print(f"    - main_characters ({len(chars)} 个):")
    for ch in chars:
        role = ch.get("role", "?")
        name = ch.get("name") or "(无名)"
        desc = ch.get("description", "")
        if len(desc) > 60:
            desc = desc[:57] + "..."
        print(f"        · {role} ({name}) — {desc}")
    key_acts = plot.get("key_acts", [])
    print(f"    - key_acts ({len(key_acts)} 个):")
    for act in key_acts:
        idx = act.get("act_idx", "?")
        name = act.get("name", "?")
        s_sec = act.get("approx_start_sec", 0.0)
        e_sec = act.get("approx_end_sec", 0.0)
        summary = act.get("summary", "")
        if len(summary) > 70:
            summary = summary[:67] + "..."
        print(f"      [{idx}] {s_sec:>5.1f}s → {e_sec:>5.1f}s  {name}")
        print(f"           {summary}")

    # narrative_ir paragraph 信息 (供 segments 反查 topic)
    paragraphs = timeline.get("narrative_ir", {}).get("paragraphs", [])
    para_topic = {p.get("paragraph_idx"): p.get("topic", "?") for p in paragraphs}

    print()
    print("  🎬 Segments (narrative sentence → bound shots):")
    for seg in segments:
        order_idx = seg.get("order_idx", "?")
        para_idx = seg.get("paragraph_idx", "?")
        sent_idx = seg.get("sentence_idx", "?")
        ss = seg.get("source_start_sec", 0.0)
        es = seg.get("source_end_sec", 0.0)
        dur = seg.get("duration_sec", es - ss)
        method = seg.get("binding_method", "?")
        text = seg.get("sentence_text", "?")
        if len(text) > 70:
            text = text[:67] + "..."
        shots = seg.get("source_shot_ids", [])
        topic = para_topic.get(para_idx, "?")
        print(
            f"    [#{order_idx:>2}] p{para_idx}.s{sent_idx}  "
            f"{ss:>6.2f}s → {es:>6.2f}s  (Δ={dur:>5.2f}s, method={method}) shots={shots}"
        )
        print(f"           topic : {topic}")
        print(f"           text  : {text}")

    # 验收提示
    print()
    print("  💡 验收提示 (肉眼检查):")
    print("     1. plot_outline.title_guess + plot_summary 是否符合视频实际剧情?")
    print("     2. key_acts 的时间段切分是否合理 (开头/中段/结尾覆盖完整)?")
    print("     3. 各 segment.sentence_text 的中文叙述是否与 source_start/end_sec 对应的视频片段画面一致?")
    print("     4. 用 ffplay/quicktime 跳转到 source_start_sec 验证 5 个段落的 binding 准确度.")
    print("     5. cat asr.json 检查原始 ASR 句子内容与 narrative_ir 的 evidence_keywords 是否对应.")

    print()
    print("════════════════════════════════════════════════════════════")
    print("✨ All 3 stages DONE. Inspect full timeline:")
    print(f"   cat {timeline_path} | python -m json.tool")
    print(f"   ls -la {job_dir}/")
    print("════════════════════════════════════════════════════════════")
    return 0


if __name__ == "__main__":
    sys.exit(main())
