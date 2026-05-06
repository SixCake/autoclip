"""Build natural-language `instructions` for Qwen-TTS instruct models.

Strategy: combine a persona-level base description (音色性格基线) with a
style-preset overlay (内容风格修饰). The persona axis answers "this voice is
who", the style axis answers "this voice is doing what right now".

Length budget: Qwen-TTS instructions cap is 1600 tokens; our templates stay
well under 100 Chinese chars each so concatenation is always safe.

Design notes:
- Templates are Chinese (Qwen-TTS instructions support 中文/English only)
- Unknown persona_id / style_preset → silent fallback to DEFAULT templates
  (instructions are advisory; never raise)
"""

from __future__ import annotations

# Persona-level base description: matches docs/personas/{id}.md character.
# Each line is a self-contained instruction sentence.
_PERSONA_INSTRUCTIONS: dict[str, str] = {
    "archaeologist": (
        "语速中等偏慢，吐字清晰，语气平稳沉着，"
        "像一位讲学的学者在层层揭开历史谜题。"
    ),
    "empathy_senior": (
        "语速中等，音调温柔但带知性，"
        "像一位年长几岁的学姐在耐心地分析与共情。"
    ),
    "healing_big_sister": (
        "语速偏慢，音调温柔甜美，气息绵长舒缓，"
        "像贴心的大姐姐在治愈地陪伴。"
    ),
    "rage_brother": (
        "语速偏快，音量略高，带有明显的情绪起伏与江湖豪迈感，"
        "像一位仗义执言的老哥在激动地点评。"
    ),
    "sarcastic_gen_z": (
        "语速偏快，音调带俏皮的上扬，时不时拖长尾音，"
        "像一位嘴贱的 Z 世代朋友在调侃吐槽。"
    ),
    "toxic_middle_aged": (
        "语速中等，语气低沉冷峻，带有看透世事的从容，"
        "毒舌但不咆哮，像一位阅历丰富的中年人在冷笑话式点评。"
    ),
}

# Style-preset overlay: applied on top of persona base. Empty string for default.
_STYLE_OVERLAYS: dict[str, str] = {
    "default": "",
    "humor_roast": "整体节奏更快一些，重音更鲜明，带出俏皮和锐利的吐槽感。",
    "serious_review": "整体放缓节奏，重音更稳重，带出客观和深度分析的质感。",
}

# Used when persona_id resolves to fallback voice (Ethan), so instructions
# stay coherent with a neutral aural personality.
_DEFAULT_PERSONA_INSTRUCTION = (
    "语速中等，音调自然温暖，吐字清晰，"
    "像一位友好的解说员在平和地讲述。"
)


def build_instructions(
    persona_id: str | None,
    style_preset: str | None = None,
) -> str:
    """Compose Qwen-TTS instruction string from persona + style signals.

    Both arguments are tolerant: unknown / None / empty values fall back to
    sensible defaults. Returned string is always non-empty so callers can
    pass it through unconditionally.
    """
    persona_part = _PERSONA_INSTRUCTIONS.get(
        persona_id or "",
        _DEFAULT_PERSONA_INSTRUCTION,
    )
    style_part = _STYLE_OVERLAYS.get(style_preset or "default", "")
    if style_part:
        return f"{persona_part} {style_part}"
    return persona_part
