"""Persona Inferer (v0.8.3 — lightweight Stage1 LLM for persona recommendation only).

v0.8.3 changes vs v0.8 P1 original:
    - Q1 (scope): drop hook_candidates + paragraph_skeleton (now produced by v0.8.5 main LLM call)
    - Q2 (input): take PlotOutline (high-density LLM-summarized signal) instead of raw ASR
    - Q3 (fallback): strict mode — raise PersonaInferenceError on any failure; no silent default

Output: PersonaInferenceResult(persona_id, confidence, reasoning) — 3 fields only.

See docs/plans/tasks/M2a-fix-narrative-style.md §v0.8.3 for brainstorming history.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from autoclip.algo.narrative_ir import PlotOutline


# === Constants ===

VALID_PERSONA_IDS: frozenset[str] = frozenset(
    {
        "toxic_middle_aged",
        "healing_big_sister",
        "archaeologist",
        "rage_brother",
        "empathy_senior",
        "sarcastic_gen_z",
    }
)

# Strip ```json ... ``` fences if LLM wraps output (DeepSeek json_mode usually clean, but be safe)
_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


# === Exceptions ===


class PersonaInferenceError(RuntimeError):
    """Raised when persona inference fails (invalid JSON / persona not in whitelist / API error).

    Per Q3 brainstorming decision (strict mode): no silent fallback. Caller decides recovery.
    """


# === Data Models ===


@dataclass(frozen=True)
class PersonaInferenceResult:
    """Output of infer_persona() — 3 fields only (v0.8.3 lightweight version)."""

    persona_id: str  # Must be one of VALID_PERSONA_IDS
    confidence: float  # 0.0 - 1.0
    reasoning: str  # ≤50 字 解释，便于人工 review 与 v0.8.7 跑批分析


# === Prompts ===

SYSTEM_PROMPT = """你是 B 站二创内容策略分析师。给定剧情大纲，从下列 6 个人格中选最匹配的 1 个。

【人格库】
- toxic_middle_aged（毒舌中年）：犀利讽刺，适合烂片吐槽、社会现象
- healing_big_sister（治愈大姐）：温暖共情，适合情感剧、家庭剧、儿歌
- archaeologist（考古学家）：学术接地气，适合经典电影重读、文化符号
- rage_brother（暴躁老哥）：直接粗粝，适合烂片吐槽、逻辑漏洞
- empathy_senior（共情学姐）：温柔细腻，适合青春剧、成长故事
- sarcastic_gen_z（讽刺 Z 世代）：玩梗反讽，适合年轻化内容、套路拆解

【输出严格 JSON】
{
  "persona_id": "<必须是上面 6 个之一>",
  "confidence": <0.0-1.0 浮点数>,
  "reasoning": "<≤50 字中文解释为何选此人格>"
}
"""

USER_PROMPT = """剧情大纲：
- 标题猜测：{title_guess}
- 题材：{genre}
- 主要角色：{characters_brief}
- 剧情概要：{plot_summary}
- 关键段：{key_acts_brief}

