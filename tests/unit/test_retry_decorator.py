"""Unit tests for retry_with_repair decorator (M2a.4)."""

import time
from unittest.mock import MagicMock

import pytest

from autoclip.utils.retry import retry_with_repair


class TestSuccessOnFirstAttempt:
    """Test that successful calls return immediately."""

    def test_first_attempt_success_returns_value(self):
        mock = MagicMock(return_value="ok")

        @retry_with_repair(max_attempts=3, initial_delay=0)
        def func():
            return mock()

        result = func()
        assert result == "ok"
        assert mock.call_count == 1


class TestSuccessOnSecondAttempt:
    """Test that retry recovers from transient failure."""

    def test_second_attempt_success(self):
        attempts = {"count": 0}

        @retry_with_repair(max_attempts=3, initial_delay=0)
        def func():
            attempts["count"] += 1
            if attempts["count"] < 2:
                raise ValueError("transient failure")
            return "recovered"

        result = func()
        assert result == "recovered"
        assert attempts["count"] == 2

    def test_third_attempt_success(self):
        attempts = {"count": 0}

        @retry_with_repair(max_attempts=3, initial_delay=0)
        def func():
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise RuntimeError("still failing")
            return "finally"

        result = func()
        assert result == "finally"
        assert attempts["count"] == 3


class TestAllAttemptsFail:
    """Test that final exception is re-raised after all attempts fail."""

    def test_all_attempts_fail_raises_last_exception(self):
        attempts = {"count": 0}

        @retry_with_repair(max_attempts=3, initial_delay=0)
        def func():
            attempts["count"] += 1
            raise ValueError(f"failure #{attempts['count']}")

        with pytest.raises(ValueError) as exc_info:
            func()

        assert attempts["count"] == 3
        assert "failure #3" in str(exc_info.value)

    def test_max_attempts_one_no_retry(self):
        attempts = {"count": 0}

        @retry_with_repair(max_attempts=1, initial_delay=0)
        def func():
            attempts["count"] += 1
            raise RuntimeError("fail")

        with pytest.raises(RuntimeError):
            func()
        assert attempts["count"] == 1


class TestPreservesFunctionMetadata:
    """Test that decorator preserves function name + docstring (functools.wraps)."""

    def test_wraps_preserves_name(self):
        @retry_with_repair(max_attempts=2, initial_delay=0)
        def my_function():
            """My docstring."""
            return 1

        assert my_function.__name__ == "my_function"
        assert my_function.__doc__ == "My docstring."


class TestArgumentsPassedThrough:
    """Test that decorator forwards args/kwargs correctly."""

    def test_args_forwarded(self):
        @retry_with_repair(max_attempts=2, initial_delay=0)
        def add(a, b):
            return a + b

        assert add(2, 3) == 5

    def test_kwargs_forwarded(self):
        @retry_with_repair(max_attempts=2, initial_delay=0)
        def greet(name="world"):
            return f"hello {name}"

        assert greet(name="autoclip") == "hello autoclip"


class TestInputValidation:
    """Test decorator factory parameter validation."""

    def test_max_attempts_zero_raises(self):
        with pytest.raises(ValueError, match="max_attempts must be"):
            retry_with_repair(max_attempts=0)

    def test_negative_initial_delay_raises(self):
        with pytest.raises(ValueError, match="initial_delay must be"):
            retry_with_repair(initial_delay=-1)

    def test_max_delay_smaller_than_initial_raises(self):
        with pytest.raises(ValueError, match="max_delay"):
            retry_with_repair(initial_delay=10, max_delay=1)


class TestExponentialBackoff:
    """Test that backoff delay grows exponentially up to max_delay."""

    def test_backoff_capped_at_max_delay(self, monkeypatch):
        sleeps: list[float] = []
        monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

        @retry_with_repair(max_attempts=4, initial_delay=1.0, max_delay=3.0, backoff_factor=2.0)
        def func():
            raise ValueError("fail")

        with pytest.raises(ValueError):
            func()

        # 3 sleeps before 4th attempt: 1.0, 2.0, min(4.0, 3.0)=3.0
        assert sleeps == [1.0, 2.0, 3.0]
