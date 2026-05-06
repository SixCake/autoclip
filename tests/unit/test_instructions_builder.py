"""Unit tests for build_instructions() — Qwen-TTS persona+style instruction composer.

Covers (Session 35):
- All 6 personas produce non-empty Chinese instructions
- Unknown / None persona falls back to default neutral instruction
- Style overlay is appended for known styles (humor_roast / serious_review)
- Unknown / None / 'default' style is a no-op (returns persona base only)
- Token budget: each composed instruction stays well under Qwen-TTS 1600-token cap
"""

from __future__ import annotations

import pytest

from autoclip.algo.persona_inferer import VALID_PERSONA_IDS
from autoclip.providers.tts.instructions import build_instructions

# Loose char cap — 1 Chinese char ≈ 1-2 tokens; 400 chars is far under the
# Qwen-TTS 1600-token budget but tight enough to catch accidental bloat.
_INSTRUCTION_CHAR_CAP = 400


class TestPersonaCoverage:
    @pytest.mark.parametrize("persona_id", sorted(VALID_PERSONA_IDS))
    def test_every_persona_has_non_empty_instruction(self, persona_id: str) -> None:
        result = build_instructions(persona_id)
        assert result, f"Persona {persona_id!r} produced empty instruction"
        assert len(result) <= _INSTRUCTION_CHAR_CAP

    def test_unknown_persona_returns_default(self) -> None:
        result = build_instructions("not_a_real_persona")
        assert result  # non-empty default
        # default fallback must mention "解说员" to confirm it's the neutral template
        assert "解说" in result or "自然" in result

    def test_none_persona_returns_default(self) -> None:
        assert build_instructions(None) == build_instructions("not_a_real_persona")

    def test_empty_persona_returns_default(self) -> None:
        assert build_instructions("") == build_instructions(None)


class TestStyleOverlay:
    def test_humor_roast_appends_overlay(self) -> None:
        base = build_instructions("rage_brother", "default")
        boosted = build_instructions("rage_brother", "humor_roast")
        assert len(boosted) > len(base)
        assert "俏皮" in boosted or "锐利" in boosted

    def test_serious_review_appends_overlay(self) -> None:
        base = build_instructions("archaeologist", "default")
        boosted = build_instructions("archaeologist", "serious_review")
        assert len(boosted) > len(base)
        assert "客观" in boosted or "深度" in boosted

    def test_default_style_is_noop(self) -> None:
        assert build_instructions("empathy_senior", "default") == build_instructions(
            "empathy_senior"
        )

    def test_unknown_style_is_noop(self) -> None:
        assert build_instructions("empathy_senior", "weird_style") == build_instructions(
            "empathy_senior", "default"
        )

    def test_none_style_is_noop(self) -> None:
        assert build_instructions("empathy_senior", None) == build_instructions(
            "empathy_senior", "default"
        )


class TestTokenBudget:
    """Worst-case persona + style combinations must stay under the char cap."""

    @pytest.mark.parametrize("persona_id", sorted(VALID_PERSONA_IDS))
    @pytest.mark.parametrize("style", ["default", "humor_roast", "serious_review"])
    def test_worst_case_stays_under_cap(self, persona_id: str, style: str) -> None:
        composed = build_instructions(persona_id, style)
        assert len(composed) <= _INSTRUCTION_CHAR_CAP, (
            f"persona={persona_id} style={style} produced "
            f"{len(composed)} chars (cap {_INSTRUCTION_CHAR_CAP})"
        )


class TestDoesNotRaise:
    def test_all_combinations_are_safe(self) -> None:
        """No combination of persona + style should ever raise."""
        for persona in [*VALID_PERSONA_IDS, None, "", "garbage"]:
            for style in [None, "", "default", "humor_roast", "serious_review", "x"]:
                build_instructions(persona, style)  # must not raise
