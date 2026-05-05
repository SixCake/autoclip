"""Hook Generator (v0.8.5 — Stage1 LLM for opening hook candidates).

v0.8.5 brainstorming decisions:
    - Q1=A: standalone 4th LLM call (not folded into narrative_ir or persona)
    - Q2.1=B: 3-5 floating candidates; each = {text, style_tag, score}
    - Q2.2=whitelist: VALID_STYLE_TAGS frozenset of 6 types
    - Q2.3=keep score: 0.0-1.0 float (LLM self-assessed; calibrated in v0.8.7 review)
    - Q3.A=B: input = plot_outline + recommended_persona + narrative_ir.paragraphs[0]
    - Q3.B=degrade: on any failure, fall back to a single candidate built from
                    narrative_ir.paragraphs[0].sentences[0].text (do NOT block pipeline);
                    HookCandidatesResult.degraded=True flags this for v0.8.7 review.

Output: HookCandidatesResult(candidates: list[HookCandidate], degraded: bool, degrade_reason: str)

See docs/plans/tasks/M2a-fix-narrative-style.md §v0.8.5 for brainstorming history.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from autoclip.algo.narrative_ir import NarrativeIR, PlotOutline
    from autoclip.algo.persona_inferer import PersonaInferenceResult


# === Constants ===

# Q2.2 whitelist: 6 types of opening hook style tags. Any tag outside this set triggers degrade.
VALID_STYLE_TAGS: frozenset[str] = frozenset(
    {
        "反套路问句",  # 用反常识问题勾起好奇 (e.g., "为什么没人发现这个 bug?")
        "数字冲击",    # 用具体数字制造惊讶感 (e.g., "3 秒钟，他做了 5 个错误决定")
        "反差对比",    # 制造预期与现实的强对比 (e.g., "号称儿童片，实际...")
        "悬念伏笔",    # 抛出未解之谜引诱继续看 (e.g., "结局会推翻所有人的猜测")
        "情绪共振",    # 直接戳中观众情绪 (e.g., "看完想哭的瞬间")
        "其他",        # degrade fallback 占位 / LLM 真的找不到合适标签时
    }
)

# Min/max candidate count (Q2.1=B "3-5 floating"). Less than MIN triggers degrade.
MIN_CANDIDATES = 3
MAX_CANDIDATES = 5

# Strip ```json ... ``` fences if LLM wraps output (DeepSeek json_mode usually clean, but be safe)
_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


# === Exceptions ===


class HookGenerationError(RuntimeError):
    """Internal error inside hook generation (caught by generate_hook_candidates and converted
    to a degraded HookCandidatesResult per Q3.B brainstorming decision — never propagated up).

    Distinguish from PersonaInferenceError (strict mode): hooks are nice-to-have downstream
    of narrative_ir; failing them must NOT crash the scripting stage.
    """


# === Data Models ===


@dataclass(frozen=True)
class HookCandidate:
    """A single opening hook candidate for v0.8.7 review and (future) UI selection."""

    text: str          # 钩子句正文，≤120 字
    style_tag: str     # Must be one of VALID_STYLE_TAGS
    score: float       # 0.0 - 1.0, LLM self-assessed quality


@dataclass(frozen=True)
class HookCandidatesResult:
    """Output of generate_hook_candidates() — list of candidates + degrade telemetry."""

    candidates: list[HookCandidate] = field(default_factory=list)
    degraded: bool = False           # True if Q3.B fallback was triggered
    degrade_reason: str = ""         # Empty on success; short reason string on degrade


# === Prompts ===

SYSTEM_PROMPT = """你是 B 站二创解说短视频的钩子句策略师。你的任务：基于剧情大纲、推荐人格、正文第一段，
产出 3-5 个不同风格的开场钩子候选，让用户/UP 主从中挑最合适的。

【钩子价值】钩子是短视频前 3-5 秒的核心，决定划走率。好钩子 = 高密度信息 + 反套路 + 让人想知道下一句。

