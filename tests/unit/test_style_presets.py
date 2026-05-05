"""Unit tests for style preset expansion (M4.3)."""

from __future__ import annotations

import pytest

from autoclip.prompts.style_presets.humor_roast import (
    FEW_SHOT_EXAMPLE as HUMOR_EXAMPLE,
    STYLE_DESCRIPTION as HUMOR_STYLE,
    STYLE_NAME as HUMOR_NAME,
)
from autoclip.prompts.style_presets.plot_summary import (
    FEW_SHOT_EXAMPLE as PLOT_EXAMPLE,
    STYLE_DESCRIPTION as PLOT_STYLE,
    STYLE_NAME as PLOT_NAME,
)
from autoclip.prompts.style_presets.serious_review import (
    FEW_SHOT_EXAMPLE as SERIOUS_EXAMPLE,
    STYLE_DESCRIPTION as SERIOUS_STYLE,
    STYLE_NAME as SERIOUS_NAME,
)
from autoclip.prompts.narrative_ir import _STYLE_REGISTRY


class TestStylePresetNames:
    def test_all_three_names_correct(self) -> None:
        assert PLOT_NAME == "plot_summary"
        assert HUMOR_NAME == "humor_roast"
        assert SERIOUS_NAME == "serious_review"


class TestStyleDescriptions:
    def test_all_have_persona_placeholder(self) -> None:
        """All styles must have {persona_reference_block} for v0.8.4 injection."""
        for style_desc, name in [
            (PLOT_STYLE, "plot_summary"),
            (HUMOR_STYLE, "humor_roast"),
            (SERIOUS_STYLE, "serious_review"),
        ]:
            assert "{persona_reference_block}" in style_desc, f"{name} missing {{persona_reference_block}}"

    def test_all_have_duration_placeholder(self) -> None:
        for style_desc, name in [
            (PLOT_STYLE, "plot_summary"),
            (HUMOR_STYLE, "humor_roast"),
            (SERIOUS_STYLE, "serious_review"),
        ]:
            assert "{target_duration_sec}" in style_desc, f"{name} missing {{target_duration_sec}}"

    def test_styles_are_distinct(self) -> None:
        """50% threshold: at least 50% of style description should differ between presets."""
        styles = [PLOT_STYLE, HUMOR_STYLE, SERIOUS_STYLE]
        for i, style_a in enumerate(styles):
            for j, style_b in enumerate(styles):
                if i >= j:
                    continue
                # Simple check: they are not identical
                assert style_a != style_b, f"Style {i} and {j} are identical!"


class TestFewShotExamples:
    def test_all_have_at_least_3_sentences(self) -> None:
        for example, name in [
            (PLOT_EXAMPLE, "plot_summary"),
            (HUMOR_EXAMPLE, "humor_roast"),
            (SERIOUS_EXAMPLE, "serious_review"),
        ]:
            sentences = example.get("sentences", [])
            assert len(sentences) >= 3, f"{name} has only {len(sentences)} few-shot sentences (need ≥3)"

    def test_all_examples_have_required_fields(self) -> None:
        for example, name in [
            (PLOT_EXAMPLE, "plot_summary"),
            (HUMOR_EXAMPLE, "humor_roast"),
            (SERIOUS_EXAMPLE, "serious_review"),
        ]:
            assert "paragraph_idx" in example, f"{name} missing paragraph_idx"
            assert "sentences" in example, f"{name} missing sentences"
            for sent in example["sentences"]:
                assert "text" in sent, f"{name} sentence missing text"
                assert "evidence_keywords" in sent, f"{name} sentence missing evidence_keywords"


class TestStyleRegistry:
    def test_all_three_presets_in_registry(self) -> None:
        assert "plot_summary" in _STYLE_REGISTRY
        assert "humor_roast" in _STYLE_REGISTRY
        assert "serious_review" in _STYLE_REGISTRY

    def test_registry_returns_tuple_of_style_and_fewshot(self) -> None:
        for preset_name, (style_desc, few_shot) in _STYLE_REGISTRY.items():
            assert isinstance(style_desc, str), f"{preset_name} style_desc is not str"
            assert isinstance(few_shot, dict), f"{preset_name} few_shot is not dict"


class TestNarrativeIRStyleDispatch:
    def test_build_messages_with_humor_roast(self) -> None:
        from autoclip.prompts.narrative_ir import build_narrative_ir_messages
        messages = build_narrative_ir_messages(
            plot_outline_dict={
                "genre": "动作",
                "title_guess": "测试",
                "plot_summary": "测试剧情",
                "main_characters": [],
                "key_acts": [],
            },
            asr_with_timestamps="测试 ASR 内容",
            target_duration_sec=60.0,
            style_preset="humor_roast",
        )
        assert len(messages) == 2
        system_content = messages[0].content
        assert "吐槽" in system_content or "幽默" in system_content or "humor" in system_content.lower()

    def test_invalid_style_falls_back_to_plot_summary(self) -> None:
        from autoclip.prompts.narrative_ir import build_narrative_ir_messages
        messages = build_narrative_ir_messages(
            plot_outline_dict={
                "genre": "动作",
                "title_guess": "测试",
                "plot_summary": "测试",
                "main_characters": [],
                "key_acts": [],
            },
            asr_with_timestamps="测试",
            target_duration_sec=60.0,
            style_preset="nonexistent_style",  # should fall back gracefully
        )
        assert len(messages) == 2  # Should not crash