请输出 JSON。
"""


# === Core Functions ===


def _format_plot_outline(plot_outline: PlotOutline) -> dict[str, str]:
    """Format PlotOutline into 5 short strings for prompt injection."""
    characters_brief = (
        "; ".join(f"{c.role}({c.name or '?'}): {c.description}" for c in plot_outline.main_characters)
        or "（无）"
    )
    key_acts_brief = (
        " → ".join(f"{a.act_idx}.{a.name}" for a in plot_outline.key_acts) or "（无）"
    )
    return {
        "title_guess": plot_outline.title_guess or "（未命名）",
        "genre": plot_outline.genre or "（未知）",
        "characters_brief": characters_brief,
        "plot_summary": plot_outline.plot_summary or "（无）",
        "key_acts_brief": key_acts_brief,
    }


def infer_persona(
    plot_outline: PlotOutline,
    llm_client: BaseChatModel | None = None,
) -> PersonaInferenceResult:
    """Infer recommended persona from plot outline (v0.8.3 strict mode).

    Args:
        plot_outline: Required. PlotOutline from upstream LLM call (already structured signal).
        llm_client: Optional. If None, uses get_llm(json_mode=True) default.

    Returns:
        PersonaInferenceResult(persona_id, confidence, reasoning).

    Raises:
        PersonaInferenceError: On any failure (invalid JSON / persona not whitelisted / API error).
    """
    if llm_client is None:
        from autoclip.providers.llm import get_llm

        llm_client = get_llm(json_mode=True, temperature=0.3, max_tokens=300)

    fields = _format_plot_outline(plot_outline)
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=USER_PROMPT.format(**fields)),
    ]

    try:
        response = llm_client.invoke(messages)
    except Exception as e:
        raise PersonaInferenceError(f"LLM API call failed: {e}") from e

    raw = response.content if hasattr(response, "content") else str(response)
    if not isinstance(raw, str):
        raw = str(raw)

    fence_match = _FENCE_PATTERN.search(raw)
    json_str = fence_match.group(1) if fence_match else raw.strip()

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise PersonaInferenceError(
            f"Invalid JSON in LLM response: {e}\nRaw (first 300): {raw[:300]}"
        ) from e

    persona_id = data.get("persona_id", "")
    if persona_id not in VALID_PERSONA_IDS:
        raise PersonaInferenceError(
            f"persona_id '{persona_id}' not in whitelist {sorted(VALID_PERSONA_IDS)}; raw={data}"
        )

    return PersonaInferenceResult(
        persona_id=persona_id,
        confidence=float(data.get("confidence", 0.5)),
        reasoning=str(data.get("reasoning", ""))[:200],  # cap to prevent prompt injection bloat
    )


def load_persona_description(persona_name: str) -> str:
    """Load persona description markdown for v0.8.4 reference-line injection.

    Args:
        persona_name: One of VALID_PERSONA_IDS (raises ValueError if not).

    Returns:
        Full markdown content of docs/personas/{persona_name}.md.
    """
    if persona_name not in VALID_PERSONA_IDS:
        raise ValueError(f"persona_name '{persona_name}' not in whitelist {sorted(VALID_PERSONA_IDS)}")
    persona_path = (
        Path(__file__).resolve().parents[3] / "docs" / "personas" / f"{persona_name}.md"
    )
    if not persona_path.exists():
        raise FileNotFoundError(f"Persona file not found: {persona_path}")
    return persona_path.read_text(encoding="utf-8")


# === v0.8.4 helpers (reference-line extraction for prompt injection) ===

# Match the unified section header in all 6 persona md files:
#   "## 真人 Reference 台词（5-10 条）"
# Capture body until next "## " heading or EOF.
_REFERENCE_SECTION_PATTERN = re.compile(
    r"##\s*真人\s*Reference\s*台词[^\n]*\n([\s\S]*?)(?=\n##\s|\Z)",
    re.MULTILINE,
)

# Match enumerated lines like:  1. "..."   2. "..."   3. "..."
# Tolerates half-width " and full-width “ ” quotes.
_REFERENCE_LINE_PATTERN = re.compile(
    r'^\s*\d+\.\s*["“](.+?)["”]\s*$',
    re.MULTILINE,
)


def extract_reference_lines(persona_md: str) -> list[str]:
    """Extract enumerated 'Reference 台词' entries from a persona markdown file.

    Used by v0.8.4 to inject persona-specific reference lines into the
    narrative_ir prompt without dumping the full md (which would include
    failure signals / offensive flags that would confuse the LLM).

    Args:
        persona_md: Full markdown content of one docs/personas/*.md file
                    (typically obtained via load_persona_description()).

    Returns:
        List of reference line strings (quotes and numbering stripped).
        Empty list if the section is missing or contains no enumerated entries
        (caller should treat this as a load failure — see Karpathy §1: do not
        silently degrade).
    """
    section_match = _REFERENCE_SECTION_PATTERN.search(persona_md)
    if not section_match:
        return []
    body = section_match.group(1)
    return [m.group(1).strip() for m in _REFERENCE_LINE_PATTERN.finditer(body)]