【style_tag 白名单（必须严格匹配）】
- 反套路问句：用反常识问题勾起好奇
- 数字冲击：用具体数字制造惊讶感
- 反差对比：制造预期与现实的强对比
- 悬念伏笔：抛出未解之谜引诱继续看
- 情绪共振：直接戳中观众情绪
- 其他：以上都不准确时使用（尽量避免）

【输出要求】
1. 必须 3-5 个候选，多样化覆盖不同风格（不要 5 个都用同一个 style_tag）
2. 每个候选 ≤120 字
3. score 是你自评质量，0.0-1.0 浮点数（不要全部给 0.9，要有区分度）
4. 风格必须与「推荐人格」匹配（毒舌型不要写治愈，治愈型不要写毒舌）
5. 可以参考「正文第一段」的风格但不要照抄
6. 严格 JSON 输出，不要任何解释文字

【输出 JSON schema】
{
  "candidates": [
    {"text": "<钩子句>", "style_tag": "<必须是白名单 6 个之一>", "score": <0.0-1.0>},
    ...
  ]
}
"""

USER_PROMPT = """剧情大纲：
- 标题猜测：{title_guess}
- 题材：{genre}
- 主要角色：{characters_brief}
- 剧情概要：{plot_summary}

推荐人格：{persona_id}
人格选择理由：{persona_reasoning}

正文第一段（参考其风格，但请重新创作钩子）：
{first_paragraph_text}

