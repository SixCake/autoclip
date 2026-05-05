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
    FEW_SHOT_EXAMPLE,
    STYLE_DESCRIPTION,
)

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
) -> list:
    """Build SystemMessage + HumanMessage for narrative IR generation.

    Args:
        plot_outline_dict: PlotOutline.to_dict() output (contains main_characters for role injection).
        asr_with_timestamps: ASR text with timestamps (will be truncated to 40k chars if longer).
        target_duration_sec: Target video duration in seconds (for sentence count estimation).

    Returns:
        List of LangChain BaseMessage instances.
    """
    # Truncate ASR to 40k characters
    truncated_asr = asr_with_timestamps[:40000] if len(asr_with_timestamps) > 40000 else asr_with_timestamps

    # Estimate target sentence count
    target_sentences = int(target_duration_sec / 6)

    # Check if main_characters is empty (degrade path)
    main_characters = plot_outline_dict.get("main_characters", [])
    if not main_characters:
        # Omit role-aware constraints when no characters available
        style_desc = STYLE_DESCRIPTION.split("【角色称呼】")[0].strip()
        role_clause = "\n\n【角色称呼】\n当前剧情大纲未提供角色信息，可使用通用指代如「他」「她」"
        style_desc += role_clause
    else:
        style_desc = STYLE_DESCRIPTION

    system_content = SYSTEM_PROMPT_TEMPLATE.format(
        style_description=style_desc,
    )

    user_content = USER_PROMPT_TEMPLATE.format(
        plot_outline_json=json.dumps(plot_outline_dict, ensure_ascii=False, indent=2),
        asr_with_timestamps=truncated_asr,
        few_shot_json=json.dumps(FEW_SHOT_EXAMPLE, ensure_ascii=False, indent=2),
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
