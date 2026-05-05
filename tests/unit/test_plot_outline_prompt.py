"""Unit tests for plot outline prompt builder + parser (M2a.2).

Covers:
- build_messages includes ASR text and duration_sec
- parse valid JSON
- parse JSON wrapped in markdown fence
- parse schema mismatch raises ValueError
- Character field round-trip serialization
- involved_characters reference consistency check
- main_characters empty degrade does not raise
"""

import json

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from autoclip.algo.narrative_ir import PlotOutline
from autoclip.prompts.plot_outline import build_plot_outline_messages, parse_plot_outline_response


class TestBuildPlotOutlineMessages:
    """Tests for build_plot_outline_messages()."""

    def test_build_messages_includes_asr_and_duration(self):
        """SystemMessage + HumanMessage contain ASR text and duration."""
        asr_text = "hello world this is a test"
        duration_sec = 120.5

        msgs = build_plot_outline_messages(asr_text, duration_sec)

        assert len(msgs) == 2
        assert isinstance(msgs[0], SystemMessage)
        assert isinstance(msgs[1], HumanMessage)
        assert asr_text in msgs[1].content
        assert str(duration_sec) in msgs[1].content

    def test_build_messages_truncates_long_asr(self):
        """ASR text longer than 30k chars is truncated."""
        long_text = "x" * 50000
        msgs = build_plot_outline_messages(long_text, 60.0)
        assert len(msgs[1].content) < 50000  # Should be truncated to ~30k + prompt overhead


class TestParsePlotOutlineResponse:
    """Tests for parse_plot_outline_response()."""

    @pytest.fixture
    def valid_json(self):
        return json.dumps({
            "title_guess": "Test Movie",
            "genre": "Action",
            "main_characters": [
                {"role": "男主", "name": "John", "description": "Brave hero"},
                {"role": "女主", "name": None, "description": "Mysterious lady"}
            ],
            "plot_summary": "A short summary.",
            "key_acts": [
                {
                    "act_idx": 1,
                    "name": "Opening",
                    "approx_start_sec": 0.0,
                    "approx_end_sec": 30.0,
                    "summary": "Intro scene",
                    "involved_characters": ["男主"]
                },
                {
                    "act_idx": 2,
                    "name": "Conflict",
                    "approx_start_sec": 30.0,
                    "approx_end_sec": 60.0,
                    "summary": "Fight starts",
                    "involved_characters": ["男主", "女主"]
                },
                {
                    "act_idx": 3,
                    "name": "Climax",
                    "approx_start_sec": 60.0,
                    "approx_end_sec": 90.0,
                    "summary": "Final battle",
                    "involved_characters": ["男主"]
                }
            ]
        })

    def test_parse_valid_json(self, valid_json):
        """Valid JSON parses to PlotOutline with correct fields."""
        result = parse_plot_outline_response(valid_json)

        assert isinstance(result, PlotOutline)
        assert result.title_guess == "Test Movie"
        assert result.genre == "Action"
        assert len(result.main_characters) == 2
        assert result.main_characters[0].role == "男主"
        assert result.main_characters[0].name == "John"
        assert len(result.key_acts) == 3

    def test_parse_with_markdown_fence(self, valid_json):
        """JSON wrapped in ```json ... ``` is correctly parsed."""
        fenced = f"```json\n{valid_json}\n```"
        result = parse_plot_outline_response(fenced)
        assert result.title_guess == "Test Movie"

    def test_parse_with_plain_fence(self, valid_json):
        """JSON wrapped in ``` ... ``` (no json label) is correctly parsed."""
        fenced = f"```\n{valid_json}\n```"
        result = parse_plot_outline_response(fenced)
        assert result.title_guess == "Test Movie"

    def test_parse_schema_mismatch_raises(self):
        """Missing required field raises ValueError."""
        bad_json = json.dumps({"title_guess": "Test"})  # Missing genre, main_characters, etc.
        with pytest.raises(ValueError) as exc_info:
            parse_plot_outline_response(bad_json)
        assert "Schema validation failed" in str(exc_info.value) or "Invalid JSON" in str(exc_info.value)

    def test_character_round_trip_serialization(self, valid_json):
        """Character fields serialize correctly via to_dict()."""
        result = parse_plot_outline_response(valid_json)
        char_dict = result.main_characters[0].to_dict()
        assert char_dict["role"] == "男主"
        assert char_dict["name"] == "John"
        assert char_dict["description"] == "Brave hero"

    def test_involved_characters_consistency_check(self):
        """involved_characters referencing unknown role raises ValueError."""
        bad_json = json.dumps({
            "title_guess": "Test",
            "genre": "Drama",
            "main_characters": [{"role": "男主", "name": None, "description": "Hero"}],
            "plot_summary": "Summary",
            "key_acts": [
                {"act_idx": 1, "name": "Act 1", "approx_start_sec": 0.0, "approx_end_sec": 10.0, "summary": "Intro", "involved_characters": ["未知角色"]},
                {"act_idx": 2, "name": "Act 2", "approx_start_sec": 10.0, "approx_end_sec": 20.0, "summary": "Middle", "involved_characters": []},
                {"act_idx": 3, "name": "Act 3", "approx_start_sec": 20.0, "approx_end_sec": 30.0, "summary": "End", "involved_characters": []}
            ]
        })
        with pytest.raises(ValueError) as exc_info:
            parse_plot_outline_response(bad_json)
        assert "unknown role" in str(exc_info.value).lower() or "involved_characters" in str(exc_info.value).lower()

    def test_main_characters_empty_degrade(self):
        """Empty main_characters does not raise; key_acts with empty involved_characters is OK."""
        sparse_json = json.dumps({
            "title_guess": "Unknown Title",
            "genre": "Unknown",
            "main_characters": [],
            "plot_summary": "No characters identified.",
            "key_acts": [
                {"act_idx": 1, "name": "Act 1", "approx_start_sec": 0.0, "approx_end_sec": 10.0, "summary": "Something happens", "involved_characters": []},
                {"act_idx": 2, "name": "Act 2", "approx_start_sec": 10.0, "approx_end_sec": 20.0, "summary": "More things", "involved_characters": []},
                {"act_idx": 3, "name": "Act 3", "approx_start_sec": 20.0, "approx_end_sec": 30.0, "summary": "End", "involved_characters": []}
            ]
        })
        result = parse_plot_outline_response(sparse_json)
        assert isinstance(result, PlotOutline)
        assert result.main_characters == []
        assert result.title_guess == "Unknown Title"
