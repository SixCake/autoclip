"""Unit tests for LocalWhisperProvider — focused on logic that does NOT require model weights.

Real model loading is tested in tests/integration/test_local_whisper.py (default skip).
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from autoclip.providers.asr import ASRSentence
from autoclip.providers.asr.local_whisper import (
    LocalWhisperProvider,
    _reset_singleton_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_model_cache():
    """Each test starts with a clean module-level singleton cache."""
    _reset_singleton_for_tests()
    yield
    _reset_singleton_for_tests()


# ===== Defaults =====


def test_provider_defaults_match_adr_004():
    p = LocalWhisperProvider()
    assert p.model_size == "large-v3"
    assert p.device == "auto"
    assert p.compute_type == "default"
    assert p.beam_size == 5
    assert p.PROVIDER_NAME == "local-whisper"


def test_provider_custom_args():
    p = LocalWhisperProvider(model_size="medium", device="cpu", compute_type="int8", beam_size=3)
    assert p.model_size == "medium"
    assert p.device == "cpu"
    assert p.compute_type == "int8"
    assert p.beam_size == 3


# ===== File not found =====


def test_transcribe_missing_audio_raises_file_not_found(tmp_path):
    p = LocalWhisperProvider()
    missing = tmp_path / "does_not_exist.wav"
    with pytest.raises(FileNotFoundError, match="audio file not found"):
        p.transcribe(missing)


# ===== Post-processing logic =====


def _seg(start, end, text, avg_logprob=-0.3):
    """Build a fake faster-whisper segment object."""
    return SimpleNamespace(start=start, end=end, text=text, avg_logprob=avg_logprob)


def test_postprocess_drops_empty_text():
    out = LocalWhisperProvider._postprocess_segments(
        iter(
            [
                _seg(0.0, 1.0, "  "),
                _seg(1.0, 2.0, "hello"),
                _seg(2.0, 3.0, ""),
            ]
        )
    )
    assert len(out) == 1
    assert out[0].text == "hello"
    assert out[0].idx == 0  # reindexed continuously


def test_postprocess_drops_low_confidence():
    out = LocalWhisperProvider._postprocess_segments(
        iter(
            [
                _seg(0.0, 1.0, "noise", avg_logprob=-1.5),
                _seg(1.0, 2.0, "good", avg_logprob=-0.2),
            ]
        )
    )
    assert len(out) == 1
    assert out[0].text == "good"


def test_postprocess_drops_short_glitch():
    """Short (<1s) AND short-text (<4 chars) segments are dropped as glitches."""
    out = LocalWhisperProvider._postprocess_segments(
        iter(
            [
                _seg(0.0, 0.3, "啊"),  # both short → drop
                _seg(1.0, 1.3, "完整一句话"),  # short dur but >=4 chars → keep
                _seg(2.0, 5.0, "嗯"),  # short text but long dur → keep
            ]
        )
    )
    assert [s.text for s in out] == ["完整一句话", "嗯"]


def test_postprocess_reindexes_after_drops():
    out = LocalWhisperProvider._postprocess_segments(
        iter(
            [
                _seg(0.0, 1.0, "first"),
                _seg(1.0, 2.0, "", avg_logprob=-0.1),  # dropped (empty)
                _seg(2.0, 3.0, "second"),
                _seg(3.0, 4.0, "noise", avg_logprob=-2.0),  # dropped (low conf)
                _seg(4.0, 5.0, "third"),
            ]
        )
    )
    assert [s.idx for s in out] == [0, 1, 2]
    assert [s.text for s in out] == ["first", "second", "third"]


def test_postprocess_speaker_always_none_per_adr_009():
    out = LocalWhisperProvider._postprocess_segments(iter([_seg(0.0, 2.0, "hello world")]))
    assert all(s.speaker is None for s in out)


# ===== Singleton + transcribe orchestration =====


def test_transcribe_uses_singleton_on_repeated_calls(tmp_path):
    """Model should be loaded ONCE across multiple transcribe() calls."""
    audio = tmp_path / "fake.wav"
    audio.write_bytes(b"fake")

    fake_model = MagicMock()
    fake_model.transcribe.return_value = (
        iter([_seg(0.0, 1.5, "hello world")]),
        SimpleNamespace(language="zh"),
    )

    with patch(
        "autoclip.providers.asr.local_whisper.WhisperModel",
        return_value=fake_model,
    ) as mock_cls:
        p = LocalWhisperProvider(model_size="tiny")
        result1 = p.transcribe(audio)
        result2 = p.transcribe(audio)

    assert mock_cls.call_count == 1, "Model class should be instantiated only once (singleton)"
    assert fake_model.transcribe.call_count == 2
    assert result1.provider == "local-whisper"
    assert result2.provider == "local-whisper"
    assert result1.sentences[0].text == "hello world"


def test_transcribe_passes_correct_args_to_model(tmp_path):
    audio = tmp_path / "fake.wav"
    audio.write_bytes(b"fake")

    fake_model = MagicMock()
    fake_model.transcribe.return_value = (
        iter([]),
        SimpleNamespace(language="zh"),
    )

    with patch(
        "autoclip.providers.asr.local_whisper.WhisperModel",
        return_value=fake_model,
    ):
        p = LocalWhisperProvider(beam_size=7)
        p.transcribe(audio, language="en")

    fake_model.transcribe.assert_called_once_with(
        str(audio),
        language="en",
        beam_size=7,
        vad_filter=True,
        word_timestamps=False,
    )


# ===== Fallback chain =====


def test_load_falls_back_to_medium_on_primary_failure(tmp_path):
    audio = tmp_path / "fake.wav"
    audio.write_bytes(b"fake")

    call_count = {"n": 0}

    def fake_ctor(*args, model_size_or_path: str, **kwargs):
        call_count["n"] += 1
        if model_size_or_path == "large-v3":
            raise RuntimeError("simulated OOM")
        # medium succeeds
        m = MagicMock()
        m.transcribe.return_value = (
            iter([_seg(0.0, 1.5, "fallback ok")]),
            SimpleNamespace(language="zh"),
        )
        return m

    with patch(
        "autoclip.providers.asr.local_whisper.WhisperModel",
        side_effect=fake_ctor,
    ):
        p = LocalWhisperProvider(model_size="large-v3")
        result = p.transcribe(audio)

    assert call_count["n"] == 2  # large-v3 attempted, medium fell through
    assert result.sentences[0].text == "fallback ok"


def test_load_raises_runtime_error_when_both_fail(tmp_path):
    audio = tmp_path / "fake.wav"
    audio.write_bytes(b"fake")

    with patch(
        "autoclip.providers.asr.local_whisper.WhisperModel",
        side_effect=RuntimeError("nope"),
    ):
        p = LocalWhisperProvider(model_size="large-v3")
        with pytest.raises(RuntimeError, match="Failed to load whisper fallback 'medium'"):
            p.transcribe(audio)


def test_load_raises_runtime_error_when_medium_directly_fails(tmp_path):
    """If user explicitly asks for 'medium' and it fails, no further fallback."""
    audio = tmp_path / "fake.wav"
    audio.write_bytes(b"fake")

    with patch(
        "autoclip.providers.asr.local_whisper.WhisperModel",
        side_effect=RuntimeError("nope"),
    ):
        p = LocalWhisperProvider(model_size="medium")
        with pytest.raises(RuntimeError, match="Failed to load whisper model 'medium'"):
            p.transcribe(audio)


# ===== Sanity: post-processing produces valid ASRSentence objects =====


def test_postprocess_returns_asr_sentence_instances():
    out = LocalWhisperProvider._postprocess_segments(iter([_seg(0.0, 1.5, "hello")]))
    assert len(out) == 1
    assert isinstance(out[0], ASRSentence)
