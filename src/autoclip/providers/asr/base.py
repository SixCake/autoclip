"""ASRProvider abstract base + ASR data structures.

Schema aligns with `models.shot.ASRSentence` ORM (Index stage product).

References:
- design.md §6.2 (ASRSentence dataclass)
- design.md Part IV §21.1 (ADR-004 三度修订: provider impl 替换为 LocalWhisper)
- design.md Part IV §22 (ADR-009: speaker MVP 永远为 None, 走 LLM 文本推断)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ASRSentence:
    """One ASR-recognized sentence with timing.

    Field schema matches `autoclip.models.shot.ASRSentence` ORM model
    so that Index stage can persist results without conversion.

    Note:
        `speaker` is intentionally `None` in MVP (ADR-009 路径 2: 角色信息走 LLM 文本推断).
        Field reserved for future v1.1+ speaker diarization (e.g. WhisperX).
    """

    idx: int
    start_sec: float
    end_sec: float
    text: str
    confidence: float
    speaker: str | None = None

    def __post_init__(self) -> None:
        if self.idx < 0:
            raise ValueError(f"idx must be non-negative, got {self.idx}")
        if self.start_sec < 0:
            raise ValueError(f"start_sec must be non-negative, got {self.start_sec}")
        if self.end_sec < self.start_sec:
            raise ValueError(f"end_sec ({self.end_sec}) must be >= start_sec ({self.start_sec})")

    @property
    def duration_sec(self) -> float:
        return self.end_sec - self.start_sec

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ASRResult:
    """Aggregate ASR output for a single audio file."""

    sentences: list[ASRSentence] = field(default_factory=list)
    language: str = "zh"
    provider: str = ""

    @property
    def total_duration_sec(self) -> float:
        """Sum of all sentence durations (excludes silence gaps)."""
        return sum(s.duration_sec for s in self.sentences)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sentences": [s.to_dict() for s in self.sentences],
            "language": self.language,
            "provider": self.provider,
        }


class ASRProvider(ABC):
    """Abstract base for all ASR providers.

    Implementations must be safe to use across `multiprocessing` (spawn) boundaries —
    typically by lazy-loading models inside `transcribe()` rather than `__init__`.
    """

    @abstractmethod
    def transcribe(self, audio_path: Path, language: str = "zh") -> ASRResult:
        """Transcribe an audio file to a list of timestamped sentences.

        Args:
            audio_path: Local path to audio file (16kHz mono WAV recommended).
            language: ISO 639-1 language code (e.g. "zh", "en"). Default "zh".

        Returns:
            ASRResult with sentences sorted by `start_sec` ascending.

        Raises:
            FileNotFoundError: if audio_path does not exist.
            RuntimeError: on unrecoverable provider failure.
        """
        ...
