"""Unit tests for v0.8.5 hook_generator (algo/hook_generator.py).

Test matrix per v0.8.5 brainstorming decisions:
- HappyPath (2): valid 3 / 5 candidates
- DegradePath (8): all 5 brainstorming-listed degrade triggers + edge cases
  (invalid JSON / count <3 / count >5 / invalid style_tag / score out of range /
   LLM API error / empty text / degrade fallback uses paragraphs[0].sentences[0])
- WhitelistIntegrity (1): all 6 style_tags accepted
- PromptStructure (1): _format_inputs injects persona + paragraphs[0]
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from autoclip.algo.hook_generator import (
    MAX_CANDIDATES,
    MIN_CANDIDATES,
    VALID_STYLE_TAGS,
    HookCandidate,
    HookCandidatesResult,
    HookGenerationError,
    _format_inputs,
    generate_hook_candidates,
)
from autoclip.algo.narrative_ir import (
    Character,
    KeyAct,
    NarrativeIR,
    NarrativeParagraph,
    NarrativeSentence,
    PlotOutline,
)
from autoclip.algo.persona_inferer import PersonaInferenceResult


# === Fixtures ===


def _make_plot_outline() -> PlotOutline:
    return PlotOutline(
        title_guess="测试电影",
        genre="drama",
        main_characters=[
            Character(role="protagonist", name="Alice", description="主角"),
        ],
        plot_summary="测试剧情概要",
        key_acts=[
            KeyAct(act_idx=1, name="开场", approx_start_sec=0.0, approx_end_sec=10.0,
                   summary="开始", involved_characters=["protagonist"]),
        ],
    )


def _make_persona_result() -> PersonaInferenceResult:
    return PersonaInferenceResult(
        persona_id="toxic_middle_aged",
        confidence=0.85,
        reasoning="drama 题材适合毒舌视角",
    )


def _make_narrative_ir(first_sentence_text: str = "原文第一句钩子。") -> NarrativeIR:
    return NarrativeIR(
        paragraphs=[
            NarrativeParagraph(
                paragraph_idx=1,
                topic="开场",
                approx_source_start_sec=0.0,
                approx_source_end_sec=10.0,
                sentences=[
                    NarrativeSentence(sentence_idx=1, text=first_sentence_text, evidence_keywords=[]),
                    NarrativeSentence(sentence_idx=2, text="第二句正文。", evidence_keywords=[]),
                ],
            ),
        ],
    )


def _make_valid_response(n: int = 3, style_tag: str = "反套路问句") -> str:
    """Build a valid LLM JSON response with n candidates."""
    return json.dumps(
        {
            "candidates": [
                {"text": f"候选钩子 {i + 1}", "style_tag": style_tag, "score": 0.5 + i * 0.1}
                for i in range(n)
            ]
        },
        ensure_ascii=False,
    )


# === HappyPath (2 tests) ===


class TestHappyPath:
    def test_3_candidates_valid_response(self) -> None:
        fake_llm = FakeListChatModel(responses=[_make_valid_response(n=3)])
        result = generate_hook_candidates(
            _make_plot_outline(), _make_persona_result(), _make_narrative_ir(),
            llm_client=fake_llm,
        )
        assert isinstance(result, HookCandidatesResult)
        assert len(result.candidates) == 3
        assert not result.degraded
        assert result.degrade_reason == ""
        for c in result.candidates:
            assert isinstance(c, HookCandidate)
            assert c.style_tag in VALID_STYLE_TAGS
            assert 0.0 <= c.score <= 1.0

    def test_5_candidates_valid_response(self) -> None:
        fake_llm = FakeListChatModel(responses=[_make_valid_response(n=5)])
        result = generate_hook_candidates(
            _make_plot_outline(), _make_persona_result(), _make_narrative_ir(),
            llm_client=fake_llm,
        )
        assert len(result.candidates) == 5
        assert not result.degraded


# === DegradePath (8 tests, covering all 5 brainstorming-listed triggers + edge cases) ===


class TestDegradePath:
    """Q3.B contract: generate_hook_candidates() NEVER raises; all failures degrade."""

    def test_invalid_json_triggers_degrade(self) -> None:
        fake_llm = FakeListChatModel(responses=["not json at all"])
        result = generate_hook_candidates(
            _make_plot_outline(), _make_persona_result(), _make_narrative_ir(),
            llm_client=fake_llm,
        )
        assert result.degraded
        assert "Invalid JSON" in result.degrade_reason
        assert len(result.candidates) == 1  # fallback single candidate

    def test_count_below_3_triggers_degrade(self) -> None:
        fake_llm = FakeListChatModel(responses=[_make_valid_response(n=2)])
        result = generate_hook_candidates(
            _make_plot_outline(), _make_persona_result(), _make_narrative_ir(),
            llm_client=fake_llm,
        )
        assert result.degraded
        assert f"not in [{MIN_CANDIDATES}, {MAX_CANDIDATES}]" in result.degrade_reason

    def test_count_above_5_triggers_degrade(self) -> None:
        fake_llm = FakeListChatModel(responses=[_make_valid_response(n=6)])
        result = generate_hook_candidates(
            _make_plot_outline(), _make_persona_result(), _make_narrative_ir(),
            llm_client=fake_llm,
        )
        assert result.degraded
        assert f"not in [{MIN_CANDIDATES}, {MAX_CANDIDATES}]" in result.degrade_reason

    def test_invalid_style_tag_triggers_degrade(self) -> None:
        bad_response = json.dumps(
            {"candidates": [
                {"text": "x", "style_tag": "INVALID_TAG_NOT_IN_WHITELIST", "score": 0.5}
            ] * 3},
            ensure_ascii=False,
        )
        fake_llm = FakeListChatModel(responses=[bad_response])
        result = generate_hook_candidates(
            _make_plot_outline(), _make_persona_result(), _make_narrative_ir(),
            llm_client=fake_llm,
        )
        assert result.degraded
        assert "not in whitelist" in result.degrade_reason

    def test_score_out_of_range_triggers_degrade(self) -> None:
        bad_response = json.dumps(
            {"candidates": [
                {"text": "x", "style_tag": "反套路问句", "score": 1.5}
            ] * 3},
            ensure_ascii=False,
        )
        fake_llm = FakeListChatModel(responses=[bad_response])
        result = generate_hook_candidates(
            _make_plot_outline(), _make_persona_result(), _make_narrative_ir(),
            llm_client=fake_llm,
        )
        assert result.degraded
        assert "not in [0.0, 1.0]" in result.degrade_reason

    def test_llm_api_error_triggers_degrade(self) -> None:
        """Mock llm_client.invoke() to raise — should be caught and degraded, NOT propagated."""
        fake_llm = MagicMock()
        fake_llm.invoke.side_effect = ConnectionError("simulated API failure")
        result = generate_hook_candidates(
            _make_plot_outline(), _make_persona_result(), _make_narrative_ir(),
            llm_client=fake_llm,
        )
        assert result.degraded
        assert "LLM API call failed" in result.degrade_reason
        assert "simulated API failure" in result.degrade_reason

    def test_empty_text_triggers_degrade(self) -> None:
        bad_response = json.dumps(
            {"candidates": [
                {"text": "   ", "style_tag": "反套路问句", "score": 0.5}
            ] * 3},
            ensure_ascii=False,
        )
        fake_llm = FakeListChatModel(responses=[bad_response])
        result = generate_hook_candidates(
            _make_plot_outline(), _make_persona_result(), _make_narrative_ir(),
            llm_client=fake_llm,
        )
        assert result.degraded
        assert "empty/invalid text" in result.degrade_reason

    def test_degrade_uses_first_sentence_as_fallback(self) -> None:
        """When degrade triggers, fallback candidate.text MUST come from
        narrative_ir.paragraphs[0].sentences[0].text (Q3.B contract)."""
        original_first = "这是 narrative_ir 的第一句话，应该作为 degrade fallback 的来源。"
        fake_llm = FakeListChatModel(responses=["not json"])  # force degrade
        result = generate_hook_candidates(
            _make_plot_outline(), _make_persona_result(), _make_narrative_ir(original_first),
            llm_client=fake_llm,
        )
        assert result.degraded
        assert len(result.candidates) == 1
        fallback = result.candidates[0]
        assert original_first in fallback.text  # may be capped at 120 chars but should be substring
        assert fallback.style_tag == "其他"
        assert fallback.score == 0.5


# === WhitelistIntegrity (1 test) ===


class TestWhitelistIntegrity:
    @pytest.mark.parametrize("style_tag", sorted(VALID_STYLE_TAGS))
    def test_all_6_style_tags_accepted(self, style_tag: str) -> None:
        """Every tag in VALID_STYLE_TAGS must be acceptable in LLM response (no over-rejection)."""
        response = json.dumps(
            {"candidates": [
                {"text": f"候选 {i}", "style_tag": style_tag, "score": 0.7}
                for i in range(3)
            ]},
            ensure_ascii=False,
        )
        fake_llm = FakeListChatModel(responses=[response])
        result = generate_hook_candidates(
            _make_plot_outline(), _make_persona_result(), _make_narrative_ir(),
            llm_client=fake_llm,
        )
        assert not result.degraded, f"style_tag {style_tag!r} rejected: {result.degrade_reason}"
        assert all(c.style_tag == style_tag for c in result.candidates)


# === PromptStructure (1 test) ===


class TestPromptStructure:
    def test_format_inputs_includes_persona_and_first_paragraph(self) -> None:
        """_format_inputs must inject persona_id + reasoning + ALL sentences of paragraphs[0]
        (Q3.A=B contract)."""
        fields = _format_inputs(
            _make_plot_outline(),
            _make_persona_result(),
            _make_narrative_ir("第一句独特标记 ABCXYZ"),
        )
        assert fields["persona_id"] == "toxic_middle_aged"
        assert "drama" in fields["persona_reasoning"]
        assert "第一句独特标记 ABCXYZ" in fields["first_paragraph_text"]
        assert "第二句正文。" in fields["first_paragraph_text"]  # paragraph 全部句子都注入
        assert "测试电影" in fields["title_guess"]


# === Module-level smoke ===


class TestModuleSurface:
    def test_HookGenerationError_is_RuntimeError(self) -> None:
        assert issubclass(HookGenerationError, RuntimeError)

    def test_VALID_STYLE_TAGS_has_exactly_6_entries(self) -> None:
        assert len(VALID_STYLE_TAGS) == 6

    def test_VALID_STYLE_TAGS_contains_其他_for_degrade(self) -> None:
        """degrade fallback uses style_tag='其他' — must exist in whitelist."""
        assert "其他" in VALID_STYLE_TAGS
