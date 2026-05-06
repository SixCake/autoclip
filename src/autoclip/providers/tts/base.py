"""TTS provider base class — abstract interface for text-to-speech synthesis.

Shared utilities (silent-wav stub + ffprobe duration) live at module level so
every concrete provider can reuse them without subclassing tricks.
"""

from __future__ import annotations

import json
import logging
import subprocess
import wave
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Stub WAV constants — kept conservative to match Qwen-TTS pcm sample rate
_STUB_SAMPLE_RATE = 24000
_STUB_CHARS_PER_SEC = 4.0  # rough Chinese narration speed estimate


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


def create_silent_wav(path: Path, duration_sec: float) -> None:
    """Create a 16-bit mono silent WAV file.

    Used by both stub mode (no API key) and last-resort fallback (API failure)
    so that a missing TTS chunk never blocks the downstream assembly stage.
    """
    num_frames = int(_STUB_SAMPLE_RATE * duration_sec)
    with wave.open(str(path), "w") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(_STUB_SAMPLE_RATE)
        wav_file.writeframes(b"\x00\x00" * num_frames)


def estimate_stub_duration(text: str) -> float:
    """Estimate playback duration for stub-mode wav (>=1 second floor)."""
    return max(1.0, len(text) / _STUB_CHARS_PER_SEC)


def probe_duration(audio_path: Path) -> float:
    """Probe actual audio duration with ffprobe; fall back to size-based estimate."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_streams", str(audio_path),
            ],
            capture_output=True, text=True, timeout=10,
        )
        data = json.loads(result.stdout)
        for stream in data.get("streams", []):
            if stream.get("duration"):
                return float(stream["duration"])
    except Exception:
        logger.warning("ffprobe failed for %s, falling back to size-based estimate", audio_path)
    # Rough fallback: assume 24kHz mono 16-bit
    try:
        size_bytes = audio_path.stat().st_size
        return max(0.1, size_bytes / (_STUB_SAMPLE_RATE * 2))
    except OSError:
        return 1.0


class TTSProvider(ABC):
    """Abstract TTS provider — synthesize a list of sentences to audio files."""

    @abstractmethod
    def synthesize_batch(
        self,
        sentences: list[dict],   # list of {sentence_idx, text}
        output_dir: Path,
        voice_id: str = "default",
        instructions: str | None = None,
    ) -> TTSResult:
        """Synthesize each sentence and write audio files under output_dir.

        Args:
            sentences: Ordered list of sentence dicts with 'sentence_idx' and 'text'.
            output_dir: Directory to write per-sentence audio files.
            voice_id: Provider-specific voice identifier.
            instructions: Natural-language style instructions (Qwen-TTS instruct
                models only). Providers that do not support instructions should
                silently ignore this argument.

        Returns:
            TTSResult with a TTSSegment per sentence, in caller-provided order.
        """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider name for logging."""
