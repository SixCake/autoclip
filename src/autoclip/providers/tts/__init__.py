"""TTS provider package.

Session 35: switched from Volcengine to Qwen-TTS (qwen3-tts-instruct-flash).
See `voice_map.py` and `instructions.py` for the persona ↔ voice matching layer.
"""

from .base import TTSProvider, TTSResult, TTSSegment
from .instructions import build_instructions
from .qwen import QwenTTSProvider
from .voice_map import DEFAULT_VOICE, PERSONA_TO_VOICE, VOICE_DISPLAY_NAMES, select_voice

__all__ = [
    "TTSProvider",
    "TTSResult",
    "TTSSegment",
    "QwenTTSProvider",
    "build_instructions",
    "select_voice",
    "PERSONA_TO_VOICE",
    "DEFAULT_VOICE",
    "VOICE_DISPLAY_NAMES",
]
