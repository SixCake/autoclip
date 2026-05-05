"""Unit tests for autoclip.utils.tokens.estimate_tokens — M2a.6 K7 guardrail input.

Coverage:
- Empty / non-str / type validation
- Pure CJK (Chinese-only) ratio ≈ chars / 2.5
- Pure ASCII ratio ≈ chars / 4
- Mixed CJK + ASCII (per-char weighting, not one-pass-counts-all)
- Conservative rounding (always ceil — never under-report for K7)
- K7 input gate boundary scenarios: under / at / above 90k token budget (v0.6)
- calc_narrative_ir_max_tokens (v0.6 K7 输出闸门) 边界用例
"""

from __future__ import annotations

import pytest

from autoclip.utils.tokens import (
    INPUT_TOKEN_BUDGET_K7,
    calc_narrative_ir_max_tokens,
    estimate_tokens,
)


class TestInputValidation:
    def test_empty_string_returns_zero(self):
        assert estimate_tokens("") == 0

    def test_none_raises_type_error(self):
        with pytest.raises(TypeError, match="expects str"):
            estimate_tokens(None)  # type: ignore[arg-type]

    def test_int_raises_type_error(self):
        with pytest.raises(TypeError, match="expects str"):
            estimate_tokens(123)  # type: ignore[arg-type]


class TestPureCJK:
    def test_25_chinese_chars_equals_10_tokens(self):
        # 25 / 2.5 = 10 exactly
        assert estimate_tokens("中" * 25) == 10

    def test_1_chinese_char_rounds_up_to_1_token(self):
        # ceil(1/2.5) = 1
        assert estimate_tokens("中") == 1

    def test_3_chinese_chars_rounds_up_to_2_tokens(self):
        # ceil(3/2.5) = 2
        assert estimate_tokens("中文字") == 2


class TestPureASCII:
    def test_4_ascii_chars_equals_1_token(self):
        assert estimate_tokens("abcd") == 1

    def test_1_ascii_char_rounds_up_to_1_token(self):
        # ceil(1/4) = 1
        assert estimate_tokens("a") == 1

    def test_100_ascii_chars_equals_25_tokens(self):
        assert estimate_tokens("a" * 100) == 25


class TestMixedText:
    def test_cjk_plus_ascii_per_class_weighted(self):
        # 5 中文 (ceil(5/2.5)=2) + 8 ASCII (ceil(8/4)=2) = 4 tokens
        assert estimate_tokens("中文测试啊" + "abcdefgh") == 4

    def test_cjk_dominates_when_ascii_minority(self):
        # 100 CJK + 4 ASCII = ceil(100/2.5) + ceil(4/4) = 40 + 1 = 41
        assert estimate_tokens("中" * 100 + "test") == 41


class TestK7InputGate:
    """K7 v0.6 输入闸门: INPUT_TOKEN_BUDGET_K7 = 90000 tokens; verify estimator near threshold.

    v0.6 修订: 阈值从 32000 → 90000 (DeepSeek 128k context 留 30k 给输出的安全水位).
    M2a baseline 实测视频 (90min) ≈ 18k tokens, 远低于阈值 — 阈值升级是为 4h+ 长视频留余地.
    """

    def test_constant_value_is_90000(self):
        """输入闸门常量值校验 (v0.6 改名 + 改值)."""
        assert INPUT_TOKEN_BUDGET_K7 == 90000

    def test_under_budget_typical_90min_video(self):
        # 45000 中文 ≈ 18000 tokens (typical 90min 双语字幕) — well under 90k
        result = estimate_tokens("中" * 45000)
        assert result == 18000
        assert result < INPUT_TOKEN_BUDGET_K7

    def test_exactly_at_budget_chinese(self):
        # 225000 中文 = 90000 tokens exactly (45000 / 2.5 * 2 ≈ 4h+ 视频)
        result = estimate_tokens("中" * 225000)
        assert result == 90000
        assert result == INPUT_TOKEN_BUDGET_K7

    def test_above_budget_chinese_triggers_k7(self):
        # 225003 中文 → ceil(225003/2.5) = 90002 > 90000
        result = estimate_tokens("中" * 225003)
        assert result == 90002
        assert result > INPUT_TOKEN_BUDGET_K7


class TestK7OutputGate:
    """K7 v0.6 输出闸门: calc_narrative_ir_max_tokens(target_sentences).

    公式: clamp(target_sentences * 80 + 1000, 2000, 16000).
    v0.6 修复 600s 档位 100% 失败的 P0 bug (硬编码 8000 → 动态算).
    """

    def test_zero_sentences_clamps_to_min(self):
        # 0 * 80 + 1000 = 1000 → clamp → 2000
        assert calc_narrative_ir_max_tokens(0) == 2000

    def test_10_sentences_60s_pico_archetype_clamps_min(self):
        # 60s 档位: 10 * 80 + 1000 = 1800 → clamp → 2000
        assert calc_narrative_ir_max_tokens(10) == 2000

    def test_50_sentences_300s_archetype_no_clamp(self):
        # 300s 档位: 50 * 80 + 1000 = 5000
        assert calc_narrative_ir_max_tokens(50) == 5000

    def test_100_sentences_600s_archetype_no_clamp(self):
        """600s 档位 — 这是修复的核心 bug 场景: 原硬编码 8000 不够, 现 9000 足够."""
        # 600s 档位: 100 * 80 + 1000 = 9000
        assert calc_narrative_ir_max_tokens(100) == 9000
        assert calc_narrative_ir_max_tokens(100) > 8000  # 原硬编码值, 验证 v0.6 修复有效

    def test_200_sentences_1200s_archetype_clamps_to_max(self):
        # 1200s 档位: 200 * 80 + 1000 = 17000 → clamp → 16000
        assert calc_narrative_ir_max_tokens(200) == 16000

    def test_extreme_high_clamps_to_max(self):
        # 极端值 1000 sentences: 81000 → clamp → 16000
        assert calc_narrative_ir_max_tokens(1000) == 16000

    def test_negative_raises_value_error(self):
        import pytest
        with pytest.raises(ValueError, match="must be >= 0"):
            calc_narrative_ir_max_tokens(-1)


class TestConservativeRounding:
    """Verify estimate is always >= true token count (ceil semantics)."""

    def test_2_chinese_chars_not_truncated_to_zero(self):
        # 2/2.5 = 0.8; ceil=1 (NOT 0)
        assert estimate_tokens("中文") == 1

    def test_3_ascii_chars_not_truncated_to_zero(self):
        # 3/4 = 0.75; ceil=1 (NOT 0)
        assert estimate_tokens("abc") == 1