请输出 3-5 个钩子候选 JSON。
"""


# === Internal helpers ===


def _format_inputs(
    plot_outline: PlotOutline,
    persona_result: PersonaInferenceResult,
    narrative_ir: NarrativeIR,
) -> dict[str, str]:
    """Format 3 input objects into prompt fields. All values are short strings (no nested JSON)."""
    characters_brief = (
        "; ".join(f"{c.role}({c.name or '?'}): {c.description}" for c in plot_outline.main_characters)
        or "（无）"
    )
    # Q3.A=B: 注入 narrative_ir.paragraphs[0] 全部句子（让 LLM 看到正文风格）
    if narrative_ir.paragraphs:
        first_para = narrative_ir.paragraphs[0]
        first_paragraph_text = "\n".join(
            f"{i + 1}. {s.text}" for i, s in enumerate(first_para.sentences)
        ) or "（空）"
    else:
        first_paragraph_text = "（无 paragraphs）"

    return {
        "title_guess": plot_outline.title_guess or "（未命名）",
        "genre": plot_outline.genre or "（未知）",
        "characters_brief": characters_brief,
        "plot_summary": plot_outline.plot_summary or "（无）",
        "persona_id": persona_result.persona_id,
        "persona_reasoning": persona_result.reasoning or "（无）",
        "first_paragraph_text": first_paragraph_text,
    }


def _validate_and_parse(raw: str) -> list[HookCandidate]:
    """Parse LLM raw output into validated HookCandidate list. Raises HookGenerationError
    on any schema violation (caller catches and degrades per Q3.B)."""
    fence_match = _FENCE_PATTERN.search(raw)
    json_str = fence_match.group(1) if fence_match else raw.strip()

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise HookGenerationError(
            f"Invalid JSON in LLM response: {e}\nRaw (first 300): {raw[:300]}"
        ) from e

    candidates_raw = data.get("candidates")
    if not isinstance(candidates_raw, list):
        raise HookGenerationError(
            f"Missing or invalid 'candidates' list in LLM response; got {type(candidates_raw).__name__}"
        )

    if not (MIN_CANDIDATES <= len(candidates_raw) <= MAX_CANDIDATES):
        raise HookGenerationError(
            f"Candidate count {len(candidates_raw)} not in [{MIN_CANDIDATES}, {MAX_CANDIDATES}]"
        )

    candidates: list[HookCandidate] = []
    for idx, item in enumerate(candidates_raw):
        if not isinstance(item, dict):
            raise HookGenerationError(f"Candidate {idx} is not a dict; got {type(item).__name__}")
        text = item.get("text", "")
        style_tag = item.get("style_tag", "")
        score = item.get("score", 0.0)

        if not isinstance(text, str) or not text.strip():
            raise HookGenerationError(f"Candidate {idx} has empty/invalid text")
        if style_tag not in VALID_STYLE_TAGS:
            raise HookGenerationError(
                f"Candidate {idx} style_tag {style_tag!r} not in whitelist {sorted(VALID_STYLE_TAGS)}"
            )
        try:
            score_f = float(score)
        except (TypeError, ValueError) as e:
            raise HookGenerationError(f"Candidate {idx} score {score!r} not a float") from e
        if not (0.0 <= score_f <= 1.0):
            raise HookGenerationError(f"Candidate {idx} score {score_f} not in [0.0, 1.0]")

        candidates.append(HookCandidate(text=text.strip()[:120], style_tag=style_tag, score=score_f))

    return candidates


def _degrade_with_fallback(narrative_ir: NarrativeIR, reason: str) -> HookCandidatesResult:
    """Q3.B degrade path: build a single candidate from narrative_ir.paragraphs[0].sentences[0]
    so timeline.json always has hook_candidates field (≥1 entry)."""
    logger.warning("[hook_generator] degrade triggered — reason: {}", reason)
    fallback_text = ""
    if narrative_ir.paragraphs and narrative_ir.paragraphs[0].sentences:
        fallback_text = narrative_ir.paragraphs[0].sentences[0].text or ""
    if not fallback_text:
        fallback_text = "（无可用钩子）"  # last-resort placeholder; should never happen in practice
    return HookCandidatesResult(
        candidates=[HookCandidate(text=fallback_text[:120], style_tag="其他", score=0.5)],
        degraded=True,
        degrade_reason=reason[:200],  # cap to keep timeline.json compact
    )


# === Core entry ===


def generate_hook_candidates(
    plot_outline: PlotOutline,
    persona_result: PersonaInferenceResult,
    narrative_ir: NarrativeIR,
    llm_client: BaseChatModel | None = None,
) -> HookCandidatesResult:
    """Generate 3-5 opening hook candidates for v0.8.5 timeline.json field.

    Q3.B contract: this function NEVER raises. On any failure (LLM API error,
    invalid JSON, schema violation, count out of range, tag not whitelisted, score out of
    range), returns a degraded HookCandidatesResult with a single fallback candidate built
    from narrative_ir.paragraphs[0].sentences[0].text + degraded=True flag.

    Args:
        plot_outline: PlotOutline from upstream Step 2 LLM call.
        persona_result: PersonaInferenceResult from upstream Step 2.5 (v0.8.4) LLM call.
        narrative_ir: NarrativeIR from upstream Step 3 LLM call (Q3.A=B: pass paragraphs[0]).
        llm_client: Optional. If None, uses get_llm(json_mode=True, temperature=0.8, max_tokens=600).

    Returns:
        HookCandidatesResult — always has ≥1 candidate; degraded flag indicates fallback used.
    """
    if llm_client is None:
        from autoclip.providers.llm import get_llm

        llm_client = get_llm(json_mode=True, temperature=0.8, max_tokens=600)

    fields = _format_inputs(plot_outline, persona_result, narrative_ir)
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=USER_PROMPT.format(**fields)),
    ]

    # Per Q3.B: catch ALL failure modes; never propagate
    try:
        response = llm_client.invoke(messages)
    except Exception as e:
        return _degrade_with_fallback(narrative_ir, f"LLM API call failed: {e}")

    raw = response.content if hasattr(response, "content") else str(response)
    if not isinstance(raw, str):
        raw = str(raw)

    try:
        candidates = _validate_and_parse(raw)
    except HookGenerationError as e:
        return _degrade_with_fallback(narrative_ir, str(e))

    return HookCandidatesResult(candidates=candidates, degraded=False, degrade_reason="")
