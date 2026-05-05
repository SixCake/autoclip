"""Integration tests for Scripting stage — real callback chain + JSON repair + timeline schema.

Default skip behavior: NO external API calls (uses FakeListChatModel + real LlmCallsRecorder).
These tests run unconditionally on every CI/local pytest invocation.

Coverage (complementary to test_scripting_handler_progress.py unit tests):
- K3 real callback chain: FakeListChatModel.invoke() with callbacks=[LlmCallsRecorder]
  → llm_calls/scripting_001.json + scripting_002.json actually written to disk
- timeline.json full schema validation (top-level keys + nested types)
- Real JSON repair chain: 1st response has trailing comma → try_repair_json fixes
  → 2nd attempt succeeds without entering retry loop's terminal branch

For the manual real-LLM test (B2=B verification: DeepSeek primary + dashscope fallback
each smoke-tested on a 5min short clip), see scripts/test_scripting_realvideo.sh
(deferred to M2a integration verification; not gated here).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from autoclip.pipeline import scripting
from autoclip.pipeline.scripting import run_scripting
from autoclip.pipeline.state import JobStateFile
from autoclip.providers.llm import LlmCallsRecorder

# ---------------------------------------------------------------------------
# Fixtures (re-use unit test fixtures; integration extends with repair scenarios)
# ---------------------------------------------------------------------------

VALID_PLOT_OUTLINE_JSON = json.dumps(
    {
        "title_guess": "Integration Test Movie",
        "genre": "drama",
        "main_characters": [
            {"role": "protagonist", "name": "Alice", "description": "the lead"},
            {"role": "antagonist", "name": "Bob", "description": "the foil"},
        ],
        "plot_summary": "Integration test plot summary.",
        "key_acts": [
            {
                "act_idx": 1, "name": "Setup",
                "approx_start_sec": 0.0, "approx_end_sec": 10.0,
                "summary": "Things begin.", "involved_characters": ["protagonist"],
            },
            {
                "act_idx": 2, "name": "Conflict",
                "approx_start_sec": 10.0, "approx_end_sec": 20.0,
                "summary": "Things escalate.", "involved_characters": ["protagonist", "antagonist"],
            },
            {
                "act_idx": 3, "name": "Resolution",
                "approx_start_sec": 20.0, "approx_end_sec": 30.0,
                "summary": "Things resolve.", "involved_characters": ["protagonist"],
            },
        ],
    },
    ensure_ascii=False,
)

VALID_NARRATIVE_IR_JSON = json.dumps(
    {
        "paragraphs": [
            {
                "paragraph_idx": 1, "topic": "intro",
                "approx_source_start_sec": 0.0, "approx_source_end_sec": 15.0,
                "sentences": [
                    {"sentence_idx": 1, "text": "First sentence.", "evidence_keywords": []},
                    {"sentence_idx": 2, "text": "Second sentence.", "evidence_keywords": []},
                ],
            },
            {
                "paragraph_idx": 2, "topic": "outro",
                "approx_source_start_sec": 15.0, "approx_source_end_sec": 30.0,
                "sentences": [
                    {"sentence_idx": 3, "text": "Third sentence.", "evidence_keywords": []},
                ],
            },
        ],
    },
    ensure_ascii=False,
)

# Trailing-comma JSON — should be repaired by try_repair_json strategy 4 (fix_trailing_comma)
TRAILING_COMMA_PLOT_OUTLINE = VALID_PLOT_OUTLINE_JSON.rstrip("}") + ",}"


def _write_minimal_inputs(job_dir: Path) -> None:
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
        {"start_sec": float(i * 7), "end_sec": float(i * 7 + 6), "text": f"测试句子{i}。"}
        for i in range(4)
    ]
    (job_dir / "asr.json").write_text(
        json.dumps({"sentences": asr_sentences, "language": "zh", "provider": "fake"}),
        encoding="utf-8",
    )

    JobStateFile(job_dir).init_state(
        job_id=1, video_hash="deadbeef",
        target_duration_sec=60, style_preset="plot_summary",
    )


# ---------------------------------------------------------------------------
# K3: real LlmCallsRecorder callback chain → llm_calls/ files actually written
# ---------------------------------------------------------------------------


class TestK3CallbackChainE2E:
    def test_two_llm_calls_persist_to_llm_calls_directory(self, tmp_path, monkeypatch):
        """K3: both plot_outline and narrative_ir LLM calls write to llm_calls/scripting_NNN.json."""
        job_dir = tmp_path / "job_k3"
        job_dir.mkdir()
        _write_minimal_inputs(job_dir)

        # Build FakeListChatModel that REAL get_llm-style passes callbacks via constructor.
        # Trick: monkeypatch get_llm to return a FakeListChatModel BUT inject the recorder
        # passed via `callbacks` kwarg into the fake LLM's constructor (mimics ChatOpenAI).
        recorders_received: list[LlmCallsRecorder] = []
        responses_per_call = [VALID_PLOT_OUTLINE_JSON, VALID_NARRATIVE_IR_JSON]
        call_idx = [0]

        def fake_get_llm(*args, callbacks=None, **kwargs):
            llm = FakeListChatModel(
                responses=[responses_per_call[call_idx[0]]],
                callbacks=callbacks or [],
            )
            call_idx[0] += 1
            if callbacks:
                recorders_received.extend(
                    c for c in callbacks if isinstance(c, LlmCallsRecorder)
                )
            return llm

        monkeypatch.setattr(scripting, "get_llm", fake_get_llm)

        run_scripting(job_dir)

        # Verify recorder was actually passed to LLM constructor (K3 contract)
        assert len(recorders_received) == 2, (
            f"K3 violation: expected 2 LlmCallsRecorder instances, got {len(recorders_received)}"
        )
        # Both LLM constructions should receive the SAME recorder instance
        # (handler creates one recorder, reuses for both LLM calls)
        assert recorders_received[0] is recorders_received[1], (
            "K3 violation: handler should reuse single recorder across both LLM calls"
        )

        # Verify files actually written
        llm_calls_dir = job_dir / "llm_calls"
        assert llm_calls_dir.exists(), "K3 violation: llm_calls/ directory not created"
        files = sorted(llm_calls_dir.iterdir())
        filenames = [f.name for f in files]
        assert filenames == ["scripting_001.json", "scripting_002.json"], (
            f"K3 violation: expected scripting_001.json + scripting_002.json, got {filenames}"
        )

    def test_persisted_call_record_schema(self, tmp_path, monkeypatch):
        """Each scripting_NNN.json has expected top-level keys."""
        job_dir = tmp_path / "job_k3b"
        job_dir.mkdir()
        _write_minimal_inputs(job_dir)

        responses_per_call = [VALID_PLOT_OUTLINE_JSON, VALID_NARRATIVE_IR_JSON]
        call_idx = [0]

        def fake_get_llm(*args, callbacks=None, **kwargs):
            llm = FakeListChatModel(
                responses=[responses_per_call[call_idx[0]]],
                callbacks=callbacks or [],
            )
            call_idx[0] += 1
            return llm

        monkeypatch.setattr(scripting, "get_llm", fake_get_llm)
        run_scripting(job_dir)

        record_001 = json.loads(
            (job_dir / "llm_calls" / "scripting_001.json").read_text(encoding="utf-8")
        )
        # Required keys per LlmCallsRecorder schema (see callback.py)
        for key in ("seq", "stage", "model", "messages", "response", "usage",
                    "started_at", "ended_at", "duration_sec"):
            assert key in record_001, f"missing key {key!r} in persisted call record"
        assert record_001["seq"] == 1
        assert record_001["stage"] == "scripting"


# ---------------------------------------------------------------------------
# Real JSON repair chain: trailing-comma response → try_repair_json fixes
# ---------------------------------------------------------------------------


class TestRealJSONRepairChain:
    def test_trailing_comma_response_succeeds_via_repair(self, tmp_path, monkeypatch):
        """1st LLM response has trailing comma → repair fixes it → no terminal failure."""
        job_dir = tmp_path / "job_repair"
        job_dir.mkdir()
        _write_minimal_inputs(job_dir)

        # Note: TRAILING_COMMA on 1st attempt → repair fixes inside same get_llm call;
        # 2nd get_llm() returns narrative_ir LLM with valid response.
        responses_per_call = [TRAILING_COMMA_PLOT_OUTLINE, VALID_NARRATIVE_IR_JSON]
        call_idx = [0]

        def fake_get_llm(*args, callbacks=None, **kwargs):
            llm = FakeListChatModel(
                responses=[responses_per_call[call_idx[0]]],
                callbacks=callbacks or [],
            )
            call_idx[0] += 1
            return llm

        monkeypatch.setattr(scripting, "get_llm", fake_get_llm)

        # Should NOT raise — repair chain catches trailing comma silently
        run_scripting(job_dir)

        # Verify state DONE (no terminal failure)
        state = JobStateFile(job_dir).load()
        assert state["stages"]["script"]["status"] == "done"

        # Verify timeline.json was successfully written
        assert (job_dir / "timeline.json").exists()


# ---------------------------------------------------------------------------
# Full timeline.json schema validation
# ---------------------------------------------------------------------------


class TestTimelineJSONSchemaE2E:
    def test_timeline_json_full_nested_schema(self, tmp_path, monkeypatch):
        """Verify every nested field in timeline.json has expected types + structure."""
        job_dir = tmp_path / "job_schema"
        job_dir.mkdir()
        _write_minimal_inputs(job_dir)

        responses_per_call = [VALID_PLOT_OUTLINE_JSON, VALID_NARRATIVE_IR_JSON]
        call_idx = [0]

        def fake_get_llm(*args, callbacks=None, **kwargs):
            llm = FakeListChatModel(
                responses=[responses_per_call[call_idx[0]]],
                callbacks=callbacks or [],
            )
            call_idx[0] += 1
            return llm

        monkeypatch.setattr(scripting, "get_llm", fake_get_llm)
        run_scripting(job_dir)

        timeline = json.loads(
            (job_dir / "timeline.json").read_text(encoding="utf-8")
        )

        # --- top-level structure ---
        assert set(timeline.keys()) == {"plot_outline", "narrative_ir", "binding_stats", "segments"}

        # --- plot_outline schema ---
        po = timeline["plot_outline"]
        assert isinstance(po["title_guess"], str)
        assert isinstance(po["genre"], str)
        assert isinstance(po["main_characters"], list)
        assert len(po["main_characters"]) == 2
        for ch in po["main_characters"]:
            assert set(ch.keys()) == {"role", "name", "description"}
        assert isinstance(po["plot_summary"], str)
        assert isinstance(po["key_acts"], list)
        assert len(po["key_acts"]) == 3

        # --- narrative_ir schema ---
        ir = timeline["narrative_ir"]
        assert "paragraphs" in ir
        assert len(ir["paragraphs"]) == 2
        for para in ir["paragraphs"]:
            assert set(para.keys()) >= {
                "paragraph_idx", "topic", "approx_source_start_sec",
                "approx_source_end_sec", "sentences",
            }

        # --- binding_stats schema ---
        bs = timeline["binding_stats"]
        assert set(bs.keys()) == {"total_segments", "fallback_count", "fallback_ratio"}
        assert bs["total_segments"] == 3  # 2 + 1 sentences from narrative_ir
        assert bs["fallback_count"] == 0
        assert bs["fallback_ratio"] == 0.0

        # --- segments schema (per item) ---
        assert len(timeline["segments"]) == 3
        expected_seg_keys = {
            "order_idx", "paragraph_idx", "sentence_idx", "sentence_text",
            "source_start_sec", "source_end_sec", "duration_sec",
            "source_shot_ids", "binding_method",
        }
        for i, seg in enumerate(timeline["segments"]):
            assert set(seg.keys()) == expected_seg_keys
            assert seg["order_idx"] == i
            assert seg["binding_method"] == "hint_uniform"
            assert isinstance(seg["source_shot_ids"], list)
            assert seg["source_end_sec"] >= seg["source_start_sec"]
            assert abs(seg["duration_sec"] - (seg["source_end_sec"] - seg["source_start_sec"])) < 1e-6

    def test_segments_order_matches_narrative_ir_iter_sentences(self, tmp_path, monkeypatch):
        """segments order_idx 严格按 NarrativeIR.iter_sentences() 全局顺序."""
        job_dir = tmp_path / "job_order"
        job_dir.mkdir()
        _write_minimal_inputs(job_dir)

        responses_per_call = [VALID_PLOT_OUTLINE_JSON, VALID_NARRATIVE_IR_JSON]
        call_idx = [0]

        def fake_get_llm(*args, callbacks=None, **kwargs):
            llm = FakeListChatModel(
                responses=[responses_per_call[call_idx[0]]],
                callbacks=callbacks or [],
            )
            call_idx[0] += 1
            return llm

        monkeypatch.setattr(scripting, "get_llm", fake_get_llm)
        run_scripting(job_dir)

        timeline = json.loads(
            (job_dir / "timeline.json").read_text(encoding="utf-8")
        )
        segments = timeline["segments"]
        # Para 1: sentence_idx=1,2; Para 2: sentence_idx=3 → flatten to (1,1) (1,2) (2,3)
        assert [(s["paragraph_idx"], s["sentence_idx"]) for s in segments] == [
            (1, 1), (1, 2), (2, 3)
        ]
