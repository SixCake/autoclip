"""v0.8.3 persona_inferer 单元测试 — strict mode + whitelist + plot_outline input."""

from __future__ import annotations

import json

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from autoclip.algo.narrative_ir import Character, KeyAct, PlotOutline
from autoclip.algo.persona_inferer import (
    VALID_PERSONA_IDS,
    PersonaInferenceError,
    PersonaInferenceResult,
    infer_persona,
    load_persona_description,
)

# === Fixtures ===


@pytest.fixture
def sample_plot_outline() -> PlotOutline:
    """A minimal PlotOutline for testing (drama genre, 2 characters, 3 acts)."""
    return PlotOutline(
        title_guess="测试视频",
        genre="家庭剧",
        main_characters=[
            Character(role="女主", name="小芳", description="温柔的母亲"),
            Character(role="男主", name="老王", description="沉默寡言的父亲"),
        ],
        plot_summary="一家人面对疾病的故事，最终和解。",
        key_acts=[
            KeyAct(act_idx=1, name="开场冲突", approx_start_sec=0.0, approx_end_sec=20.0, summary="争吵"),
            KeyAct(act_idx=2, name="转折", approx_start_sec=20.0, approx_end_sec=60.0, summary="疾病"),
            KeyAct(act_idx=3, name="和解", approx_start_sec=60.0, approx_end_sec=90.0, summary="拥抱"),
        ],
    )


def _fake_llm(response_text: str) -> FakeListChatModel:
    """Build a FakeListChatModel that returns the given string on .invoke()."""
    return FakeListChatModel(responses=[response_text])


# === Happy path ===


class TestInferPersonaHappyPath:
    def test_returns_result_dataclass(self, sample_plot_outline: PlotOutline) -> None:
        llm = _fake_llm(
            json.dumps(
                {
                    "persona_id": "healing_big_sister",
                    "confidence": 0.85,
                    "reasoning": "家庭剧 + 和解结尾 → 治愈系",
                }
            )
        )
        result = infer_persona(sample_plot_outline, llm_client=llm)

        assert isinstance(result, PersonaInferenceResult)
        assert result.persona_id == "healing_big_sister"
        assert result.confidence == 0.85
        assert result.reasoning == "家庭剧 + 和解结尾 → 治愈系"

    def test_strips_markdown_fence(self, sample_plot_outline: PlotOutline) -> None:
        """LLM 偶尔会包 ```json ... ``` fence，必须 strip。"""
        wrapped = "```json\n" + json.dumps(
            {"persona_id": "toxic_middle_aged", "confidence": 0.7, "reasoning": "讽刺"}
        ) + "\n```"
        llm = _fake_llm(wrapped)
        result = infer_persona(sample_plot_outline, llm_client=llm)
        assert result.persona_id == "toxic_middle_aged"

    def test_reasoning_truncated_to_200_chars(self, sample_plot_outline: PlotOutline) -> None:
        """Prompt-injection 防御：reasoning 超长截断到 200 字符。"""
        long_reasoning = "x" * 500
        llm = _fake_llm(
            json.dumps(
                {"persona_id": "archaeologist", "confidence": 0.5, "reasoning": long_reasoning}
            )
        )
        result = infer_persona(sample_plot_outline, llm_client=llm)
        assert len(result.reasoning) == 200


# === Strict mode (Q3 decision) — fail fast ===


class TestInferPersonaStrictMode:
    def test_invalid_json_raises(self, sample_plot_outline: PlotOutline) -> None:
        llm = _fake_llm("this is not json at all 我不是 JSON")
        with pytest.raises(PersonaInferenceError, match="Invalid JSON"):
            infer_persona(sample_plot_outline, llm_client=llm)

    def test_persona_not_in_whitelist_raises(self, sample_plot_outline: PlotOutline) -> None:
        """LLM 幻觉出新人格 → 必须抛异常（不静默接受）。"""
        llm = _fake_llm(
            json.dumps(
                {"persona_id": "philosophical_detective", "confidence": 0.9, "reasoning": "脑补"}
            )
        )
        with pytest.raises(PersonaInferenceError, match="not in whitelist"):
            infer_persona(sample_plot_outline, llm_client=llm)

    def test_missing_persona_id_raises(self, sample_plot_outline: PlotOutline) -> None:
        llm = _fake_llm(json.dumps({"confidence": 0.5, "reasoning": "忘了 persona_id"}))
        with pytest.raises(PersonaInferenceError, match="not in whitelist"):
            infer_persona(sample_plot_outline, llm_client=llm)

    def test_llm_api_exception_wrapped(self, sample_plot_outline: PlotOutline) -> None:
        """底层 LLM API 抛异常 → 包装为 PersonaInferenceError。"""

        class BoomLLM:
            def invoke(self, _messages):  # noqa: ANN001
                raise RuntimeError("network timeout")

        with pytest.raises(PersonaInferenceError, match="LLM API call failed"):
            infer_persona(sample_plot_outline, llm_client=BoomLLM())  # type: ignore[arg-type]


