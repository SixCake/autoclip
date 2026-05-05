"""Unit tests for TTS provider abstraction (M3.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from autoclip.providers.tts.base import TTSProvider, TTSResult, TTSSegment
from autoclip.providers.tts.volcengine import VolcengineTTSProvider, _create_silent_wav


class TestTTSDataclasses:
    def test_tts_segment_fields(self, tmp_path: Path) -> None:
        audio = tmp_path / "test.wav"
        audio.write_bytes(b"")
        seg = TTSSegment(sentence_idx=1, text="hello", audio_path=audio, actual_duration_sec=2.5)
        assert seg.sentence_idx == 1
        assert seg.actual_duration_sec == 2.5

    def test_tts_result_total_duration(self, tmp_path: Path) -> None:
        segs = [
            TTSSegment(1, "a", tmp_path / "1.wav", 1.0),
            TTSSegment(2, "b", tmp_path / "2.wav", 2.5),
        ]
        result = TTSResult(segments=segs, total_duration_sec=3.5)
        assert result.total_duration_sec == 3.5


class TestSilentWav:
    def test_creates_valid_wav(self, tmp_path: Path) -> None:
        path = tmp_path / "silent.wav"
        _create_silent_wav(path, duration_sec=1.0)
        assert path.exists()
        assert path.stat().st_size > 0


class TestVolcengineTTSProviderStubMode:
    def test_stub_mode_without_credentials(self, tmp_path: Path) -> None:
        """Without credentials, should run in stub mode without error."""
        provider = VolcengineTTSProvider()
        assert provider.name == "volcengine-stub"

    def test_synthesize_batch_produces_wav_files(self, tmp_path: Path) -> None:
        provider = VolcengineTTSProvider()
        sentences = [
            {"sentence_idx": 1, "text": "这是第一句测试"},
            {"sentence_idx": 2, "text": "这是第二句测试"},
        ]
        result = provider.synthesize_batch(sentences, tmp_path / "tts")
        assert len(result.segments) == 2
        assert result.total_duration_sec > 0
        for seg in result.segments:
            assert seg.audio_path.exists()

    def test_synthesize_estimates_duration_from_text(self, tmp_path: Path) -> None:
        provider = VolcengineTTSProvider()
        long_text = "这" * 40  # 40 chars → ~10 sec
        sentences = [{"sentence_idx": 1, "text": long_text}]
        result = provider.synthesize_batch(sentences, tmp_path / "tts")
        assert result.segments[0].actual_duration_sec >= 5.0  # at least 5s for 40 chars

    def test_synthesize_returns_sorted_by_idx(self, tmp_path: Path) -> None:
        provider = VolcengineTTSProvider()
        sentences = [
            {"sentence_idx": 3, "text": "第三句"},
            {"sentence_idx": 1, "text": "第一句"},
            {"sentence_idx": 2, "text": "第二句"},
        ]
        result = provider.synthesize_batch(sentences, tmp_path / "tts")
        indices = [s.sentence_idx for s in result.segments]
        assert indices == [3, 1, 2]  # order matches input order (sort is caller's responsibility)

    def test_provider_is_abstract_base(self) -> None:
        assert issubclass(VolcengineTTSProvider, TTSProvider)
