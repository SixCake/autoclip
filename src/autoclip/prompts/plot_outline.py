"""Plot Outline prompt builder + parser (M2a.2).

Builds messages for LLM to extract title_guess, genre, main_characters (role/name/description),
and key_acts (3-5 acts with time windows and involved_characters) from ASR text + duration_sec.

Supports markdown fence stripping in parse_plot_outline_response().
"""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from autoclip.algo.narrative_ir import (
    Character,
    KeyAct,
    PlotOutline,
    _CharacterRaw,
    _KeyActRaw,
    _PlotOutlineRaw,
)


# === Prompt template ===

SYSTEM_PROMPT = """你是一位资深的影视剧情分析专家和角色识别专家。

你的任务是从给定的视频对白文本（ASR 转录结果）和视频总时长中，提取出结构化的剧情大纲。

输出必须是严格的 JSON 格式，不要包含任何 Markdown 代码块标记（如 ```json ... ```），也不要包含任何额外的解释文字。

JSON Schema 如下：
{
  "title_guess": "string - 猜测的视频标题",
  "genre": "string - 视频类型，如'喜剧'/'动作'/'悬疑'/'爱情'",
  "main_characters": [
    {
      "role": "string - 功能性身份标签，如'男主'/'女主'/'反派A'/'导师'/'配角B'",
      "name": "string | null - 如果对白中明确出现了该角色的姓名（被他人喊出），则填入；否则为 null",
      "description": "string - 一句话角色画像，描述其性格、外貌或关键特征"
    }
  ],
  "plot_summary": "string - 整体剧情摘要，3-5 句话",
  "key_acts": [
    {
      "act_idx": "integer - 幕序号，1-5",
      "name": "string - 幕的简短名称，如'开场冲突'/'转折点'/'高潮对决'",
      "approx_start_sec": "float - 该幕大致的开始时间（秒）",
      "approx_end_sec": "float - 该幕大致的结束时间（秒）",
      "summary": "string - 该幕发生了什么事的简要描述",
      "involved_characters": ["string - 引用 main_characters 中的 role 值，列出本幕出现的角色"]
    }
  ]
}

关键约束：
1. main_characters 数量限定 2-6 个，仅列对剧情推动有作用的角色。
2. key_acts 数量限定 3-5 个。
3. approx_start_sec 和 approx_end_sec 必须基于对白上下文推算，不能超出视频总时长 duration_sec。
4. involved_characters 中的每个值必须是 main_characters 中已定义的 role 之一。
5. 请基于对白中的称呼（如「爸」「师父」「陛下」「X老师」「队长」）和上下文逻辑，推断主要角色的功能性身份（role）。
6. 如果对白中没有明确出现姓名，name 字段留 null，仅填 role 和 description。
7. 如果无法提取任何有效角色信息，main_characters 可以为空数组 []，下游会做降级处理。
"""

USER_PROMPT_TEMPLATE = """视频总时长: {duration_sec} 秒

ASR 对白文本（可能截断至 30k 字符）:
{asr_text}

请严格按照上述 JSON Schema 输出剧情大纲。
"""


def build_plot_outline_messages(asr_text: str, duration_sec: float) -> list:
    """Build SystemMessage + HumanMessage for plot outline extraction.

    Args:
        asr_text: Raw ASR transcript text (will be truncated to 30k chars if longer).
        duration_sec: Total video duration in seconds.

    Returns:
        List of LangChain BaseMessage instances.
    """
    # Truncate ASR text to 30k characters to avoid token overflow
    truncated_text = asr_text[:30000] if len(asr_text) > 30000 else asr_text

    system_msg = SystemMessage(content=SYSTEM_PROMPT)
    user_content = USER_PROMPT_TEMPLATE.format(
        duration_sec=duration_sec,
        asr_text=truncated_text,
    )
    user_msg = HumanMessage(content=user_content)

    return [system_msg, user_msg]


# === Parser with markdown fence support ===

FENCE_PATTERN = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def parse_plot_outline_response(raw: str) -> PlotOutline:
    """Parse LLM raw response into PlotOutline dataclass.

    Supports:
    - Plain JSON string
    - JSON wrapped in markdown fence (```json ... ``` or ``` ... ```)

    Args:
        raw: Raw string response from LLM.

    Returns:
        PlotOutline instance with validated fields.

    Raises:
        ValueError: If JSON is invalid, schema mismatch, or involved_characters reference unknown roles.
    """
    # Step 1: Strip markdown fence if present
    match = FENCE_PATTERN.search(raw)
    if match:
        json_str = match.group(1)
    else:
        json_str = raw.strip()

    # Step 2: Parse JSON
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in LLM response: {e}") from e

    # Step 3: Validate via Pydantic
    try:
        raw_model = _PlotOutlineRaw(**data)
    except Exception as e:
        raise ValueError(f"Schema validation failed: {e}") from e

    # Step 4: Convert to dataclasses with additional consistency checks
    characters = [
        Character(role=c.role, name=c.name, description=c.description)
        for c in raw_model.main_characters
    ]
    valid_roles = {c.role for c in characters}

    key_acts = []
    for act_raw in raw_model.key_acts:
        # Check involved_characters references
        for role_ref in act_raw.involved_characters:
            if role_ref not in valid_roles:
                raise ValueError(
                    f"involved_characters references unknown role '{role_ref}'. "
                    f"Valid roles: {valid_roles}"
                )
        key_acts.append(
            KeyAct(
                act_idx=act_raw.act_idx,
                name=act_raw.name,
                approx_start_sec=act_raw.approx_start_sec,
                approx_end_sec=act_raw.approx_end_sec,
                summary=act_raw.summary,
                involved_characters=act_raw.involved_characters,
            )
        )

    return PlotOutline(
        title_guess=raw_model.title_guess,
        genre=raw_model.genre,
        main_characters=characters,
        plot_summary=raw_model.plot_summary,
        key_acts=key_acts,
    )
