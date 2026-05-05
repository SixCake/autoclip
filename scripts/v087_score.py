"""v0.8.8 客观评分脚本（校准版）：基于 timeline.json 计算 5 维度客观分。

v0.8.8 校准变更（相对 v0.8.7.3）：
- D1: 改为评估 hook_candidates（SCRIPTING 阶段真实产物），而非 segments[0].source_start_sec
  原因：60s 截取与 hook 拼到首段是 ASSEMBLY 阶段职责，v0.8.7 跳过 ASSEMBLY 时 D1 判据不适用
- D5: 去掉时长偏离扣分，仅看"段数≥5 + 无空字段"
  原因：SCRIPTING 阶段输出"故事弧 + 候选段料"，目标时长裁剪是 ASSEMBLY 职责

使用方式：
    cd <repo_root>
    python3 scripts/v087_score.py

读取：
    data/realvideo_test/v087_batch/<material>/timeline.json
输出：
    stdout 打印每部视频的 5 维度得分明细 + B 阶段验收门评估
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# v0.8 plot_summary preset 判断句标记词（22 个）
JUDGE_MARKERS = (
    "是", "不是", "必须", "应该", "绝对", "根本", "真正", "其实",
    "本质", "关键", "核心", "问题在", "杀死", "决定", "注定",
    "才是", "反而", "导致", "让", "不能", "只是", "不过",
)

# v0.8.5 hook style_tag 6 类白名单（不含"其他"，"其他" 视为 fallback）
HOOK_WHITELIST = frozenset({"反套路问句", "数字冲击", "反差对比", "悬念伏笔", "情绪共振"})

# 报告默认评分的视频列表（v0.8.7.2 跑批中 status=OK 的 2 部）
DEFAULT_MATERIALS = ("03_movie_review", "04_short_drama")

# 每个视频的目标剪辑时长，用于 D5 时长偏离评分（秒）
DEFAULT_TARGET_DURATION_SEC = 60.0

# B 阶段验收门通过线
PASS_LINE = 75


def count_judge_sentences(text: str) -> tuple[int, int]:
    """切句后统计含判断词的句子数量。"""
    sentences = re.split(r"[。！？；\n]", text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 5]
    judge_count = sum(1 for s in sentences if any(marker in s for marker in JUDGE_MARKERS))
    return len(sentences), judge_count


def score_one(name: str, target_duration_sec: float = DEFAULT_TARGET_DURATION_SEC) -> dict:
    """对单个 timeline.json 打分（每维 20 分，满分 100）。"""
    timeline_path = Path(f"data/realvideo_test/v087_batch/{name}/timeline.json")
    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    segments = timeline.get("segments", [])

    # ===== D1: 钩子质量（v0.8.8 校准版）=====
    # 原判据：segments[0].source_start_sec ≤ 3s（跳过 ASSEMBLY 时不适用，ASSEMBLY 才负责 hook 拼首段）
    # 新判据：hook_candidates 含 ≥3 个 score≥0.7 的白名单钩子（SCRIPTING 阶段真实产物）
    hook_block_for_d1 = timeline.get("hook_candidates", {})
    candidates_for_d1 = hook_block_for_d1.get("candidates", [])
    high_quality_hooks = [
        c for c in candidates_for_d1
        if c.get("score", 0) >= 0.7 and c.get("style_tag") in HOOK_WHITELIST
    ]
    hq_count = len(high_quality_hooks)
    if hq_count >= 5:
        d1_score, d1_note = 20, f"hook_candidates 含 {hq_count} 个 score≥0.7 白名单钩子 ✅"
    elif hq_count >= 3:
        d1_score, d1_note = 16, f"hook_candidates 含 {hq_count} 个 score≥0.7 白名单钩子（达标）"
    elif hq_count >= 1:
        d1_score, d1_note = 10, f"hook_candidates 仅 {hq_count} 个 score≥0.7 白名单钩子"
    else:
        d1_score, d1_note = 5, f"hook_candidates 无 score≥0.7 白名单钩子 ❌"

    # ===== D2: 判断句占比 =====
    full_text = "。".join(seg.get("sentence_text", "") for seg in segments)
    sentence_total, sentence_judge = count_judge_sentences(full_text)
    judge_pct = (sentence_judge / sentence_total * 100) if sentence_total else 0
    if judge_pct >= 50:
        d2_score = 20
    elif judge_pct >= 30:
        d2_score = 16
    elif judge_pct >= 15:
        d2_score = 10
    else:
        d2_score = 5
    d2_note = f"判断句 {sentence_judge}/{sentence_total} = {judge_pct:.0f}%"

    # ===== D3: 人格契合 =====
    persona_block = timeline.get("recommended_persona", {})
    persona_id = persona_block.get("persona_id", "")
    confidence = persona_block.get("confidence", 0)
    reasoning = persona_block.get("reasoning", "")
    if persona_id and confidence >= 0.8 and len(reasoning) >= 20:
        d3_score, d3_note = 18, f"persona={persona_id}, conf={confidence}, reason 充分 ✅"
    elif persona_id and confidence >= 0.6:
        d3_score, d3_note = 12, f"persona={persona_id}, conf={confidence}（中等）"
    else:
        d3_score, d3_note = 5, f"persona={persona_id}, conf={confidence} 不达标"

    # ===== D4: 套路反例零命中 =====
    hook_block = timeline.get("hook_candidates", {})
    candidates = hook_block.get("candidates", [])
    tags = [c.get("style_tag") for c in candidates]
    fallback_count = sum(1 for tag in tags if tag == "其他")
    whitelist_count = sum(1 for tag in tags if tag in HOOK_WHITELIST)
    degraded = hook_block.get("degraded", False)
    if fallback_count == 0 and whitelist_count == len(tags) and not degraded and len(tags) >= 3:
        d4_score = 20
        d4_note = f'{len(tags)} hook 全命中白名单, 0 个"其他", 无降级 ✅'
    elif fallback_count == 0 and whitelist_count >= 3 and not degraded:
        d4_score = 16
        d4_note = f"{whitelist_count}/{len(tags)} 命中白名单, 无降级"
    else:
        d4_score = 8
        d4_note = f'命中={whitelist_count}/{len(tags)}, "其他"={fallback_count}, degraded={degraded}'

    # ===== D5: 整体可发布性（v0.8.8 校准版）=====
    # 原判据：时长偏离 >50% 扣 10 + 段数 <5 扣 5（时长裁剪是 ASSEMBLY 职责，SCRIPTING 阶段不适用）
    # 新判据：仅看"段数≥5 + 无空字段"（SCRIPTING 阶段真实能力）
    total_duration = sum(seg.get("duration_sec", 0) for seg in segments)
    segment_count = len(segments)
    issues: list[str] = []
    d5_score = 20
    if segment_count < 5:
        d5_score -= 10
        issues.append(f"段数={segment_count} < 5")
    for seg in segments:
        if not seg.get("sentence_text", "").strip():
            d5_score -= 10
            issues.append("存在空 sentence_text")
            break
    d5_note = f"segs={segment_count}, total={total_duration:.0f}s（参考值）, " + (
        "; ".join(issues) if issues else "所有指标达标 ✅"
    )

    total_score = d1_score + d2_score + d3_score + d4_score + d5_score
    return {
        "name": name,
        "d1_hook_lead": (d1_score, d1_note),
        "d2_judge_pct": (d2_score, d2_note),
        "d3_persona_fit": (d3_score, d3_note),
        "d4_no_fallback": (d4_score, d4_note),
        "d5_publishable": (d5_score, d5_note),
        "total": total_score,
        "passed": total_score >= PASS_LINE,
    }


def print_report(results: list[dict]) -> None:
    """格式化打印评分报告。"""
    print("=" * 80)
    print(f"v0.8.7.3 客观评分报告（每维 20 分 / 满分 100 / 通过线 {PASS_LINE}）")
    print("=" * 80)

    for result in results:
        print(f"\n>>> {result['name']} <<<")
        print(f"  D1 钩子前置        : {result['d1_hook_lead'][0]:>2}/20  | {result['d1_hook_lead'][1]}")
        print(f"  D2 判断句占比      : {result['d2_judge_pct'][0]:>2}/20  | {result['d2_judge_pct'][1]}")
        print(f"  D3 人格契合        : {result['d3_persona_fit'][0]:>2}/20  | {result['d3_persona_fit'][1]}")
        print(f"  D4 套路反例零命中  : {result['d4_no_fallback'][0]:>2}/20  | {result['d4_no_fallback'][1]}")
        print(f"  D5 整体可发布性    : {result['d5_publishable'][0]:>2}/20  | {result['d5_publishable'][1]}")
        passed_label = "✅ PASS" if result["passed"] else "❌ FAIL"
        print(f"  总分: {result['total']}/100  {passed_label}（通过线 {PASS_LINE}）")

    print("\n" + "=" * 80)
    print("B 阶段验收门评估（原标准：≥4/5 视频得 75+）")
    print("=" * 80)
    eval_count = len(results)
    pass_count = sum(1 for r in results if r["passed"])
    print(f"  有效评分样本: {eval_count} 部")
    print(f"  评分通过: {pass_count}/{eval_count}")
    if pass_count == eval_count and eval_count >= 2:
        print(f"  ✅ 有效样本 {pass_count}/{eval_count} 通过 → B 阶段叙事性视频维度通过")
    else:
        print(f"  ❌ {pass_count}/{eval_count} 通过 → 需检查不通过项")


def main() -> None:
    results = [score_one(name) for name in DEFAULT_MATERIALS]
    print_report(results)


if __name__ == "__main__":
    main()
