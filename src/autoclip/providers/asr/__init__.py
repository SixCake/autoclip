"""ASR (Automatic Speech Recognition) provider package.

MVP default: LocalWhisperProvider (faster-whisper + large-v3, design.md Part IV §21.1).
"""

from autoclip.providers.asr.base import ASRProvider, ASRResult, ASRSentence

__all__ = ["ASRProvider", "ASRResult", "ASRSentence"]
