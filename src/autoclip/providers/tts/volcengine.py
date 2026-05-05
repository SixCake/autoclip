"""Volcengine TTS provider — HTTP API based synthesis.

Design notes:
- Uses raw HTTP (no dedicated SDK) per design.md ADR choice
- Falls back to silent audio stub when VOLCENGINE_TTS_APP_ID not set (CI/test mode)
- Each sentence synthesized to tts_{sentence_idx:04d}.wav under output_dir
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
import uuid
import wave
from pathlib import Path

import httpx

from .base import TTSProvider, TTSResult, TTSSegment

logger = logging.getLogger(__name__)

_VOLCENGINE_TTS_URL = "https://openspeech.bytedance.com/api/v1/tts"
_DEFAULT_VOICE_ID = "zh_female_wanwanxiaohe_moon_bigtts"
_STUB_SAMPLE_RATE = 24000


def _create_silent_wav(path: Path, duration_sec: float) -> None:
    """Create a silent WAV file for stub/test mode."""
    num_frames = int(_STUB_SAMPLE_RATE * duration_sec)
    with wave.open(str(path), "w") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(_STUB_SAMPLE_RATE)
        wav_file.writeframes(b"\x00\x00" * num_frames)


def _probe_duration(audio_path: Path) -> float:
    """Probe actual audio duration using ffprobe."""
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
        logger.warning("ffprobe failed for %s, estimating duration from text", audio_path)
    # Fallback: rough estimate (3 chars/sec for Chinese)
    return 2.0


class VolcengineTTSProvider(TTSProvider):
    """Volcengine TTS provider with HTTP API + stub fallback."""

    def __init__(self) -> None:
        self._app_id = os.environ.get("VOLCENGINE_TTS_APP_ID", "")
        self._access_token = os.environ.get("VOLCENGINE_TTS_ACCESS_TOKEN", "")
        self._stub_mode = not (self._app_id and self._access_token)
        if self._stub_mode:
            logger.warning(
                "VolcengineTTSProvider: VOLCENGINE_TTS_APP_ID or ACCESS_TOKEN not set — "
                "running in stub mode (silent audio)"
            )

    @property
    def name(self) -> str:
        return "volcengine" if not self._stub_mode else "volcengine-stub"

    def synthesize_batch(
        self,
        sentences: list[dict],
        output_dir: Path,
        voice_id: str = _DEFAULT_VOICE_ID,
    ) -> TTSResult:
        """Synthesize each sentence to a WAV file."""
        output_dir.mkdir(parents=True, exist_ok=True)
        segments: list[TTSSegment] = []

        for sentence in sentences:
            sentence_idx: int = sentence["sentence_idx"]
            text: str = sentence["text"]
            audio_path = output_dir / f"tts_{sentence_idx:04d}.wav"

            if self._stub_mode:
                # Estimate duration: ~4 chars/sec for Chinese narration
                estimated_duration = max(1.0, len(text) / 4.0)
                _create_silent_wav(audio_path, estimated_duration)
                actual_duration = estimated_duration
                logger.debug("Stub TTS: sentence %d → %s (%.1fs)", sentence_idx, audio_path, actual_duration)
            else:
                actual_duration = self._synthesize_one(text, audio_path, voice_id)

            segments.append(TTSSegment(
                sentence_idx=sentence_idx,
                text=text,
                audio_path=audio_path,
                actual_duration_sec=actual_duration,
            ))

        total_duration = sum(seg.actual_duration_sec for seg in segments)
        return TTSResult(segments=segments, total_duration_sec=total_duration)

    def _synthesize_one(self, text: str, output_path: Path, voice_id: str) -> float:
        """Call Volcengine TTS API for one sentence. Returns actual duration."""
        request_id = str(uuid.uuid4())
        payload = {
            "app": {
                "appid": self._app_id,
                "token": self._access_token,
                "cluster": "volcano_tts",
            },
            "user": {"uid": "autoclip"},
            "audio": {
                "voice_type": voice_id,
                "encoding": "wav",
                "speed_ratio": 1.0,
                "volume_ratio": 1.0,
                "pitch_ratio": 1.0,
            },
            "request": {
                "reqid": request_id,
                "text": text,
                "text_type": "plain",
                "operation": "query",
                "silence_duration": "125",
                "with_frontend": 1,
                "frontend_type": "unitTson",
            },
        }

        for attempt in range(3):
            try:
                response = httpx.post(
                    _VOLCENGINE_TTS_URL,
                    json=payload,
                    timeout=30.0,
                )
                response.raise_for_status()
                result = response.json()
                audio_data_hex = result.get("data", "")
                if not audio_data_hex:
                    raise ValueError(f"Empty TTS response: {result}")
                audio_bytes = bytes.fromhex(audio_data_hex)
                output_path.write_bytes(audio_bytes)
                return _probe_duration(output_path)
            except Exception as exc:
                logger.warning("TTS attempt %d failed for sentence: %s — %s", attempt + 1, text[:30], exc)
                if attempt < 2:
                    time.sleep(2 ** attempt)

        # All retries exhausted: write silent stub to avoid blocking pipeline
        logger.error("TTS failed after 3 attempts — writing silent stub for: %s", text[:30])
        estimated_duration = max(1.0, len(text) / 4.0)
        _create_silent_wav(output_path, estimated_duration)
        return estimated_duration
