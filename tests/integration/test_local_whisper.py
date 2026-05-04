"""Integration test for LocalWhisperProvider — runs real faster-whisper model.

Skipped by default (loading large-v3 takes ~30s and downloads ~3GB on first run).
Enable with `RUN_INTEGRATION=1 pytest tests/integration/test_local_whisper.py`.

Requires:
- A real audio fixture at tests/fixtures/audio_5s_zh.wav (16kHz mono, 5s of Chinese speech).
- ~3GB free disk for HF model cache (or set WHISPER_MODEL_SIZE=tiny for cheap CI).
"""

import os
from pathlib import Path

import pytest

from autoclip.providers.asr import ASRResult
from autoclip.providers.asr.local_whisper import (
    LocalWhisperProvider,
    _reset_singleton_for_tests,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1",
    reason="Set RUN_INTEGRATION=1 to run integration tests (downloads/loads whisper model)",
)


FIXTURE = Path(__file__).parent.parent / "fixtures" / "audio_5s_zh.wav"


@pytest.fixture(autouse=True)
def _reset_singleton():
    _reset_singleton_for_tests()
    yield
    _reset_singleton_for_tests()


@pytest.mark.integration
@pytest.mark.slow
def test_transcribe_5s_chinese_audio_with_tiny_model():
    """Smoke test — uses 'tiny' model to keep CI cheap; 5s audio ~5s wall time."""
    if not FIXTURE.exists():
        pytest.skip(f"audio fixture not found: {FIXTURE}; provide a 5s zh wav to enable")

    # Allow override via env so dev can switch model sizes without editing code.
    model_size = os.environ.get("WHISPER_TEST_MODEL", "tiny")
    p = LocalWhisperProvider(model_size=model_size, device="auto", compute_type="default")

    result = p.transcribe(FIXTURE, language="zh")

    assert isinstance(result, ASRResult)
    assert result.provider == "local-whisper"
    assert result.language == "zh"
    assert len(result.sentences) >= 1, "expected at least one sentence from 5s of speech"

    # Timestamps must be monotonically increasing.
    starts = [s.start_sec for s in result.sentences]
    assert starts == sorted(starts), "sentence start_sec must be ascending"

    # All sentences must have non-empty text and speaker=None (ADR-009).
    for s in result.sentences:
        assert s.text.strip(), "sentence text must be non-empty post-processing"
        assert s.speaker is None, "MVP must not populate speaker field (ADR-009)"
        assert s.end_sec > s.start_sec
