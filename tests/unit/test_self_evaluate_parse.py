"""Unit tests for self-evaluation parser (M4.4)."""

from __future__ import annotations

import json
import pytest

from autoclip.prompts.self_evaluate import parse_self_evaluate_response, _fallback_evaluation


class TestParseHappyPath:
    def test_valid_json_response(self) -> None:
        raw = json.dumps({
            "scores": {
                "script_quality": 4,
                "visual_match": 3,
                "rhythm": 4,
                "publishable": 3,
            },
            "feedback": {
                "script_quality": "整体通顺",
                "visual_match": "部分错位",
                "rhythm": "节奏合适",
                "publishable": "需小改",
            },
            "overall": 3.5,
            "suggestion": "建议调整第5句",
        })
        result = parse_self_evaluate_response(raw)
        assert result["scores"]["script_quality"] == 4
        assert result["overall"] == 3.5
        assert "script_quality" in result["feedback"]

    def test_auto_calculates_overall(self) -> None:
        raw = json.dumps({
            "scores": {"script_quality": 4, "visual_match": 4, "rhythm": 4, "publishable": 4},
            "feedback": {},
        })
        result = parse_self_evaluate_response(raw)
        assert result["overall"] == 4.0

    def test_strips_markdown_code_blocks(self) -> None:
        raw = "```json\n" + json.dumps({
            "scores": {"script_quality": 5, "visual_match": 5, "rhythm": 5, "publishable": 5},
            "feedback": {},
            "overall": 5.0,
            "suggestion": "",
        }) + "\n```"
        result = parse_self_evaluate_response(raw)
        assert result["scores"]["script_quality"] == 5


class TestParseDegradedCases:
    def test_invalid_json_returns_fallback(self) -> None:
        result = parse_self_evaluate_response("not json at all")
        assert result["overall"] == 3.0
        assert "script_quality" in result["scores"]

    def test_missing_scores_returns_fallback(self) -> None:
        raw = json.dumps({"feedback": {}, "overall": 4.0})
        result = parse_self_evaluate_response(raw)
        assert result["overall"] == 3.0  # fallback

    def test_partial_scores_handled(self) -> None:
        raw = json.dumps({
            "scores": {"script_quality": 4},  # missing other fields
            "feedback": {},
            "overall": 4.0,
        })
        result = parse_self_evaluate_response(raw)
        # Should still return without crashing
        assert "scores" in result


class TestFallbackEvaluation:
    def test_fallback_has_all_required_fields(self) -> None:
        result = _fallback_evaluation("test reason")
        assert "scores" in result
        assert "feedback" in result
        assert "overall" in result
        assert "suggestion" in result

    def test_fallback_overall_is_30(self) -> None:
        result = _fallback_evaluation("any reason")
        assert result["overall"] == 3.0
