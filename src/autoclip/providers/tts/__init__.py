"""TTS provider package."""

from .base import TTSProvider, TTSResult, TTSSegment
from .volcengine import VolcengineTTSProvider

__all__ = ["TTSProvider", "TTSResult", "TTSSegment", "VolcengineTTSProvider"]