# === load_persona_description ===


class TestLoadPersonaDescription:
    @pytest.mark.parametrize("persona_id", sorted(VALID_PERSONA_IDS))
    def test_all_6_personas_loadable(self, persona_id: str) -> None:
        """6 个人格库 .md 文件必须全部存在且非空（防止 v0.8.4 注入失败）。"""
        content = load_persona_description(persona_id)
        assert len(content) > 100, f"persona {persona_id} 内容过短: {len(content)} 字符"
        # Karpathy §1 暴露假设：persona md 必须含"reference"或"台词"段
        assert "台词" in content or "reference" in content.lower(), (
            f"persona {persona_id} 缺 reference 台词段，v0.8.4 注入会失败"
        )

    def test_invalid_persona_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="not in whitelist"):
            load_persona_description("not_a_real_persona")


# === Whitelist constant integrity ===


class TestWhitelistIntegrity:
    def test_whitelist_has_exactly_6_personas(self) -> None:
        """防误删保护 — 修改前必须 review。"""
        assert len(VALID_PERSONA_IDS) == 6, (
            f"VALID_PERSONA_IDS 长度变化需 review，当前 {len(VALID_PERSONA_IDS)}: {VALID_PERSONA_IDS}"
        )

    def test_whitelist_is_frozen(self) -> None:
        """frozenset → 调用方不能误改。"""
        assert isinstance(VALID_PERSONA_IDS, frozenset)


# === v0.8.4 extract_reference_lines tests ===


from autoclip.algo.persona_inferer import extract_reference_lines  # noqa: E402


class TestExtractReferenceLines:
    def test_extracts_lines_from_real_persona_md(self) -> None:
        """对真实 docs/personas/toxic_middle_aged.md 必须提取出 5+ 条台词。"""
        md = load_persona_description("toxic_middle_aged")
        lines = extract_reference_lines(md)
        assert len(lines) >= 5, f"应至少 5 条 Reference 台词，实际 {len(lines)}"
        # Karpathy §1 暴露假设: 提取出的台词不能含序号前缀和首尾引号
        for line in lines:
            assert not line.startswith('"'), f"首字符应为引号已 strip: {line!r}"
            assert not line[0].isdigit() or "." not in line[:3], f"序号前缀未 strip: {line!r}"

    @pytest.mark.parametrize("persona_id", sorted(VALID_PERSONA_IDS))
    def test_all_6_personas_yield_non_empty_lines(self, persona_id: str) -> None:
        """6 个 persona 必须全部能提取出非空 Reference 台词列表（防 v0.8.4 注入失败）。"""
        md = load_persona_description(persona_id)
        lines = extract_reference_lines(md)
        assert len(lines) >= 5, (
            f"persona {persona_id} 提取出 {len(lines)} 条 Reference 台词，应 ≥5；"
            f"段标题正则可能与该文件不匹配，需排查"
        )

    def test_missing_section_returns_empty(self) -> None:
        """段缺失 → 返回 []（Karpathy §1: 不静默降级，由 caller 抛错）。"""
        md = "# 测试人格\n\n## 人格描述\n这里没有 Reference 段。\n\n## 失败信号\n- xxx"
        assert extract_reference_lines(md) == []

    def test_full_width_quotes_supported(self) -> None:
        """兼容全角“”引号（防 markdown 编辑器自动替换造成漏抓）。"""
        md = (
            "## 真人 Reference 台词（5-10 条）\n"
            "1. “这是全角引号台词。”\n"
            "2. \"这是半角引号台词。\"\n"
            "3. “混合段也要抓到。”\n"
            "\n"
            "## 失败信号\n- xxx\n"
        )
        lines = extract_reference_lines(md)
        assert lines == [
            "这是全角引号台词。",
            "这是半角引号台词。",
            "混合段也要抓到。",
        ]

    def test_does_not_eat_next_section(self) -> None:
        """lookahead 必须正确停在下一个 ## 段，不吞 '失败信号' 内容。"""
        md = (
            "## 真人 Reference 台词（5-10 条）\n"
            '1. "只抓这一条。"\n'
            "\n"
            "## 失败信号\n"
            '1. "这条不应该被抓到。"\n'
        )
        lines = extract_reference_lines(md)
        assert lines == ["只抓这一条。"], f"吞了下一段内容: {lines}"
