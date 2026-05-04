"""Local Whisper ASR provider (faster-whisper backend).

Default ASR for MVP — see design.md Part IV §21.1 (ADR-004 三度修订).

Key properties:
- Zero network: model weights cached at ~/.cache/huggingface/hub/.
- Zero credentials: works offline after first download.
- Module-level model singleton — avoids re-loading 3GB weights inside spawn subprocesses.
- VAD enabled by default — skips silent regions (~30-40% of typical movie audio).
- Fallback chain: large-v3 → medium → RuntimeError.
"""

from __future__ import annotations

from pathlib import Path

from faster_whisper import WhisperModel
from loguru import logger

from autoclip.providers.asr.base import ASRProvider, ASRResult, ASRSentence

# Module-level singleton — survives within a single process; spawn subprocesses
# will reload independently (which is fine, they need their own copy anyway).
# WhisperModel is imported at module level (not lazy) so unittest.mock.patch
# can target `autoclip.providers.asr.local_whisper.WhisperModel` reliably.
_MODEL_SINGLETON: WhisperModel | None = None
_LOADED_MODEL_SIZE: str | None = None


def _load_whisper_model(
    model_size: str,
    device: str,
    compute_type: str,
) -> WhisperModel:
    """Lazy-instantiate WhisperModel; returns cached singleton if already loaded.

    Falls back to "medium" if the requested model fails to load (typical OOM
    on low-RAM machines per R17). Re-raises as RuntimeError if both fail.
    """
    global _MODEL_SINGLETON, _LOADED_MODEL_SIZE

    if _MODEL_SINGLETON is not None and model_size == _LOADED_MODEL_SIZE:
        return _MODEL_SINGLETON

    try:
        logger.info(
            "Loading faster-whisper model: size={} device={} compute_type={}",
            model_size,
            device,
            compute_type,
        )
        model = WhisperModel(
            model_size_or_path=model_size,
            device=device,
            compute_type=compute_type,
        )
    except Exception as primary_err:
        if model_size == "medium":
            raise RuntimeError(
                f"Failed to load whisper model 'medium': {primary_err!r}"
            ) from primary_err
        logger.warning(
            "Failed to load whisper model {!r} ({!r}); falling back to 'medium'",
            model_size,
            primary_err,
        )
        try:
            model = WhisperModel(
                model_size_or_path="medium",
                device=device,
                compute_type=compute_type,
            )
            model_size = "medium"  # update tag for cache key
        except Exception as fallback_err:
            raise RuntimeError(
                f"Failed to load whisper fallback 'medium': {fallback_err!r} "
                f"(original error for {model_size!r}: {primary_err!r})"
            ) from fallback_err

    _MODEL_SINGLETON = model
    _LOADED_MODEL_SIZE = model_size
    return model


def _reset_singleton_for_tests() -> None:
    """Test helper — clear cached model so each test can re-trigger load logic."""
    global _MODEL_SINGLETON, _LOADED_MODEL_SIZE
    _MODEL_SINGLETON = None
    _LOADED_MODEL_SIZE = None


# Post-processing thresholds (design.md Part IV §21.2)
_MIN_SEGMENT_SEC = 1.0
_MIN_AVG_LOGPROB = -1.0


class LocalWhisperProvider(ASRProvider):
    """Local ASR backed by faster-whisper.

    Args:
        model_size: One of tiny / base / small / medium / large-v3. Default large-v3.
        device: "auto" (recommended) / cpu / cuda / mps.
        compute_type: "default" / int8 / float16 / float32.
        beam_size: Beam search width. Default 5 (quality/speed sweet spot).
    """

    PROVIDER_NAME = "local-whisper"

    def __init__(
        self,
        model_size: str = "large-v3",
        device: str = "auto",
        compute_type: str = "default",
        beam_size: int = 5,
    ) -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.beam_size = beam_size

    def transcribe(self, audio_path: Path, language: str = "zh") -> ASRResult:
        if not audio_path.exists():
            raise FileNotFoundError(f"audio file not found: {audio_path}")

        model = _load_whisper_model(self.model_size, self.device, self.compute_type)

        logger.info(
            "Transcribing {!s} (language={}, beam_size={}, vad=True)",
            audio_path,
            language,
            self.beam_size,
        )
        segments_iter, info = model.transcribe(
            str(audio_path),
            language=language,
            beam_size=self.beam_size,
            vad_filter=True,
            word_timestamps=False,
        )

        sentences = self._postprocess_segments(segments_iter)

        logger.info(
            "Transcription done: {} sentences, detected_language={}",
            len(sentences),
            info.language,
        )
        return ASRResult(
            sentences=sentences,
            language=info.language,
            provider=self.PROVIDER_NAME,
        )

    @staticmethod
    def _postprocess_segments(segments_iter: object) -> list[ASRSentence]:
        """Filter and reindex raw whisper segments into ASRSentences.

        Drop rules:
        1. Empty / whitespace-only text.
        2. avg_logprob < -1.0 (low-confidence noise).
        3. Duration < 1.0s when text is also < 4 chars (likely glitch).
        """
        sentences: list[ASRSentence] = []
        next_idx = 0
        for seg in segments_iter:  # type: ignore[union-attr]
            text = (seg.text or "").strip()
            if not text:
                continue

            avg_logprob = float(getattr(seg, "avg_logprob", 0.0) or 0.0)
            if avg_logprob < _MIN_AVG_LOGPROB:
                continue

            start = float(seg.start)
            end = float(seg.end)
            if end - start < _MIN_SEGMENT_SEC and len(text) < 4:
                continue

            sentences.append(
                ASRSentence(
                    idx=next_idx,
                    start_sec=start,
                    end_sec=end,
                    text=text,
                    confidence=avg_logprob,
                    speaker=None,  # ADR-009 路径2: MVP 不做声纹
                )
            )
            next_idx += 1
        return sentences
