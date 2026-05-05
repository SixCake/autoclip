"""Self-evaluation prompt builder (M4.4).

Builds LLM messages to evaluate a finished narration draft on 4 dimensions.
Input: timeline.json fields (plot_outline + sentences + binding_stats).
Output JSON schema:
  {
    "scores": {"script_quality": int, "visual_match": int, "rhythm": int, "publishable": int},
    "feedback": {"script_quality": str, "visual_match": str, "rhythm": str, "publishable": str},
    "overall": float,
    "suggestion": str
  }
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

SYSTEM_PROMPT = """你是一位严格的二创视频解说稿质量评审员，擅长用量化维度评估 B 站二创解说稿质量。

请对给定的解说稿从 4 个维度逐项评分（每项 1-5 分，整数）：
1. **script_quality（解说稿质量）**：句子通顺度、剧情还原度、是否有错别字、是否有 AI 味套话
2. **visual_match（镜头匹配度）**：解说内容与镜头画面的对应程度（evidence_keywords 命中率）
3. **rhythm（节奏感）**：解说速度是否舒适、句长是否合适、停顿合理性
4. **publishable（整体可发布性）**：如果这是真实 UP 主创作的内容，是否适合原封不动发到 B 站

评分标准：
- 5分：优秀，几乎无需修改
- 4分：良好，小调整即可发布
- 3分：中等，需要中等程度修改
- 2分：较差，需要大幅修改
- 1分：很差，需要重新生成

输出必须是严格的 JSON，格式如下：
{
  "scores": {
    "script_quality": <1-5整数>,
    "visual_match": <1-5整数>,
    "rhythm": <1-5整数>,
    "publishable": <1-5整数>
  },
  "feedback": {
    "script_quality": "<简短的中文说明，说明这个维度给分的原因>",
    "visual_match": "<简短的中文说明>",
    "rhythm": "<简短的中文说明>",
    "publishable": "<简短的中文说明>"
  },
  "overall": <四项平均值，保留1位小数>,
  "suggestion": "<针对最低分维度，给出1-2句具体改进建议>"
}
"""

USER_PROMPT_TEMPLATE = """以下是待评审的解说稿信息：

【剧情大纲摘要】
{plot_outline_summary}

【binding_stats（绑定统计）】
{binding_stats_json}

【解说稿句子列表】
{sentences_json}

请按照要求输出 JSON 格式的评审结果。
"""


def build_self_evaluate_messages(timeline: dict[str, Any]) -> list:
    """Build SystemMessage + HumanMessage for self-evaluation."""
    plot_outline = timeline.get("plot_outline", {})
    plot_summary = f"{plot_outline.get('genre', '')} — {plot_outline.get('plot_summary', '')[:300]}"

    binding_stats = timeline.get("binding_stats", {})

    # Flatten sentences from narrative_ir paragraphs
    sentences: list[dict] = []
    narrative_ir = timeline.get("narrative_ir", {})
    for para in narrative_ir.get("paragraphs", []):
        for sent in para.get("sentences", []):
            sentences.append({
                "idx": sent.get("sentence_idx"),
                "text": sent.get("text", ""),
                "evidence_keywords": sent.get("evidence_keywords", []),
            })

    user_content = USER_PROMPT_TEMPLATE.format(
        plot_outline_summary=plot_summary,
        binding_stats_json=json.dumps(binding_stats, ensure_ascii=False, indent=2),
        sentences_json=json.dumps(sentences[:40], ensure_ascii=False, indent=2),  # cap at 40 sentences
    )

    return [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=user_content),
    ]


def parse_self_evaluate_response(raw: str) -> dict[str, Any]:
    """Parse LLM response into self-evaluation dict. Gracefully handles missing fields."""
    import re
    # Strip markdown code blocks if present
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Fallback: extract JSON object
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            data = json.loads(match.group())
        else:
            return _fallback_evaluation("JSON parse error")

    scores = data.get("scores", {})
    if not scores:
        return _fallback_evaluation("Missing scores field")

    # Auto-calculate overall if missing or wrong
    score_values = [scores.get(k, 3) for k in ("script_quality", "visual_match", "rhythm", "publishable")]
    calculated_overall = round(sum(score_values) / len(score_values), 1)

    return {
        "scores": {
            "script_quality": scores.get("script_quality", 3),
            "visual_match": scores.get("visual_match", 3),
            "rhythm": scores.get("rhythm", 3),
            "publishable": scores.get("publishable", 3),
        },
        "feedback": data.get("feedback", {}),
        "overall": data.get("overall", calculated_overall),
        "suggestion": data.get("suggestion", ""),
    }


def _fallback_evaluation(reason: str) -> dict[str, Any]:
    """Return neutral evaluation on parse failure."""
    return {
        "scores": {"script_quality": 3, "visual_match": 3, "rhythm": 3, "publishable": 3},
        "feedback": {
            "script_quality": f"评分失败（{reason}）",
            "visual_match": "",
            "rhythm": "",
            "publishable": "",
        },
        "overall": 3.0,
        "suggestion": "请手动检查解说稿质量",
    }
