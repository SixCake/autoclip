"""Qwen-TTS provider — DashScope MultiModalConversation based synthesis.

Design notes:
- Uses `dashscope.MultiModalConversation.call(...)` non-streaming mode
  (returns an audio URL valid for 24h, downloaded immediately to local wav)
- Falls back to silent audio stub when DASHSCOPE_API_KEY not set (CI/test mode)
- Falls back to silent audio stub if API call fails after retries — never
  blocks the assembly stage on a single sentence failure
- Each sentence synthesized to tts_{sentence_idx:04d}.wav under output_dir
- Model: qwen3-tts-instruct-flash (instruct = supports `instructions` param)
- Region: 北京 (https://dashscope.aliyuncs.com/api/v1)

Reference: https://help.aliyun.com/zh/model-studio/qwen-tts
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import httpx

from .base import (
    TTSProvider,
    TTSResult,
    TTSSegment,
    create_silent_wav,
    estimate_stub_duration,
    probe_duration,
)

logger = logging.getLogger(__name__)

# Default model — instruct variant required for `instructions` param.
DEFAULT_MODEL = "qwen3-tts-instruct-flash"

# Beijing region endpoint (set on dashscope module before each call).
BEIJING_API_URL = "https://dashscope.aliyuncs.com/api/v1"

# Default voice when caller passes voice_id="default".
DEFAULT_VOICE = "Ethan"

# Default Chinese language hint — pronunciation/intonation work best when this
# matches the actual text language (we generate Chinese narration only).
DEFAULT_LANGUAGE_TYPE = "Chinese"

# Retry policy for transient API errors (network / 5xx).
_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE_SEC = 2.0

# Audio download timeout — Qwen-TTS returns small wavs (<5MB usually).
_DOWNLOAD_TIMEOUT_SEC = 30.0


class QwenTTSProvider(TTSProvider):
    """Qwen-TTS provider with DashScope SDK + stub fallback.

    Provider behavior is decided at construction time:
    - DASHSCOPE_API_KEY missing → permanent stub mode (silent wavs only)
    - DASHSCOPE_API_KEY present → live API with per-sentence retry-then-stub
    """

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        self._model = model
        self._api_key = os.environ.get("DASHSCOPE_API_KEY", "")
        self._stub_mode = not self._api_key
        if self._stub_mode:
            logger.warning(
                "QwenTTSProvider: DASHSCOPE_API_KEY not set — running in stub mode "
                "(silent audio, no API calls)"
            )
        else:
            # Configure dashscope endpoint lazily so we don't import it in stub mode.
            self._configure_dashscope()

    @property
    def name(self) -> str:
        return "qwen-tts" if not self._stub_mode else "qwen-tts-stub"

    def synthesize_batch(
        self,
        sentences: list[dict],
        output_dir: Path,
        voice_id: str = DEFAULT_VOICE,
        instructions: str | None = None,
    ) -> TTSResult:
        """Synthesize each sentence to a WAV file, in caller-provided order."""
        output_dir.mkdir(parents=True, exist_ok=True)
        # Map "default" sentinel to the real default voice id.
        effective_voice = voice_id if voice_id and voice_id != "default" else DEFAULT_VOICE

        segments: list[TTSSegment] = []
        for sentence in sentences:
            sentence_idx: int = sentence["sentence_idx"]
            text: str = sentence["text"]
            audio_path = output_dir / f"tts_{sentence_idx:04d}.wav"

            if self._stub_mode:
                duration = estimate_stub_duration(text)
                create_silent_wav(audio_path, duration)
                actual_duration = duration
                logger.debug(
                    "Stub TTS: sentence %d → %s (%.1fs)",
                    sentence_idx, audio_path, actual_duration,
                )
            else:
                actual_duration = self._synthesize_one(
                    text=text,
                    output_path=audio_path,
                    voice_id=effective_voice,
                    instructions=instructions,
                )

            segments.append(TTSSegment(
                sentence_idx=sentence_idx,
                text=text,
                audio_path=audio_path,
                actual_duration_sec=actual_duration,
            ))

        total_duration = sum(seg.actual_duration_sec for seg in segments)
        return TTSResult(segments=segments, total_duration_sec=total_duration)

    # ------------------------------------------------------------------ helpers

    def _configure_dashscope(self) -> None:
        """Set the dashscope base url to Beijing region (idempotent)."""
        import dashscope  # imported lazily to keep stub-mode dependency-free
        dashscope.base_http_api_url = BEIJING_API_URL

    def _synthesize_one(
        self,
        text: str,
        output_path: Path,
        voice_id: str,
        instructions: str | None,
    ) -> float:
        """Call Qwen-TTS for one sentence with retries; returns actual duration.

        Last-resort fallback writes a silent wav so the pipeline never aborts on
        a single-sentence failure (matches the previous Volcengine behavior).
        """
        import dashscope  # local import — see _configure_dashscope

        call_kwargs: dict = {
            "model": self._model,
            "api_key": self._api_key,
            "text": text,
            "voice": voice_id,
            "language_type": DEFAULT_LANGUAGE_TYPE,
            "stream": False,
        }
        if instructions:
            call_kwargs["instructions"] = instructions
            call_kwargs["optimize_instructions"] = True

        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = dashscope.MultiModalConversation.call(**call_kwargs)
                audio_url = self._extract_audio_url(response)
                if not audio_url:
                    raise ValueError(f"Qwen-TTS response missing audio url: {response}")
                self._download_audio(audio_url, output_path)
                return probe_duration(output_path)
            except Exception as exc:  # network / API / decode errors
                last_error = exc
                logger.warning(
                    "Qwen-TTS attempt %d/%d failed for sentence '%s...': %s",
                    attempt + 1, _MAX_RETRIES, text[:30], exc,
                )
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_RETRY_BACKOFF_BASE_SEC ** attempt)

        # All retries exhausted — write silent stub so downstream stages still run.
        logger.error(
            "Qwen-TTS failed after %d attempts — writing silent stub for: '%s...' (%s)",
            _MAX_RETRIES, text[:30], last_error,
        )
        duration = estimate_stub_duration(text)
        create_silent_wav(output_path, duration)
        return duration

    @staticmethod
    def _extract_audio_url(response: object) -> str | None:
        """Pull the audio URL out of a MultiModalConversationResult.

        DashScope returns a result whose `output.audio.url` field holds a
        24h-valid signed URL. Defensive against minor SDK shape changes.
        """
        # Prefer attribute access (SDK uses dataclass-style results).
        try:
            output = getattr(response, "output", None) or response.get("output")  # type: ignore[union-attr]
            audio = getattr(output, "audio", None) or output.get("audio")  # type: ignore[union-attr]
            url = getattr(audio, "url", None) or audio.get("url")  # type: ignore[union-attr]
            if isinstance(url, str) and url:
                return url
        except (AttributeError, TypeError, KeyError):
            pass
        return None

    @staticmethod
    def _download_audio(url: str, output_path: Path) -> None:
        """Stream-download the synthesized audio to a local file."""
        with httpx.stream("GET", url, timeout=_DOWNLOAD_TIMEOUT_SEC) as response:
            response.raise_for_status()
            with output_path.open("wb") as out_file:
                for chunk in response.iter_bytes():
                    if chunk:
                        out_file.write(chunk)
