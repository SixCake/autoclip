"""Unit tests for persona → voice mapping (Session 35).

Validates:
- All 6 personas in VALID_PERSONA_IDS have a voice mapping (whitelist alignment)
- select_voice() returns DEFAULT_VOICE for unknown / None / empty input
- select_voice() returns the mapped voice for a known persona
- VOICE_DISPLAY_NAMES covers every voice we map to (audit/log readability)
"""

from __future__ import annotations

from autoclip.algo.persona_inferer import VALID_PERSONA_IDS
from autoclip.providers.tts.voice_map import (
    DEFAULT_VOICE,
    PERSONA_TO_VOICE,
    VOICE_DISPLAY_NAMES,
    select_voice,
)


class TestPersonaWhitelistAlignment:
    """Mapping must cover every persona that scripting may emit."""

    def test_every_persona_has_a_voice(self) -> None:
        missing = VALID_PERSONA_IDS - PERSONA_TO_VOICE.keys()
        assert not missing, f"Persona without voice mapping: {missing}"

    def test_no_extra_personas_in_mapping(self) -> None:
        """Mapping must not contain ids that scripting would never emit."""
        extra = PERSONA_TO_VOICE.keys() - VALID_PERSONA_IDS
        assert not extra, f"Mapping contains unknown persona ids: {extra}"


class TestVoiceDisplayNames:
    def test_every_mapped_voice_has_display_name(self) -> None:
        """All target voices (incl. fallback) must have a display name for logs."""
        for voice in PERSONA_TO_VOICE.values():
            assert voice in VOICE_DISPLAY_NAMES, (
                f"Voice {voice!r} missing from VOICE_DISPLAY_NAMES"
            )
        assert DEFAULT_VOICE in VOICE_DISPLAY_NAMES


class TestSelectVoice:
    def test_known_persona_returns_mapped_voice(self) -> None:
        assert select_voice("rage_brother") == "Vincent"
        assert select_voice("healing_big_sister") == "Seren"
        assert select_voice("archaeologist") == "Elias"

    def test_none_returns_default(self) -> None:
        assert select_voice(None) == DEFAULT_VOICE

    def test_empty_string_returns_default(self) -> None:
        assert select_voice("") == DEFAULT_VOICE

    def test_unknown_persona_returns_default(self) -> None:
        assert select_voice("not_a_real_persona") == DEFAULT_VOICE

    def test_default_voice_is_ethan(self) -> None:
        """Anchored test: changing DEFAULT_VOICE is a deliberate decision."""
        assert DEFAULT_VOICE == "Ethan"

    def test_select_voice_never_raises(self) -> None:
        """Voice selection must NOT block the assembly stage on bad input."""
        for bad_input in [None, "", "x", " ", "INVALID"]:
            select_voice(bad_input)  # must not raise
