"""Unit tests for json_repair (M2a.4)."""

import pytest

from autoclip.utils.json_repair import RepairFailedError, try_repair_json


class TestAlreadyValidJSON:
    """Test that already-valid JSON is returned as-is."""

    def test_simple_object(self):
        result = try_repair_json('{"a": 1}')
        assert result == {"a": 1}

    def test_nested_object(self):
        result = try_repair_json('{"a": {"b": [1, 2, 3]}}')
        assert result == {"a": {"b": [1, 2, 3]}}

    def test_simple_array(self):
        result = try_repair_json('[1, 2, 3]')
        assert result == [1, 2, 3]


class TestFenceStripping:
    """Test markdown fence stripping (Strategy 1)."""

    def test_fence_with_json_lang(self):
        raw = '```json\n{"a": 1}\n```'
        result = try_repair_json(raw)
        assert result == {"a": 1}

    def test_fence_without_lang(self):
        raw = '```\n{"a": 1}\n```'
        result = try_repair_json(raw)
        assert result == {"a": 1}

    def test_fence_uppercase_json(self):
        raw = '```JSON\n{"key": "value"}\n```'
        result = try_repair_json(raw)
        assert result == {"key": "value"}

    def test_fence_with_surrounding_whitespace(self):
        raw = '   \n```json\n{"a": 1}\n```\n   '
        result = try_repair_json(raw)
        assert result == {"a": 1}


class TestExtractJsonBlock:
    """Test extraction of {...} or [...] from surrounding text (Strategy 2)."""

    def test_text_before_json(self):
        raw = 'Here is the answer: {"a": 1}'
        result = try_repair_json(raw)
        assert result == {"a": 1}

    def test_text_after_json(self):
        raw = '{"a": 1} (this is the result)'
        result = try_repair_json(raw)
        assert result == {"a": 1}

    def test_text_before_and_after(self):
        raw = 'Sure! Here you go:\n{"answer": 42}\nLet me know if you need more.'
        result = try_repair_json(raw)
        assert result == {"answer": 42}

    def test_extract_array_from_text(self):
        raw = 'The list: [1, 2, 3] (done)'
        result = try_repair_json(raw)
        assert result == [1, 2, 3]

    def test_braces_inside_string_literal(self):
        # Ensure depth counter respects string literals
        raw = 'Wrapped: {"text": "hello {world}"}'
        result = try_repair_json(raw)
        assert result == {"text": "hello {world}"}


class TestTrailingComma:
    """Test trailing comma fix (Strategy 3)."""

    def test_trailing_comma_in_object(self):
        raw = '{"a": 1, "b": 2,}'
        result = try_repair_json(raw)
        assert result == {"a": 1, "b": 2}

    def test_trailing_comma_in_array(self):
        raw = '[1, 2, 3,]'
        result = try_repair_json(raw)
        assert result == [1, 2, 3]

    def test_trailing_comma_with_text_and_fence(self):
        raw = 'Here:\n```json\n{"a": 1, "b": [1, 2,],}\n```'
        result = try_repair_json(raw)
        assert result == {"a": 1, "b": [1, 2]}


class TestSingleQuotes:
    """Test single-quote -> double-quote conversion (Strategy 4)."""

    def test_simple_single_quote_dict(self):
        raw = "{'a': 1, 'b': 2}"
        result = try_repair_json(raw)
        assert result == {"a": 1, "b": 2}

    def test_single_quote_with_text_around(self):
        raw = "Result: {'key': 'value'}"
        result = try_repair_json(raw)
        assert result == {"key": "value"}


class TestUnrepairable:
    """Test that unrepairable input raises RepairFailedError."""

    def test_completely_invalid(self):
        with pytest.raises(RepairFailedError) as exc_info:
            try_repair_json("this is not json at all <<<>>>")
        assert "Failed to repair JSON" in str(exc_info.value)
        assert len(exc_info.value.attempts) >= 1

    def test_empty_string(self):
        with pytest.raises(RepairFailedError):
            try_repair_json("")

    def test_severely_malformed(self):
        # Mismatched brackets that no strategy can fix
        with pytest.raises(RepairFailedError):
            try_repair_json("{abc: not_quoted, more_garbage @@@}")


class TestTypeValidation:
    """Test input type validation."""

    def test_non_string_raises_typeerror(self):
        with pytest.raises(TypeError):
            try_repair_json(123)  # type: ignore[arg-type]

    def test_none_raises_typeerror(self):
        with pytest.raises(TypeError):
            try_repair_json(None)  # type: ignore[arg-type]


class TestRepairFailedErrorAttrs:
    """Test that RepairFailedError carries useful attributes."""

    def test_error_has_raw_and_attempts(self):
        try:
            try_repair_json("not json garbage")
        except RepairFailedError as e:
            assert e.raw == "not json garbage"
            assert isinstance(e.attempts, list)
            assert len(e.attempts) >= 1
        else:
            pytest.fail("Expected RepairFailedError")
