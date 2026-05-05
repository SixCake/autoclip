"""Narrative IR prompt builder (v0.8 correction — specific observation + stance interpretation).

Builds messages for LLM to generate NarrativeIR from plot_outline + asr_with_timestamps.
Injects role-aware style constraints from style_presets/plot_summary.py.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from autoclip.algo.narrative_ir import NarrativeIR, NarrativeParagraph, NarrativeSentence
from autoclip.prompts.style_presets.plot_summary import (
    FEW_SHOT_EXAMPLE as _PLOT_SUMMARY_FEW_SHOT,
    STYLE_DESCRIPTION as _PLOT_SUMMARY_STYLE,
)
from autoclip.prompts.style_presets.humor_roast import (
    FEW_SHOT_EXAMPLE as _HUMOR_ROAST_FEW_SHOT,
    STYLE_DESCRIPTION as _HUMOR_ROAST_STYLE,
)
from autoclip.prompts.style_presets.serious_review import (
    FEW_SHOT_EXAMPLE as _SERIOUS_REVIEW_FEW_SHOT,
    STYLE_DESCRIPTION as _SERIOUS_REVIEW_STYLE,
)

_STYLE_REGISTRY = {
    "plot_summary": (_PLOT_SUMMARY_STYLE, _PLOT_SUMMARY_FEW_SHOT),
    "humor_roast": (_HUMOR_ROAST_STYLE, _HUMOR_ROAST_FEW_SHOT),
    "serious_review": (_SERIOUS_REVIEW_STYLE, _SERIOUS_REVIEW_FEW_SHOT),
}

# Backward-compat aliases (plot_summary default)
STYLE_DESCRIPTION = _PLOT_SUMMARY_STYLE
FEW_SHOT_EXAMPLE = _PLOT_SUMMARY_FEW_SHOT

# === Prompt template ===

SYSTEM_PROMPT_TEMPLATE = """你是一位 B 站头部二创解说 UP 主，擅长把原视频改写成有"二创灵魂"的解说稿。

{style_description}

输出必须是严格的 JSON 格式，符合以下 Schema：
{{
  "paragraphs": [
    {{
      "paragraph_idx": integer,
      "topic": string,
      "approx_source_start_sec": float,
      "approx_source_end_sec": float,
      "sentences": [
        {{
          "sentence_idx": integer,
          "text": string,
          "evidence_keywords": [string]
        }}
      ]
    }}
  ]
}}
"""

USER_PROMPT_TEMPLATE = """剧情大纲：
{plot_outline_json}

ASR 带时间戳文本（可能截断至 40k 字符）：
{asr_with_timestamps}

Few-shot 示例（供参考风格，不要照抄内容）：
{few_shot_json}

请严格按照上述 JSON Schema 输出 NarrativeIR，确保每句都是"具体观察 + 立场解读"。
"""


def build_narrative_ir_messages(
    plot_outline_dict: dict[str, Any],
    asr_with_timestamps: str,
    target_duration_sec: float,
    persona_id: str | None = None,
    persona_reference_lines: list[str] | None = None,
    style_preset: str = "plot_summary",
) -> list:
    """Build SystemMessage + HumanMessage for narrative IR generation.

    Args:
        plot_outline_dict: PlotOutline.to_dict() output (contains main_characters for role injection).
        asr_with_timestamps: ASR text with timestamps (will be truncated to 40k chars if longer).
        target_duration_sec: Target video duration in seconds (for sentence count estimation).
        persona_id: Optional persona id from v0.8.3 inferer (e.g., "toxic_middle_aged"). If None,
                    a generic placeholder block is used.
        persona_reference_lines: Optional list of reference lines extracted from
                    docs/personas/{persona_id}.md via persona_inferer.extract_reference_lines().
                    If None or empty, a placeholder block is used.
        style_preset: One of plot_summary / humor_roast / serious_review (M4.3).

    Returns:
        List of LangChain BaseMessage instances.
    """
    # Truncate ASR to 40k characters
    truncated_asr = asr_with_timestamps[:40000] if len(asr_with_timestamps) > 40000 else asr_with_timestamps

    # Estimate target sentence count
    target_sentences = int(target_duration_sec / 6)

    # Build persona reference block (v0.8.4): inject 3-5 lines from docs/personas/{persona_id}.md
    # If caller did not supply persona info, use a generic fallback (preserves prior behavior).
    if persona_id and persona_reference_lines:
        # Cap at 5 lines to control token cost; each line ≤200 chars (persona md authored).
        capped_lines = persona_reference_lines[:5]
        persona_reference_block = f"（推荐人格：{persona_id}）\n" + "\n".join(
            f"- {line}" for line in capped_lines
        )
    else:
        persona_reference_block = "（未指定人格，使用通用 B 站二创解说语气）"

    # Check if main_characters is empty (degrade path)
    # Karpathy §3 fix: caller must explicitly format ALL placeholders in STYLE_DESCRIPTION
    # (target_duration_sec / target_sentences / persona_reference_block). Previous version
    # left {target_*} unreplaced, leaking literal "{target_duration_sec}" into the LLM prompt.
    # M4.3: select style preset
    selected_style_desc, selected_few_shot = _STYLE_REGISTRY.get(
        style_preset, (_PLOT_SUMMARY_STYLE, _PLOT_SUMMARY_FEW_SHOT)
    )

    main_characters = plot_outline_dict.get("main_characters", [])
    if not main_characters:
        # Omit role-aware constraints when no characters available; keep persona block intact
        # (persona_reference_block sits BEFORE 【角色称呼】 in STYLE_DESCRIPTION, so split is safe).
        style_desc_raw = selected_style_desc.split("【角色称呼】")[0].strip()
        role_clause = "\n\n【角色称呼】\n当前剧情大纲未提供角色信息，可使用通用指代如「他」「她」"
        style_desc_raw += role_clause
    else:
        style_desc_raw = selected_style_desc

    style_desc = style_desc_raw.format(
        target_duration_sec=target_duration_sec,
        target_sentences=target_sentences,
        persona_reference_block=persona_reference_block,
    )

    system_content = SYSTEM_PROMPT_TEMPLATE.format(
        style_description=style_desc,
    )

    user_content = USER_PROMPT_TEMPLATE.format(
        plot_outline_json=json.dumps(plot_outline_dict, ensure_ascii=False, indent=2),
        asr_with_timestamps=truncated_asr,
        few_shot_json=json.dumps(selected_few_shot, ensure_ascii=False, indent=2),
    )

    return [
        SystemMessage(content=system_content),
        HumanMessage(content=user_content),
    ]


def parse_narrative_ir_response(raw: str) -> NarrativeIR:
    """Parse LLM raw response into NarrativeIR dataclass.

    Args:
        raw: Raw string response from LLM (JSON format).

    Returns:
        NarrativeIR instance.

    Raises:
        ValueError: If JSON is invalid or schema mismatch.
    """
    try:
        data = json.loads(raw.strip())
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in LLM response: {e}") from e

    paragraphs = []
    for para_data in data.get("paragraphs", []):
        sentences = [
            NarrativeSentence(
                sentence_idx=s["sentence_idx"],
                text=s["text"],
                evidence_keywords=s.get("evidence_keywords", []),
            )
            for s in para_data.get("sentences", [])
        ]
        paragraphs.append(
            NarrativeParagraph(
                paragraph_idx=para_data["paragraph_idx"],
                topic=para_data["topic"],
                approx_source_start_sec=para_data["approx_source_start_sec"],
                approx_source_end_sec=para_data["approx_source_end_sec"],
                sentences=sentences,
            )
        )

    return NarrativeIR(paragraphs=paragraphs)
