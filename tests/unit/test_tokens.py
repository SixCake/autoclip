"""Unit tests for autoclip.utils.tokens.estimate_tokens — M2a.6 K7 guardrail input.

Coverage:
- Empty / non-str / type validation
- Pure CJK (Chinese-only) ratio ≈ chars / 2.5
- Pure ASCII ratio ≈ chars / 4
- Mixed CJK + ASCII (per-char weighting, not one-pass-counts-all)
- Conservative rounding (always ceil — never under-report for K7)
- K7 boundary scenarios: under / at / above 32k token budget
"""

from __future__ import annotations

import pytest

from autoclip.utils.tokens import estimate_tokens


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


class TestK7Boundary:
    """K7 = 32000 tokens budget; verify estimator behaves predictably near threshold."""

    def test_under_budget_chinese(self):
        # 5000 中文 ≈ 2000 tokens (well under 32k) — typical 90min ASR
        result = estimate_tokens("中" * 5000)
        assert result == 2000
        assert result < 32000

    def test_exactly_at_budget_chinese(self):
        # 80000 中文 = 32000 tokens exactly
        result = estimate_tokens("中" * 80000)
        assert result == 32000

    def test_above_budget_chinese_triggers_k7(self):
        # 80003 中文 → ceil(80003/2.5) = 32002 > 32000
        result = estimate_tokens("中" * 80003)
        assert result == 32002
        assert result > 32000


class TestConservativeRounding:
    """Verify estimate is always >= true token count (ceil semantics)."""

    def test_2_chinese_chars_not_truncated_to_zero(self):
        # 2/2.5 = 0.8; ceil=1 (NOT 0)
        assert estimate_tokens("中文") == 1

    def test_3_ascii_chars_not_truncated_to_zero(self):
        # 3/4 = 0.75; ceil=1 (NOT 0)
        assert estimate_tokens("abc") == 1
