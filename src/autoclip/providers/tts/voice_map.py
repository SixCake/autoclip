"""Persona → Qwen-TTS voice id mapping (Session 35).

Design decision: 1:1 fixed mapping (NOT dynamic per-job LLM selection) so the
sound of any given persona stays consistent across videos — predictable,
auditable, and trivial to A/B-tune by editing one line.

Whitelist alignment:
- Persona ids match `src/autoclip/algo/persona_inferer.py` VALID_PERSONA_IDS
- Voice ids match Qwen-TTS qwen3-tts-instruct-flash supported voices
  (see https://help.aliyun.com/zh/model-studio/qwen-tts §支持的系统音色)

Editing this map is the primary tuning surface for "voice ↔ content matching".
Any change to this file should be paired with a regenerated demo wav set.
"""

from __future__ import annotations

# Voice id => human-readable Chinese name (for logging/audit only)
VOICE_DISPLAY_NAMES: dict[str, str] = {
    "Elias": "墨讲师",
    "Maia": "四月",
    "Seren": "小婉",
    "Vincent": "田叔",
    "Vivian": "十三",
    "Eldric Sage": "沧明子",
    "Ethan": "晨煦",  # fallback
}

# Persona id => Qwen-TTS voice id
# See docs/personas/{persona_id}.md for character descriptions.
PERSONA_TO_VOICE: dict[str, str] = {
    "archaeologist": "Elias",          # 墨讲师 — 学科严谨 + 叙事化讲解
    "empathy_senior": "Maia",          # 四月 — 知性与温柔的碰撞
    "healing_big_sister": "Seren",     # 小婉 — 治愈舒缓助眠声线
    "rage_brother": "Vincent",         # 田叔 — 沙哑烟嗓 + 江湖豪情
    "sarcastic_gen_z": "Vivian",       # 十三 — 拽拽的 + 可爱小暴躁
    "toxic_middle_aged": "Eldric Sage",  # 沧明子 — 沧桑睿智 + 看透世事
}

# Fallback when persona inference fails or persona_id is unknown.
# Picked Ethan (阳光暖男) as a safe neutral default — works for most narration.
DEFAULT_VOICE: str = "Ethan"


def select_voice(persona_id: str | None) -> str:
    """Resolve a persona id to a Qwen-TTS voice id.

    Returns DEFAULT_VOICE when persona_id is None, empty, or not in the
    whitelist. Never raises — voice selection must not block the assembly stage.
    """
    if not persona_id:
        return DEFAULT_VOICE
    return PERSONA_TO_VOICE.get(persona_id, DEFAULT_VOICE)
