"""Unit tests for QwenTTSProvider (Session 35: replaces VolcengineTTSProvider).

Coverage:
- Dataclasses (TTSSegment / TTSResult)
- Stub utilities (create_silent_wav / estimate_stub_duration)
- Stub mode behavior when DASHSCOPE_API_KEY is missing
- API extraction helper (_extract_audio_url) with several response shapes
- Provider name reflects stub vs live mode
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from autoclip.providers.tts.base import (
    TTSProvider,
    TTSResult,
    TTSSegment,
    create_silent_wav,
    estimate_stub_duration,
)
from autoclip.providers.tts.qwen import (
    DEFAULT_MODEL,
    DEFAULT_VOICE,
    QwenTTSProvider,
)


class TestTTSDataclasses:
    def test_tts_segment_fields(self, tmp_path: Path) -> None:
        audio = tmp_path / "test.wav"
        audio.write_bytes(b"")
        seg = TTSSegment(
            sentence_idx=1, text="hello", audio_path=audio, actual_duration_sec=2.5
        )
        assert seg.sentence_idx == 1
        assert seg.actual_duration_sec == 2.5

    def test_tts_result_total_duration(self, tmp_path: Path) -> None:
        segs = [
            TTSSegment(1, "a", tmp_path / "1.wav", 1.0),
            TTSSegment(2, "b", tmp_path / "2.wav", 2.5),
        ]
        result = TTSResult(segments=segs, total_duration_sec=3.5)
        assert result.total_duration_sec == 3.5


class TestStubHelpers:
    def test_create_silent_wav_writes_valid_file(self, tmp_path: Path) -> None:
        path = tmp_path / "silent.wav"
        create_silent_wav(path, duration_sec=1.0)
        assert path.exists()
        assert path.stat().st_size > 0

    def test_estimate_stub_duration_floor(self) -> None:
        # Empty / very short text still gets at least 1.0s floor
        assert estimate_stub_duration("") == 1.0
        assert estimate_stub_duration("一") == 1.0

    def test_estimate_stub_duration_scales_with_length(self) -> None:
        # 40 chars / 4 chars per sec = 10s
        assert estimate_stub_duration("一" * 40) == pytest.approx(10.0)


class TestQwenTTSProviderStubMode:
    def test_stub_mode_without_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without DASHSCOPE_API_KEY, provider runs in stub mode without error."""
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        provider = QwenTTSProvider()
        assert provider.name == "qwen-tts-stub"

    def test_live_mode_when_api_key_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With DASHSCOPE_API_KEY set, provider name reflects live mode."""
        monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-fake")
        provider = QwenTTSProvider()
        assert provider.name == "qwen-tts"

    def test_synthesize_batch_produces_wav_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        provider = QwenTTSProvider()
        sentences = [
            {"sentence_idx": 1, "text": "这是第一句测试"},
            {"sentence_idx": 2, "text": "这是第二句测试"},
        ]
        result = provider.synthesize_batch(sentences, tmp_path / "tts")
        assert len(result.segments) == 2
        assert result.total_duration_sec > 0
        for seg in result.segments:
            assert seg.audio_path.exists()
            assert seg.audio_path.name.startswith("tts_")
            assert seg.audio_path.suffix == ".wav"

    def test_synthesize_passes_voice_and_instructions(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Voice/instructions reach synthesize_batch even in stub mode (no error)."""
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        provider = QwenTTSProvider()
        sentences = [{"sentence_idx": 1, "text": "测试"}]
        result = provider.synthesize_batch(
            sentences,
            tmp_path / "tts",
            voice_id="Vincent",
            instructions="语速偏快，带江湖豪迈感",
        )
        assert len(result.segments) == 1

    def test_synthesize_estimates_duration_from_text(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        provider = QwenTTSProvider()
        long_text = "这" * 40  # 40 chars → ~10 sec
        sentences = [{"sentence_idx": 1, "text": long_text}]
        result = provider.synthesize_batch(sentences, tmp_path / "tts")
        assert result.segments[0].actual_duration_sec >= 5.0

    def test_synthesize_preserves_input_order(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Output order matches input order (sorting is caller's responsibility)."""
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        provider = QwenTTSProvider()
        sentences = [
            {"sentence_idx": 3, "text": "第三句"},
            {"sentence_idx": 1, "text": "第一句"},
            {"sentence_idx": 2, "text": "第二句"},
        ]
        result = provider.synthesize_batch(sentences, tmp_path / "tts")
        indices = [s.sentence_idx for s in result.segments]
        assert indices == [3, 1, 2]

    def test_provider_is_subclass_of_abc(self) -> None:
        assert issubclass(QwenTTSProvider, TTSProvider)

    def test_default_model_is_instruct_variant(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Default model must be the instruct variant (supports `instructions` param)."""
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        provider = QwenTTSProvider()
        assert provider._model == "qwen3-tts-instruct-flash"
        assert DEFAULT_MODEL == "qwen3-tts-instruct-flash"
        assert DEFAULT_VOICE == "Ethan"


class TestExtractAudioUrl:
    """The SDK returns a result object; we should be tolerant of dict/attr forms."""

    def test_attribute_form(self) -> None:
        # Mimics dashscope MultiModalConversationResult shape
        response = SimpleNamespace(
            output=SimpleNamespace(
                audio=SimpleNamespace(url="https://example.com/a.wav")
            )
        )
        assert (
            QwenTTSProvider._extract_audio_url(response)
            == "https://example.com/a.wav"
        )

    def test_dict_form(self) -> None:
        response = {"output": {"audio": {"url": "https://example.com/b.wav"}}}
        assert (
            QwenTTSProvider._extract_audio_url(response)
            == "https://example.com/b.wav"
        )

    def test_missing_url_returns_none(self) -> None:
        response = {"output": {"audio": {}}}
        assert QwenTTSProvider._extract_audio_url(response) is None

    def test_completely_invalid_response_returns_none(self) -> None:
        assert QwenTTSProvider._extract_audio_url(None) is None
        assert QwenTTSProvider._extract_audio_url({}) is None
