"""Unit tests for autoclip.providers.asr.base — ASRSentence / ASRResult / ASRProvider contract."""

from pathlib import Path

import pytest

from autoclip.providers.asr import ASRProvider, ASRResult, ASRSentence

# ===== ASRSentence =====


def test_sentence_basic_fields():
    s = ASRSentence(
        idx=0,
        start_sec=1.0,
        end_sec=3.5,
        text="你好世界",
        confidence=-0.2,
    )
    assert s.idx == 0
    assert s.start_sec == 1.0
    assert s.end_sec == 3.5
    assert s.text == "你好世界"
    assert s.confidence == -0.2
    assert s.duration_sec == 2.5


def test_sentence_speaker_defaults_to_none_per_adr_009():
    """ADR-009 路径2: MVP 不做声纹, speaker 字段必须默认为 None."""
    s = ASRSentence(idx=0, start_sec=0.0, end_sec=1.0, text="hi", confidence=0.0)
    assert s.speaker is None


def test_sentence_to_dict_round_trip():
    s = ASRSentence(idx=2, start_sec=10.0, end_sec=12.5, text="test", confidence=-0.1)
    d = s.to_dict()
    assert d == {
        "idx": 2,
        "start_sec": 10.0,
        "end_sec": 12.5,
        "text": "test",
        "confidence": -0.1,
        "speaker": None,
    }


def test_sentence_negative_idx_rejected():
    with pytest.raises(ValueError, match="idx must be non-negative"):
        ASRSentence(idx=-1, start_sec=0.0, end_sec=1.0, text="x", confidence=0.0)


def test_sentence_negative_start_rejected():
    with pytest.raises(ValueError, match="start_sec must be non-negative"):
        ASRSentence(idx=0, start_sec=-0.5, end_sec=1.0, text="x", confidence=0.0)


def test_sentence_end_before_start_rejected():
    with pytest.raises(ValueError, match="end_sec .* must be >= start_sec"):
        ASRSentence(idx=0, start_sec=2.0, end_sec=1.0, text="x", confidence=0.0)


# ===== ASRResult =====


def test_result_default_construction():
    r = ASRResult()
    assert r.sentences == []
    assert r.language == "zh"
    assert r.provider == ""
    assert r.total_duration_sec == 0.0


def test_result_total_duration_sums_sentences():
    r = ASRResult(
        sentences=[
            ASRSentence(idx=0, start_sec=0.0, end_sec=1.0, text="a", confidence=0.0),
            ASRSentence(idx=1, start_sec=2.0, end_sec=4.5, text="b", confidence=0.0),
        ],
        language="zh",
        provider="local-whisper",
    )
    assert r.total_duration_sec == pytest.approx(3.5)


def test_result_to_dict_round_trip():
    s = ASRSentence(idx=0, start_sec=0.0, end_sec=1.0, text="hi", confidence=0.0)
    r = ASRResult(sentences=[s], language="en", provider="mock")
    assert r.to_dict() == {
        "sentences": [s.to_dict()],
        "language": "en",
        "provider": "mock",
    }


# ===== ASRProvider abstract contract =====


def test_asrprovider_cannot_be_instantiated_directly():
    with pytest.raises(TypeError, match="abstract"):
        ASRProvider()  # type: ignore[abstract]


def test_asrprovider_subclass_must_implement_transcribe():
    class IncompleteProvider(ASRProvider):
        pass

    with pytest.raises(TypeError, match="abstract"):
        IncompleteProvider()  # type: ignore[abstract]


def test_asrprovider_minimal_subclass_works():
    class MockProvider(ASRProvider):
        def transcribe(self, audio_path: Path, language: str = "zh") -> ASRResult:
            return ASRResult(
                sentences=[
                    ASRSentence(idx=0, start_sec=0.0, end_sec=1.0, text="mock", confidence=0.0)
                ],
                language=language,
                provider="mock",
            )

    p = MockProvider()
    result = p.transcribe(Path("/dev/null"))
    assert result.provider == "mock"
    assert len(result.sentences) == 1
    assert result.sentences[0].text == "mock"
    assert result.sentences[0].speaker is None  # ADR-009 reaffirmed
