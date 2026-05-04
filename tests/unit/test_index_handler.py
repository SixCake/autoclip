"""Unit tests for autoclip.pipeline.index — Index stage handler.

Strategy:
- Mock `detect_shots` and `_build_asr_provider` (the two seams) so we never
  invoke real PySceneDetect / Whisper. The real-binary path is exercised
  in tests/integration/test_index.py.
- Use a real JobStateFile against `tmp_path` so state.json mutations and
  cancel checks behave authentically (state.py is well-covered elsewhere).
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from autoclip.algo.shot_detector import Shot, ShotDetectionError
from autoclip.pipeline import index as index_mod
from autoclip.pipeline.index import (
    ASR_FILENAME,
    SHOTS_FILENAME,
    IndexStageCancelledError,
    IndexStageError,
    _atomic_write_json,
    _build_asr_provider,
    _check_cancel,
    _load_existing_shots,
    _shots_to_payload,
    run_index,
)
from autoclip.pipeline.ingest import AUDIO_FILENAME, LOW_FILENAME
from autoclip.pipeline.runner import (
    clear_stage_handlers,
    get_stage_handler,
)
from autoclip.pipeline.state import JobStateFile, Stage, StageStatus
from autoclip.providers.asr.base import ASRResult, ASRSentence

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def job_dir(tmp_path: Path) -> Path:
    """A job_dir with state.json + the two Ingest outputs (low + audio).

    File contents are dummy bytes — handler never opens them when detect_shots
    and provider.transcribe are mocked.
    """
    state = JobStateFile(tmp_path)
    state.init_state(job_id=1, video_hash="deadbeef", target_duration_sec=300)
    (tmp_path / LOW_FILENAME).write_bytes(b"fake-low-mp4")
    (tmp_path / AUDIO_FILENAME).write_bytes(b"fake-audio-wav")
    return tmp_path


def _make_shots(n: int = 3) -> list[Shot]:
    return [Shot(idx=i, start_sec=float(i * 10), end_sec=float((i + 1) * 10)) for i in range(n)]


def _make_asr_result(n_sentences: int = 2) -> ASRResult:
    sentences = [
        ASRSentence(
            idx=i,
            start_sec=float(i * 5),
            end_sec=float(i * 5 + 4),
            text=f"sentence {i}",
            confidence=-0.3,
        )
        for i in range(n_sentences)
    ]
    return ASRResult(sentences=sentences, language="zh", provider="fake-asr")


# ---------------------------------------------------------------------------
# Constants & module shape
# ---------------------------------------------------------------------------


def test_constants_match_design():
    """Filenames are part of the public stage contract — pin them."""
    assert SHOTS_FILENAME == "shots.json"
    assert ASR_FILENAME == "asr.json"


def test_handler_signature_matches_runner_contract():
    """Handler must be `(Path) -> None` to match StageHandler protocol.

    Note: `from __future__ import annotations` defers evaluation, so
    inspect.signature returns the annotation as a string (`'None'`) rather
    than the NoneType object. We assert against the string form deliberately.
    """
    import inspect

    sig = inspect.signature(run_index)
    assert list(sig.parameters) == ["job_dir"]
    # PEP 563 deferred evaluation: annotation is the string "None"
    assert sig.return_annotation in (None, "None")
    # And the parameter annotation likewise
    assert sig.parameters["job_dir"].annotation in (Path, "Path")


# ---------------------------------------------------------------------------
# _shots_to_payload
# ---------------------------------------------------------------------------


def test_shots_to_payload_basic():
    shots = _make_shots(3)
    p = _shots_to_payload(shots)
    assert p["n_shots"] == 3
    assert p["total_duration_sec"] == pytest.approx(30.0)
    assert len(p["shots"]) == 3
    assert p["shots"][0] == {"idx": 0, "start_sec": 0.0, "end_sec": 10.0}


def test_shots_to_payload_empty_list():
    """Defensive: even though detect_shots guarantees non-empty, payload must not crash."""
    p = _shots_to_payload([])
    assert p == {"n_shots": 0, "total_duration_sec": 0.0, "shots": []}


def test_shots_to_payload_total_duration_rounded():
    shots = [Shot(idx=0, start_sec=0.0, end_sec=1.23456789)]
    p = _shots_to_payload(shots)
    assert p["total_duration_sec"] == 1.235  # 3-decimal rounding


# ---------------------------------------------------------------------------
# _atomic_write_json
# ---------------------------------------------------------------------------


def test_atomic_write_json_round_trip(tmp_path: Path):
    target = tmp_path / "x.json"
    _atomic_write_json(target, {"a": 1, "b": "中文"})
    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded == {"a": 1, "b": "中文"}
    # tmp file should not survive
    assert not (tmp_path / "x.json.tmp").exists()


def test_atomic_write_json_overwrites_existing(tmp_path: Path):
    target = tmp_path / "x.json"
    target.write_text("STALE", encoding="utf-8")
    _atomic_write_json(target, {"v": 2})
    assert json.loads(target.read_text(encoding="utf-8")) == {"v": 2}


# ---------------------------------------------------------------------------
# _load_existing_shots
# ---------------------------------------------------------------------------


def test_load_existing_shots_missing_returns_none(tmp_path: Path):
    assert _load_existing_shots(tmp_path / "nope.json") is None


def test_load_existing_shots_happy_path(tmp_path: Path):
    p = tmp_path / SHOTS_FILENAME
    _atomic_write_json(p, _shots_to_payload(_make_shots(2)))
    shots = _load_existing_shots(p)
    assert shots is not None
    assert len(shots) == 2
    assert shots[0] == Shot(idx=0, start_sec=0.0, end_sec=10.0)


def test_load_existing_shots_empty_list_returns_none(tmp_path: Path):
    """An empty shots array means a previous run wrote a degenerate file → re-detect."""
    p = tmp_path / SHOTS_FILENAME
    _atomic_write_json(p, {"n_shots": 0, "total_duration_sec": 0.0, "shots": []})
    assert _load_existing_shots(p) is None


def test_load_existing_shots_corrupt_json_returns_none(tmp_path: Path):
    p = tmp_path / SHOTS_FILENAME
    p.write_text("{not-json", encoding="utf-8")
    assert _load_existing_shots(p) is None


def test_load_existing_shots_missing_field_returns_none(tmp_path: Path):
    p = tmp_path / SHOTS_FILENAME
    p.write_text(json.dumps({"shots": [{"idx": 0, "start_sec": 0.0}]}), encoding="utf-8")
    assert _load_existing_shots(p) is None  # missing end_sec


def test_load_existing_shots_wrong_schema_returns_none(tmp_path: Path):
    """A JSON object lacking 'shots' key should not crash."""
    p = tmp_path / SHOTS_FILENAME
    p.write_text(json.dumps({"unrelated": 1}), encoding="utf-8")
    assert _load_existing_shots(p) is None


# ---------------------------------------------------------------------------
# _check_cancel
# ---------------------------------------------------------------------------


def test_check_cancel_no_signal_passes(tmp_path: Path):
    state = JobStateFile(tmp_path)
    state.init_state(job_id=1, video_hash="x", target_duration_sec=10)
    _check_cancel(state, "anywhere")  # must not raise


def test_check_cancel_with_signal_raises(tmp_path: Path):
    state = JobStateFile(tmp_path)
    state.init_state(job_id=1, video_hash="x", target_duration_sec=10)
    state.request_cancel()
    with pytest.raises(IndexStageCancelledError, match="cancelled before some_step"):
        _check_cancel(state, "some_step")


def test_index_cancelled_is_subclass_of_index_error():
    """Catching IndexStageError must also catch the cancelled variant."""
    assert issubclass(IndexStageCancelledError, IndexStageError)


# ---------------------------------------------------------------------------
# _build_asr_provider — default factory hits Settings
# ---------------------------------------------------------------------------


def test_build_asr_provider_returns_local_whisper_with_settings():
    """The default factory must wire Settings.whisper_* into LocalWhisperProvider."""
    from autoclip.providers.asr.local_whisper import LocalWhisperProvider

    fake_settings = MagicMock(
        whisper_model_size="tiny",
        whisper_device="cpu",
        whisper_compute_type="int8",
    )
    fake_settings.ensure_data_dir = MagicMock()
    with patch("autoclip.pipeline.index.get_settings", return_value=fake_settings):
        provider = _build_asr_provider()

    assert isinstance(provider, LocalWhisperProvider)
    assert provider.model_size == "tiny"
    assert provider.device == "cpu"
    assert provider.compute_type == "int8"


# ---------------------------------------------------------------------------
# run_index — pre-flight input validation
# ---------------------------------------------------------------------------


def test_run_index_missing_low_raises(tmp_path: Path):
    state = JobStateFile(tmp_path)
    state.init_state(job_id=1, video_hash="x", target_duration_sec=10)
    (tmp_path / AUDIO_FILENAME).write_bytes(b"a")  # only audio, no low
    _ = state  # quiet ruff (state used implicitly via init_state side effect)
    with pytest.raises(IndexStageError, match=f"required input missing.*{LOW_FILENAME}"):
        run_index(tmp_path)


def test_run_index_missing_audio_raises(tmp_path: Path):
    state = JobStateFile(tmp_path)
    state.init_state(job_id=1, video_hash="x", target_duration_sec=10)
    (tmp_path / LOW_FILENAME).write_bytes(b"l")  # only low, no audio
    _ = state
    with pytest.raises(IndexStageError, match=f"required input missing.*{AUDIO_FILENAME}"):
        run_index(tmp_path)


# ---------------------------------------------------------------------------
# run_index — happy path
# ---------------------------------------------------------------------------


def test_run_index_happy_path_full_flow(job_dir: Path):
    fake_provider = MagicMock()
    fake_provider.transcribe.return_value = _make_asr_result(2)

    with (
        patch("autoclip.pipeline.index.detect_shots", return_value=_make_shots(3)) as ds_mock,
        patch("autoclip.pipeline.index._build_asr_provider", return_value=fake_provider) as fac_mock,
    ):
        run_index(job_dir)

    # detect_shots called with the LOW path
    ds_mock.assert_called_once_with(job_dir / LOW_FILENAME)
    # provider built once
    fac_mock.assert_called_once_with()
    # transcribe called with audio path
    fake_provider.transcribe.assert_called_once_with(job_dir / AUDIO_FILENAME)

    # shots.json content
    shots_payload = json.loads((job_dir / SHOTS_FILENAME).read_text(encoding="utf-8"))
    assert shots_payload["n_shots"] == 3
    assert len(shots_payload["shots"]) == 3

    # asr.json content
    asr_payload = json.loads((job_dir / ASR_FILENAME).read_text(encoding="utf-8"))
    assert asr_payload["language"] == "zh"
    assert asr_payload["provider"] == "fake-asr"
    assert len(asr_payload["sentences"]) == 2

    # K9: audio.wav must be deleted
    assert not (job_dir / AUDIO_FILENAME).exists()
    # but normalized_low must be untouched
    assert (job_dir / LOW_FILENAME).exists()

    # state: INDEX is DONE with progress 1.0
    state_dict = JobStateFile(job_dir).load()
    index_slot = state_dict["stages"][Stage.INDEX.value]
    assert index_slot["status"] == StageStatus.DONE.value
    assert index_slot["progress"] == 1.0


def test_run_index_progress_milestones(job_dir: Path):
    """Verify mark_stage is called with the design-spec progress values."""
    fake_provider = MagicMock()
    fake_provider.transcribe.return_value = _make_asr_result()

    progress_seen: list[float | None] = []

    real_state = JobStateFile(job_dir)
    real_mark = real_state.mark_stage

    def spy(stage, status, progress=None, error=None):
        if stage == Stage.INDEX:
            progress_seen.append(progress)
        return real_mark(stage, status, progress=progress, error=error)

    with (
        patch("autoclip.pipeline.index.detect_shots", return_value=_make_shots(2)),
        patch("autoclip.pipeline.index._build_asr_provider", return_value=fake_provider),
        patch.object(JobStateFile, "mark_stage", side_effect=spy, autospec=False),
    ):
        run_index(job_dir)

    # 0.3 (post-shots), 0.95 (post-asr), then None for the final DONE
    # (DONE doesn't pass progress; mark_stage auto-sets it to 1.0)
    assert progress_seen == [0.3, 0.95, None]


# ---------------------------------------------------------------------------
# run_index — failure surfacing
# ---------------------------------------------------------------------------


def test_run_index_shot_detection_failure_propagates(job_dir: Path):
    with (
        patch(
            "autoclip.pipeline.index.detect_shots",
            side_effect=ShotDetectionError("boom-shot"),
        ),
        pytest.raises(ShotDetectionError, match="boom-shot"),
    ):
        run_index(job_dir)
    # No partial files written
    assert not (job_dir / SHOTS_FILENAME).exists()
    assert not (job_dir / ASR_FILENAME).exists()
    # audio.wav must NOT be deleted on early failure (resume needs it)
    assert (job_dir / AUDIO_FILENAME).exists()


def test_run_index_asr_failure_keeps_shots_drops_asr(job_dir: Path):
    """ASR failure preserves shots.json (resume path) but never writes asr.json + keeps audio.wav."""
    fake_provider = MagicMock()
    fake_provider.transcribe.side_effect = RuntimeError("whisper crash")

    with (
        patch("autoclip.pipeline.index.detect_shots", return_value=_make_shots(2)),
        patch("autoclip.pipeline.index._build_asr_provider", return_value=fake_provider),
        pytest.raises(RuntimeError, match="whisper crash"),
    ):
        run_index(job_dir)

    # shots.json was written before ASR ran
    assert (job_dir / SHOTS_FILENAME).exists()
    payload = json.loads((job_dir / SHOTS_FILENAME).read_text(encoding="utf-8"))
    assert payload["n_shots"] == 2

    # asr.json must not exist (atomic write means no partial file either)
    assert not (job_dir / ASR_FILENAME).exists()
    # audio.wav preserved for resume
    assert (job_dir / AUDIO_FILENAME).exists()


def test_run_index_resume_uses_existing_shots(job_dir: Path):
    """If shots.json exists from a prior run, detect_shots must NOT be called again."""
    # Pre-seed shots.json (simulating a prior run that finished shot detection then crashed).
    # Use 5 shots with non-overlapping non-zero durations.
    _atomic_write_json(job_dir / SHOTS_FILENAME, _shots_to_payload(_make_shots(5)))

    fake_provider = MagicMock()
    fake_provider.transcribe.return_value = _make_asr_result()

    with (
        patch("autoclip.pipeline.index.detect_shots") as ds_mock,
        patch("autoclip.pipeline.index._build_asr_provider", return_value=fake_provider),
    ):
        run_index(job_dir)

    ds_mock.assert_not_called()  # the resume optimization
    # asr.json was still produced
    assert (job_dir / ASR_FILENAME).exists()
    # K9 still honored
    assert not (job_dir / AUDIO_FILENAME).exists()


# ---------------------------------------------------------------------------
# run_index — cancel checkpoints
# ---------------------------------------------------------------------------


def test_run_index_cancel_before_shot_detection(job_dir: Path):
    JobStateFile(job_dir).request_cancel()
    with (
        patch("autoclip.pipeline.index.detect_shots") as ds_mock,
        patch("autoclip.pipeline.index._build_asr_provider") as fac_mock,
        pytest.raises(IndexStageCancelledError, match="shot_detection"),
    ):
        run_index(job_dir)
    ds_mock.assert_not_called()
    fac_mock.assert_not_called()
    # No outputs, audio preserved
    assert not (job_dir / SHOTS_FILENAME).exists()
    assert not (job_dir / ASR_FILENAME).exists()
    assert (job_dir / AUDIO_FILENAME).exists()


def test_run_index_cancel_between_shots_and_asr(job_dir: Path):
    """Cancel signal arrives AFTER shots are written but BEFORE ASR — shots kept, asr skipped."""
    fake_provider = MagicMock()

    def detect_then_cancel(_video_path):
        # Simulate user hitting cancel while shot detection was running
        JobStateFile(job_dir).request_cancel()
        return _make_shots(2)

    with (
        patch("autoclip.pipeline.index.detect_shots", side_effect=detect_then_cancel),
        patch("autoclip.pipeline.index._build_asr_provider", return_value=fake_provider),
        pytest.raises(IndexStageCancelledError, match="asr_transcribe"),
    ):
        run_index(job_dir)

    # shots.json was written before the cancel checkpoint
    assert (job_dir / SHOTS_FILENAME).exists()
    # ASR provider never called
    fake_provider.transcribe.assert_not_called()
    # asr.json absent + audio preserved
    assert not (job_dir / ASR_FILENAME).exists()
    assert (job_dir / AUDIO_FILENAME).exists()


# ---------------------------------------------------------------------------
# Handler registration — survives import + clear_stage_handlers cycle
# ---------------------------------------------------------------------------


def test_handler_registered_on_import():
    """Re-importing index.py must (re-)register the handler with the runner.

    We use importlib.reload because the test_runner.py fixture
    `clear_stage_handlers()` may have wiped the global registry between tests.
    Same defensive pattern as test_ingest_handler.py.
    """
    clear_stage_handlers()
    assert get_stage_handler(Stage.INDEX) is None

    importlib.reload(index_mod)

    handler = get_stage_handler(Stage.INDEX)
    assert handler is not None
    assert handler.__name__ == "run_index"
    assert handler.__module__ == "autoclip.pipeline.index"
