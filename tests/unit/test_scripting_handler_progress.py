"""Unit tests for scripting handler — K10 progress milestones + K7/K8 contract verification.

Coverage:
- K10 (8 progress milestones strictly ordered): 0.05 → 0.10 → 0.25 → 0.30 → 0.60 → 0.65 → 0.80 → 0.95 → DONE(=1.0)
- K7 (input budget): timestamped_text > 32k tokens raises NarrativeIRTooLargeError
- K8 (hard failure): plot_outline 解析失败终态 raise PlotOutlineError; narrative_ir 失败 raise NarrativeIRError
- Cancel checkpoint: .cancel flag mid-stage → ScriptingCancelledError
- happy path: timeline.json 写入 + binding_method=hint_uniform + state DONE

Test strategy:
- monkeypatch get_llm → FakeListChatModel (返回预设 plot_outline + narrative_ir JSON)
- monkeypatch JobStateFile.mark_stage → 记录所有 (stage, status, progress) 调用
- 最小 fixture: shots.json + asr.json + state.json (init_state 直接调真实方法)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from autoclip.pipeline import scripting
from autoclip.pipeline.scripting import (
    NarrativeIRError,
    NarrativeIRTooLargeError,
    PlotOutlineError,
    ScriptingCancelledError,
    run_scripting,
)
from autoclip.pipeline.state import JobStateFile, Stage, StageStatus

# ---------------------------------------------------------------------------
# Fixtures: minimal valid LLM responses
# ---------------------------------------------------------------------------

VALID_PLOT_OUTLINE_JSON = json.dumps(
    {
        "title_guess": "Test Movie",
        "genre": "drama",
        "main_characters": [
            {"role": "protagonist", "name": "Alice", "description": "the lead"},
        ],
        "plot_summary": "A short test plot summary.",
        "key_acts": [
            {
                "act_idx": 1,
                "name": "Setup",
                "approx_start_sec": 0.0,
                "approx_end_sec": 10.0,
                "summary": "Things begin.",
                "involved_characters": ["protagonist"],
            },
            {
                "act_idx": 2,
                "name": "Conflict",
                "approx_start_sec": 10.0,
                "approx_end_sec": 20.0,
                "summary": "Things escalate.",
                "involved_characters": ["protagonist"],
            },
            {
                "act_idx": 3,
                "name": "Resolution",
                "approx_start_sec": 20.0,
                "approx_end_sec": 30.0,
                "summary": "Things resolve.",
                "involved_characters": ["protagonist"],
            },
        ],
    },
    ensure_ascii=False,
)

VALID_NARRATIVE_IR_JSON = json.dumps(
    {
        "paragraphs": [
            {
                "paragraph_idx": 1,
                "topic": "intro",
                "approx_source_start_sec": 0.0,
                "approx_source_end_sec": 30.0,
                "sentences": [
                    {"sentence_idx": 1, "text": "First sentence.", "evidence_keywords": []},
                    {"sentence_idx": 2, "text": "Second sentence.", "evidence_keywords": []},
                ],
            },
        ],
    },
    ensure_ascii=False,
)


def _write_minimal_inputs(job_dir: Path, n_sentences: int = 4) -> None:
    """Write minimal shots.json + asr.json + state.json into job_dir."""
    shots_payload = {
        "n_shots": 3,
        "total_duration_sec": 30.0,
        "shots": [
            {"idx": 0, "start_sec": 0.0, "end_sec": 10.0},
            {"idx": 1, "start_sec": 10.0, "end_sec": 20.0},
            {"idx": 2, "start_sec": 20.0, "end_sec": 30.0},
        ],
    }
    (job_dir / "shots.json").write_text(json.dumps(shots_payload), encoding="utf-8")

    asr_sentences = [
        {
            "start_sec": float(i * 7),
            "end_sec": float(i * 7 + 6),
            "text": f"测试句子{i}。",
        }
        for i in range(n_sentences)
    ]
    asr_payload = {"sentences": asr_sentences, "language": "zh", "provider": "fake"}
    (job_dir / "asr.json").write_text(json.dumps(asr_payload), encoding="utf-8")

    state = JobStateFile(job_dir)
    state.init_state(
        job_id=1,
        video_hash="deadbeef",
        target_duration_sec=60,
        style_preset="plot_summary",
    )


def _make_fake_llm(responses: list[str]) -> FakeListChatModel:
    """Create a FakeListChatModel returning given responses in order on .invoke()."""
    return FakeListChatModel(responses=responses)


class _MarkStageRecorder:
    """Wrap real mark_stage to record all (stage, status, progress) calls in order."""

    def __init__(self, real_mark_stage):
        self._real = real_mark_stage
        self.calls: list[tuple[str, str, float | None]] = []

    def __call__(
        self,
        stage: Stage,
        status: StageStatus,
        progress: float | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append((stage.value, status.value, progress))
        return self._real(stage, status, progress=progress, error=error)


# ---------------------------------------------------------------------------
# K10: 8 progress milestones strictly ordered
# ---------------------------------------------------------------------------


class TestK10ProgressOrder:
    def test_8_milestones_in_strict_order(self, tmp_path, monkeypatch):
        """All 8 progress milestones must fire in strict order, ending with DONE."""
        job_dir = tmp_path / "job_001"
        job_dir.mkdir()
        _write_minimal_inputs(job_dir)

        # Inject FakeListChatModel via get_llm patch — same instance for both calls
        # (FakeListChatModel maintains internal cursor across .invoke() calls)
        fake_llm = _make_fake_llm([VALID_PLOT_OUTLINE_JSON, VALID_NARRATIVE_IR_JSON])

        def fake_get_llm(*args, **kwargs):
            return fake_llm

        monkeypatch.setattr(scripting, "get_llm", fake_get_llm)

        # Wrap mark_stage to record calls
        state = JobStateFile(job_dir)
        recorder = _MarkStageRecorder(state.mark_stage)
        with patch.object(JobStateFile, "mark_stage", recorder):
            run_scripting(job_dir)

        # Extract progress values for SCRIPT stage in order
        progress_calls = [
            (status, prog) for stage, status, prog in recorder.calls if stage == "script"
        ]

        # Expected sequence (RUNNING progress + final DONE)
        expected = [
            ("running", 0.05),
            ("running", 0.10),
            ("running", 0.25),
            ("running", 0.30),
            ("running", 0.60),
            ("running", 0.65),
            ("running", 0.80),
            ("running", 0.95),
            ("done", None),
        ]
        assert progress_calls == expected, (
            f"K10 progress sequence mismatch:\n  expected: {expected}\n  actual:   {progress_calls}"
        )

    def test_progress_values_monotonically_increase(self, tmp_path, monkeypatch):
        """All progress values must be monotonically non-decreasing."""
        job_dir = tmp_path / "job_002"
        job_dir.mkdir()
        _write_minimal_inputs(job_dir)

        fake_llm = _make_fake_llm([VALID_PLOT_OUTLINE_JSON, VALID_NARRATIVE_IR_JSON])
        monkeypatch.setattr(scripting, "get_llm", lambda *a, **k: fake_llm)

        state = JobStateFile(job_dir)
        recorder = _MarkStageRecorder(state.mark_stage)
        with patch.object(JobStateFile, "mark_stage", recorder):
            run_scripting(job_dir)

        progress_values = [
            prog for stage, status, prog in recorder.calls
            if stage == "script" and prog is not None
        ]
        for i in range(1, len(progress_values)):
            assert progress_values[i] >= progress_values[i - 1], (
                f"progress regression at index {i}: "
                f"{progress_values[i - 1]} -> {progress_values[i]}"
            )

    def test_final_state_is_done_progress_1(self, tmp_path, monkeypatch):
        """After successful run, state.json shows SCRIPT stage DONE with progress=1.0."""
        job_dir = tmp_path / "job_003"
        job_dir.mkdir()
        _write_minimal_inputs(job_dir)

        fake_llm = _make_fake_llm([VALID_PLOT_OUTLINE_JSON, VALID_NARRATIVE_IR_JSON])
        monkeypatch.setattr(scripting, "get_llm", lambda *a, **k: fake_llm)

        run_scripting(job_dir)

        state = JobStateFile(job_dir).load()
        script_slot = state["stages"]["script"]
        assert script_slot["status"] == "done"
        assert script_slot["progress"] == 1.0


# ---------------------------------------------------------------------------
# K7: input budget enforcement
# ---------------------------------------------------------------------------


class TestK7TokenBudget:
    def test_timestamped_text_above_32k_raises(self, tmp_path, monkeypatch):
        """Input exceeding 32k token budget raises NarrativeIRTooLargeError before any LLM call."""
        job_dir = tmp_path / "job_k7"
        job_dir.mkdir()

        # Build 1000 sentences with 100-char Chinese text each → ~40k tokens
        # (1000 sentences × 100 chars × 0.4 tokens/char = 40000 tokens)
        big_sentences = [
            {
                "start_sec": float(i),
                "end_sec": float(i + 1),
                "text": "中" * 100,
            }
            for i in range(1000)
        ]
        (job_dir / "asr.json").write_text(
            json.dumps({"sentences": big_sentences, "language": "zh", "provider": "fake"}),
            encoding="utf-8",
        )
        (job_dir / "shots.json").write_text(
            json.dumps({"n_shots": 1, "total_duration_sec": 1000.0, "shots": [
                {"idx": 0, "start_sec": 0.0, "end_sec": 1000.0}
            ]}),
            encoding="utf-8",
        )
        JobStateFile(job_dir).init_state(
            job_id=99, video_hash="big", target_duration_sec=300, style_preset="plot_summary"
        )

        # Patch get_llm to fail loudly if called (K7 must reject before LLM call)
        def should_not_be_called(*a, **k):
            raise AssertionError("K7 must raise BEFORE any get_llm call")

        monkeypatch.setattr(scripting, "get_llm", should_not_be_called)

        with pytest.raises(NarrativeIRTooLargeError, match="32000 token budget"):
            run_scripting(job_dir)


# ---------------------------------------------------------------------------
# K8: hard failure on unrepairable LLM output
# ---------------------------------------------------------------------------


class TestK8HardFailure:
    def test_plot_outline_unrepairable_raises_PlotOutlineError(self, tmp_path, monkeypatch):
        """Unrepairable plot_outline JSON → PlotOutlineError after retries (no fallback)."""
        job_dir = tmp_path / "job_k8a"
        job_dir.mkdir()
        _write_minimal_inputs(job_dir)

        # Return garbage 3 times (matches max_attempts=3 in retry decorator)
        fake_llm = _make_fake_llm(["not json at all"] * 3)
        monkeypatch.setattr(scripting, "get_llm", lambda *a, **k: fake_llm)

        # Speed up retry: monkeypatch time.sleep
        monkeypatch.setattr("autoclip.utils.retry.time.sleep", lambda s: None)

        with pytest.raises(PlotOutlineError, match="terminally failed"):
            run_scripting(job_dir)

    def test_narrative_ir_unrepairable_raises_NarrativeIRError(self, tmp_path, monkeypatch):
        """Plot outline OK but narrative_ir unrepairable → NarrativeIRError."""
        job_dir = tmp_path / "job_k8b"
        job_dir.mkdir()
        _write_minimal_inputs(job_dir)

        # plot_outline succeeds 1st try; narrative_ir returns garbage 3 times
        fake_llm = _make_fake_llm(
            [VALID_PLOT_OUTLINE_JSON] + ["not json"] * 3
        )
        monkeypatch.setattr(scripting, "get_llm", lambda *a, **k: fake_llm)
        monkeypatch.setattr("autoclip.utils.retry.time.sleep", lambda s: None)

        with pytest.raises(NarrativeIRError, match="terminally failed"):
            run_scripting(job_dir)


# ---------------------------------------------------------------------------
# Cancel checkpoint
# ---------------------------------------------------------------------------


class TestCancelCheckpoint:
    def test_cancel_before_plot_outline_raises_cancelled(self, tmp_path, monkeypatch):
        """`.cancel` flag observed at first checkpoint → ScriptingCancelledError."""
        job_dir = tmp_path / "job_cancel"
        job_dir.mkdir()
        _write_minimal_inputs(job_dir)

        # Touch .cancel BEFORE running
        JobStateFile(job_dir).request_cancel()

        # Patch get_llm to fail loudly if called (cancel must reject before LLM)
        monkeypatch.setattr(
            scripting, "get_llm",
            lambda *a, **k: pytest.fail("LLM must NOT be called after cancel"),
        )

        with pytest.raises(ScriptingCancelledError, match="cancelled before plot_outline_llm"):
            run_scripting(job_dir)


# ---------------------------------------------------------------------------
# Happy path: timeline.json schema verification
# ---------------------------------------------------------------------------


class TestTimelineSchema:
    def test_timeline_json_contains_required_top_level_keys(self, tmp_path, monkeypatch):
        job_dir = tmp_path / "job_happy"
        job_dir.mkdir()
        _write_minimal_inputs(job_dir)

        fake_llm = _make_fake_llm([VALID_PLOT_OUTLINE_JSON, VALID_NARRATIVE_IR_JSON])
        monkeypatch.setattr(scripting, "get_llm", lambda *a, **k: fake_llm)

        run_scripting(job_dir)

        timeline = json.loads((job_dir / "timeline.json").read_text(encoding="utf-8"))
        assert set(timeline.keys()) >= {
            "plot_outline", "narrative_ir", "binding_stats", "segments"
        }

    def test_timeline_segments_have_hint_uniform_binding(self, tmp_path, monkeypatch):
        """All segments use HINT_UNIFORM binding method (M2a baseline)."""
        job_dir = tmp_path / "job_happy2"
        job_dir.mkdir()
        _write_minimal_inputs(job_dir)

        fake_llm = _make_fake_llm([VALID_PLOT_OUTLINE_JSON, VALID_NARRATIVE_IR_JSON])
        monkeypatch.setattr(scripting, "get_llm", lambda *a, **k: fake_llm)

        run_scripting(job_dir)

        timeline = json.loads((job_dir / "timeline.json").read_text(encoding="utf-8"))
        assert len(timeline["segments"]) == 2  # narrative_ir 有 2 sentences
        for seg in timeline["segments"]:
            assert seg["binding_method"] == "hint_uniform"
            assert seg["source_start_sec"] >= 0
            assert seg["source_end_sec"] >= seg["source_start_sec"]

    def test_binding_stats_M2a_baseline_zero_fallback(self, tmp_path, monkeypatch):
        """M2a baseline: fallback_count always 0, fallback_ratio 0.0."""
        job_dir = tmp_path / "job_happy3"
        job_dir.mkdir()
        _write_minimal_inputs(job_dir)

        fake_llm = _make_fake_llm([VALID_PLOT_OUTLINE_JSON, VALID_NARRATIVE_IR_JSON])
        monkeypatch.setattr(scripting, "get_llm", lambda *a, **k: fake_llm)

        run_scripting(job_dir)

        timeline = json.loads((job_dir / "timeline.json").read_text(encoding="utf-8"))
        stats = timeline["binding_stats"]
        assert stats["total_segments"] == 2
        assert stats["fallback_count"] == 0
        assert stats["fallback_ratio"] == 0.0
