"""Integration tests for Scripting stage — real callback chain + JSON repair + timeline schema.

Default skip behavior: NO external API calls (uses FakeListChatModel + real LlmCallsRecorder).
These tests run unconditionally on every CI/local pytest invocation.

Coverage (complementary to test_scripting_handler_progress.py unit tests):
- K3 real callback chain: FakeListChatModel.invoke() with callbacks=[LlmCallsRecorder]
  → llm_calls/scripting_001..004.json actually written to disk (v0.8.5: 4 LLM calls)
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

# v0.8.4: persona_inferer Stage1 LLM call inserted between plot_outline and narrative_ir.
# Schema must match autoclip.algo.persona_inferer.PersonaInferenceResult (Q3=B full dump).
VALID_PERSONA_JSON = json.dumps(
    {
        "persona_id": "toxic_middle_aged",
        "confidence": 0.85,
        "reasoning": "drama 题材 + 双角色冲突 + 转折结构 → 适合毒舌中年视角解读",
    },
    ensure_ascii=False,
)

# v0.8.5: hook_generator Stage1 LLM call inserted between narrative_ir and binding.
# Schema must match autoclip.algo.hook_generator output (3-5 candidates, 6 style_tag whitelist).
VALID_HOOK_CANDIDATES_JSON = json.dumps(
    {
        "candidates": [
            {"text": "为什么这部片骗了千万家长？", "style_tag": "反套路问句", "score": 0.85},
            {"text": "3 分钟戳穿教育片的伪装", "style_tag": "数字冲击", "score": 0.78},
            {"text": "号称启蒙片，实际全是错误", "style_tag": "反差对比", "score": 0.72},
        ],
    },
    ensure_ascii=False,
)

# v0.8.5 Q3.B degrade 测试用：明显非 JSON 的响应，触发 degrade fallback
INVALID_HOOK_JSON = "this is definitely not json {{{ broken"

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
        """K3: all 4 LLM calls (plot_outline + persona + narrative_ir + hook) write to llm_calls/scripting_NNN.json."""
        job_dir = tmp_path / "job_k3"
        job_dir.mkdir()
        _write_minimal_inputs(job_dir)

        # Build FakeListChatModel that REAL get_llm-style passes callbacks via constructor.
        # Trick: monkeypatch get_llm to return a FakeListChatModel BUT inject the recorder
        # passed via `callbacks` kwarg into the fake LLM's constructor (mimics ChatOpenAI).
        recorders_received: list[LlmCallsRecorder] = []
        responses_per_call = [VALID_PLOT_OUTLINE_JSON, VALID_PERSONA_JSON, VALID_NARRATIVE_IR_JSON, VALID_HOOK_CANDIDATES_JSON]
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
        # v0.8.5: handler now makes 4 LLM calls (plot_outline + persona + narrative_ir + hook)
        assert len(recorders_received) == 4, (
            f"K3 violation: expected 4 LlmCallsRecorder instances (plot_outline + persona + "
            f"narrative_ir + hook), got {len(recorders_received)}"
        )
        # All 4 LLM constructions should receive the SAME recorder instance
        # (handler creates one recorder, reuses across all LLM calls)
        assert all(r is recorders_received[0] for r in recorders_received), (
            "K3 violation: handler should reuse single recorder across all 4 LLM calls"
        )

        # Verify files actually written
        llm_calls_dir = job_dir / "llm_calls"
        assert llm_calls_dir.exists(), "K3 violation: llm_calls/ directory not created"
        files = sorted(llm_calls_dir.iterdir())
        filenames = [f.name for f in files]
        # v0.8.5: 4 LLM calls → 4 persisted files
        assert filenames == [
            "scripting_001.json", "scripting_002.json",
            "scripting_003.json", "scripting_004.json",
        ], (
            f"K3 violation: expected scripting_001..004.json (plot_outline + persona + "
            f"narrative_ir + hook), got {filenames}"
        )

    def test_persisted_call_record_schema(self, tmp_path, monkeypatch):
        """Each scripting_NNN.json has expected top-level keys."""
        job_dir = tmp_path / "job_k3b"
        job_dir.mkdir()
        _write_minimal_inputs(job_dir)

        responses_per_call = [VALID_PLOT_OUTLINE_JSON, VALID_PERSONA_JSON, VALID_NARRATIVE_IR_JSON, VALID_HOOK_CANDIDATES_JSON]
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
        responses_per_call = [TRAILING_COMMA_PLOT_OUTLINE, VALID_PERSONA_JSON, VALID_NARRATIVE_IR_JSON, VALID_HOOK_CANDIDATES_JSON]
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

        responses_per_call = [VALID_PLOT_OUTLINE_JSON, VALID_PERSONA_JSON, VALID_NARRATIVE_IR_JSON, VALID_HOOK_CANDIDATES_JSON]
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
        # v0.8.5: timeline.json 顶层加 hook_candidates (Q2.1=B + Q3.B=degrade)
        # v0.8.8 P1: 加 plot_outline_degraded (non-narrative content fallback flag)
        assert set(timeline.keys()) == {
            "plot_outline", "plot_outline_degraded", "recommended_persona", "narrative_ir",
            "hook_candidates", "binding_stats", "segments",
        }
        assert timeline["plot_outline_degraded"] is False  # happy path: normal narrative content

        # --- recommended_persona schema (v0.8.4 Q3=B) ---
        rp = timeline["recommended_persona"]
        assert set(rp.keys()) == {"persona_id", "confidence", "reasoning"}
        assert rp["persona_id"] == "toxic_middle_aged"  # matches VALID_PERSONA_JSON fixture
        assert isinstance(rp["confidence"], float) and 0.0 <= rp["confidence"] <= 1.0
        assert isinstance(rp["reasoning"], str) and len(rp["reasoning"]) > 0

        # --- hook_candidates schema (v0.8.5 Q2.1=B + Q2.3=score + Q3.B=degrade) ---
        hc = timeline["hook_candidates"]
        assert set(hc.keys()) == {"candidates", "degraded", "degrade_reason"}
        assert hc["degraded"] is False  # happy path: not degraded
        assert hc["degrade_reason"] == ""
        assert isinstance(hc["candidates"], list)
        assert 3 <= len(hc["candidates"]) <= 5  # Q2.1=B contract: 3-5 candidates
        for cand in hc["candidates"]:
            assert set(cand.keys()) == {"text", "style_tag", "score"}
            assert isinstance(cand["text"], str) and len(cand["text"]) > 0
            assert cand["style_tag"] in {
                "反套路问句", "数字冲击", "反差对比",
                "悬念伏笔", "情绪共振", "其他",
            }
            assert isinstance(cand["score"], float) and 0.0 <= cand["score"] <= 1.0

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

        # --- segments schema (per item) — v0.6: 新增 target_duration_sec_estimate 字段 ---
        assert len(timeline["segments"]) == 3
        expected_seg_keys = {
            "order_idx", "paragraph_idx", "sentence_idx", "sentence_text",
            "source_start_sec", "source_end_sec", "duration_sec",
            "source_shot_ids", "binding_method",
            "target_duration_sec_estimate",  # v0.6: 字数加权预估目标播放时长
        }
        for i, seg in enumerate(timeline["segments"]):
            assert set(seg.keys()) == expected_seg_keys
            assert seg["order_idx"] == i
            assert seg["binding_method"] == "hint_uniform"
            assert isinstance(seg["source_shot_ids"], list)
            assert seg["source_end_sec"] >= seg["source_start_sec"]
            assert abs(seg["duration_sec"] - (seg["source_end_sec"] - seg["source_start_sec"])) < 1e-6
            # v0.6: 估算字段应为正数 (字数加权后不可能为 0 或负)
            assert seg["target_duration_sec_estimate"] > 0, \
                f"segment {i} target_duration_sec_estimate must be > 0"

        # v0.6 invariant: sum(estimate) ≈ state.target_duration_sec (字数加权后总和守恒)
        # state.json 由 _write_minimal_inputs 写入 target_duration_sec=60 — 见 fixture
        total_estimate = sum(s["target_duration_sec_estimate"] for s in timeline["segments"])
        target_duration_sec = 60.0  # 与 _write_minimal_inputs fixture 对齐
        assert abs(total_estimate - target_duration_sec) / target_duration_sec <= 0.05, (
            f"v0.6 estimate sum invariant violation: sum={total_estimate} vs target={target_duration_sec} "
            f"(err {abs(total_estimate - target_duration_sec) / target_duration_sec * 100:.2f}% > 5%)"
        )

    def test_segments_order_matches_narrative_ir_iter_sentences(self, tmp_path, monkeypatch):
        """segments order_idx 严格按 NarrativeIR.iter_sentences() 全局顺序."""
        job_dir = tmp_path / "job_order"
        job_dir.mkdir()
        _write_minimal_inputs(job_dir)

        responses_per_call = [VALID_PLOT_OUTLINE_JSON, VALID_PERSONA_JSON, VALID_NARRATIVE_IR_JSON, VALID_HOOK_CANDIDATES_JSON]
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


# ---------------------------------------------------------------------------
# v0.8.5 Q3.B degrade path: hook LLM returns invalid JSON → pipeline NEVER crashes
# ---------------------------------------------------------------------------


class TestHookGenerationDegradeE2E:
    """v0.8.5 Q3.B contract: when hook_generator LLM call fails, pipeline must continue
    and timeline.json must contain hook_candidates with degraded=True + a single fallback
    candidate built from narrative_ir.paragraphs[0].sentences[0].text."""

    def test_invalid_hook_response_does_not_crash_pipeline(self, tmp_path, monkeypatch):
        job_dir = tmp_path / "job_hook_degrade"
        job_dir.mkdir()
        _write_minimal_inputs(job_dir)

        # 4 LLM calls: plot_outline OK / persona OK / narrative_ir OK / hook BROKEN
        responses_per_call = [
            VALID_PLOT_OUTLINE_JSON, VALID_PERSONA_JSON,
            VALID_NARRATIVE_IR_JSON, INVALID_HOOK_JSON,
        ]
        call_idx = [0]

        def fake_get_llm(*args, callbacks=None, **kwargs):
            llm = FakeListChatModel(
                responses=[responses_per_call[call_idx[0]]],
                callbacks=callbacks or [],
            )
            call_idx[0] += 1
            return llm

        monkeypatch.setattr(scripting, "get_llm", fake_get_llm)

        # Q3.B contract: must NOT raise
        run_scripting(job_dir)

        # Verify pipeline completed successfully despite hook failure
        state = JobStateFile(job_dir).load()
        assert state["stages"]["script"]["status"] == "done"
        assert state["stages"]["script"]["progress"] == 1.0

        # Verify timeline.json has hook_candidates with degraded=True flag
        timeline = json.loads((job_dir / "timeline.json").read_text(encoding="utf-8"))
        assert "hook_candidates" in timeline
        hc = timeline["hook_candidates"]
        assert hc["degraded"] is True
        assert "Invalid JSON" in hc["degrade_reason"]
        # Q3.B contract: exactly 1 fallback candidate, style_tag="其他", score=0.5
        assert len(hc["candidates"]) == 1
        fallback = hc["candidates"][0]
        assert fallback["style_tag"] == "其他"
        assert fallback["score"] == 0.5
        # fallback.text comes from narrative_ir.paragraphs[0].sentences[0].text
        # (per Q3.B contract; truncated to 120 chars)
        assert "First sentence." in fallback["text"]

