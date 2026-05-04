"""Integration tests for the Index stage — real PySceneDetect + Whisper end-to-end.

Default skip (no fixture, no model weights, no CI cycles burned).

To run locally:
    1. Run ingest first to produce normalized_low.mp4 + audio.wav, e.g.:
         pytest tests/integration/test_ingest.py -k real_video --no-cov
       OR copy any (job_dir-shaped) directory containing the two files.
    2. Point AUTOCLIP_INDEX_FIXTURE_DIR at it.
    3. Run:
         RUN_INTEGRATION=1 \\
         AUTOCLIP_INDEX_FIXTURE_DIR=/path/to/job_dir \\
         WHISPER_MODEL_SIZE=tiny \\
         pytest tests/integration/test_index.py -v --no-cov

The tiny model is sufficient to exercise the wiring (we don't assert on
ASR text quality here — that's covered by test_local_whisper.py).
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from autoclip.pipeline.index import ASR_FILENAME, SHOTS_FILENAME, run_index
from autoclip.pipeline.ingest import AUDIO_FILENAME, LOW_FILENAME
from autoclip.pipeline.state import JobStateFile, Stage, StageStatus

ENV_RUN = "RUN_INTEGRATION"
ENV_FIXTURE = "AUTOCLIP_INDEX_FIXTURE_DIR"

pytestmark = pytest.mark.skipif(
    os.environ.get(ENV_RUN, "").strip() not in ("1", "true", "yes"),
    reason=f"set {ENV_RUN}=1 to run integration tests (requires whisper weights ~150MB+)",
)


def _resolve_fixture_dir() -> Path:
    """Locate a job_dir containing the two Ingest outputs."""
    raw = os.environ.get(ENV_FIXTURE, "").strip()
    if not raw:
        pytest.skip(
            f"{ENV_FIXTURE} not set — point it at a job_dir with "
            f"{LOW_FILENAME} + {AUDIO_FILENAME}"
        )
    src = Path(raw).expanduser().resolve()
    if not (src / LOW_FILENAME).exists() or not (src / AUDIO_FILENAME).exists():
        pytest.skip(
            f"fixture dir {src} missing required files "
            f"({LOW_FILENAME} and/or {AUDIO_FILENAME})"
        )
    return src


@pytest.fixture
def job_dir(tmp_path: Path) -> Path:
    """Materialize a fresh job_dir with copies of the two Ingest products."""
    src = _resolve_fixture_dir()
    shutil.copy2(src / LOW_FILENAME, tmp_path / LOW_FILENAME)
    shutil.copy2(src / AUDIO_FILENAME, tmp_path / AUDIO_FILENAME)
    state = JobStateFile(tmp_path)
    state.init_state(job_id=1, video_hash="integration", target_duration_sec=300)
    return tmp_path


def test_run_index_end_to_end_real_whisper(job_dir: Path):
    """Drive run_index against real shot detector + real Whisper.

    Assertions are structural (file shapes, K9 deletion, DONE state) — not
    on the actual transcribed text.
    """
    run_index(job_dir)

    # Structural: shots.json
    shots_path = job_dir / SHOTS_FILENAME
    assert shots_path.exists()
    shots_payload = json.loads(shots_path.read_text(encoding="utf-8"))
    assert shots_payload["n_shots"] >= 1
    assert isinstance(shots_payload["shots"], list)
    for s in shots_payload["shots"]:
        assert s["end_sec"] > s["start_sec"]
        assert s["start_sec"] >= 0
    starts = [s["start_sec"] for s in shots_payload["shots"]]
    assert starts == sorted(starts), "shot starts must be ascending"

    # Structural: asr.json
    asr_path = job_dir / ASR_FILENAME
    assert asr_path.exists()
    asr_payload = json.loads(asr_path.read_text(encoding="utf-8"))
    assert "sentences" in asr_payload
    assert "language" in asr_payload
    assert asr_payload["provider"] == "local-whisper"
    # tiny model on a short clip may legitimately produce 0 sentences (only silence)
    assert isinstance(asr_payload["sentences"], list)

    # K9: audio.wav deleted, normalized_low untouched
    assert not (job_dir / AUDIO_FILENAME).exists()
    assert (job_dir / LOW_FILENAME).exists()

    # State: INDEX DONE with progress=1.0
    slot = JobStateFile(job_dir).load()["stages"][Stage.INDEX.value]
    assert slot["status"] == StageStatus.DONE.value
    assert slot["progress"] == 1.0


def test_run_index_resume_reuses_shots_json(job_dir: Path):
    """Crash-and-recover: shots.json from a prior run must be reused on retry.

    Original (broken) design tried to sabotage by deleting audio.wav before
    the first run — but the handler's pre-flight check raises IndexStageError
    BEFORE detect_shots even runs, so shots.json never gets written. That
    test could never actually exercise the resume path.

    Correct design: simulate a partial-success state directly.
    1. Run once successfully  → shots.json + asr.json present, audio.wav gone.
    2. Simulate a 2nd-stage retry by removing asr.json and restoring audio.wav
       (i.e. pretend the prior run completed shot detection and ASR but a
       downstream consumer wiped asr.json — operationally equivalent to the
       crash-after-shots-before-asr-finalized case).
    3. Re-run; the handler should skip detect_shots entirely.

    Strict reuse proof for the integration layer (where we can't mock the
    seam): shots.json bytes + mtime must be identical across the two runs.
    The unit test `test_run_index_resume_uses_existing_shots` provides the
    full mock-based proof that detect_shots is never called.
    """
    src = _resolve_fixture_dir()

    # --- 1st run: full success ---
    run_index(job_dir)
    shots_path = job_dir / SHOTS_FILENAME
    asr_path = job_dir / ASR_FILENAME
    assert shots_path.exists()
    assert asr_path.exists()
    assert not (job_dir / AUDIO_FILENAME).exists()

    shots_bytes_before = shots_path.read_bytes()
    shots_mtime_before = shots_path.stat().st_mtime_ns

    # --- Set up partial-success state for 2nd run ---
    asr_path.unlink()  # simulate asr.json wiped
    shutil.copy2(src / AUDIO_FILENAME, job_dir / AUDIO_FILENAME)

    # --- 2nd run: must reuse shots.json (no re-detection) ---
    run_index(job_dir)

    # Strict reuse proof: shots.json untouched (same bytes + same mtime)
    shots_bytes_after = shots_path.read_bytes()
    shots_mtime_after = shots_path.stat().st_mtime_ns
    assert shots_bytes_after == shots_bytes_before, (
        "shots.json was rewritten — resume optimization broken"
    )
    assert shots_mtime_after == shots_mtime_before, (
        "shots.json mtime changed — file was touched even if contents matched"
    )

    # asr.json regenerated, K9 honored
    assert asr_path.exists()
    assert not (job_dir / AUDIO_FILENAME).exists()
