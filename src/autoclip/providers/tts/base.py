"""TTS provider base class — abstract interface for text-to-speech synthesis."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TTSSegment:
    """Result of synthesizing one sentence."""

    sentence_idx: int
    text: str
    audio_path: Path        # absolute path to synthesized wav/mp3
    actual_duration_sec: float  # measured via ffprobe after synthesis


@dataclass
class TTSResult:
    """Aggregate result of batch TTS synthesis for one assembly job."""

    segments: list[TTSSegment]
    total_duration_sec: float   # sum of actual_duration_sec


class TTSProvider(ABC):
    """Abstract TTS provider — synthesize a list of sentences to audio files."""

    @abstractmethod
    def synthesize_batch(
        self,
        sentences: list[dict],   # list of {sentence_idx, text}
        output_dir: Path,
        voice_id: str = "default",
    ) -> TTSResult:
        """Synthesize each sentence and write audio files under output_dir.

        Args:
            sentences: Ordered list of sentence dicts with 'sentence_idx' and 'text'.
            output_dir: Directory to write per-sentence audio files.
            voice_id: Provider-specific voice identifier.

        Returns:
            TTSResult with a TTSSegment per sentence, sorted by sentence_idx.
        """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider name for logging."""
