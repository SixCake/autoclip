"""Retry decorator for LLM output parsing layer (M2a.4).

Provides ``retry_with_repair`` decorator with exponential backoff.

Design notes:
- Complementary to LangChain ``ChatOpenAI(max_retries=2)`` which handles
  HTTP-layer failures. This decorator targets the application layer:
  JSON parsing / schema validation failures from LLM output.
- No new dependencies (stdlib + loguru only).
- Self-implemented for-loop instead of tenacity decorator to keep the
  surface area small (per M2a.1 dependency lock decision).
"""

from __future__ import annotations

import functools
import time
from collections.abc import Callable
from typing import Any, TypeVar

from loguru import logger

T = TypeVar("T")


def retry_with_repair(
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 10.0,
    backoff_factor: float = 2.0,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorate a callable with exponential-backoff retry.

    Args:
        max_attempts: Maximum number of attempts (must be >= 1). The first
            invocation counts as attempt 1, so ``max_attempts=3`` means up
            to 2 retries after the first failure.
        initial_delay: Delay (seconds) before first retry.
        max_delay: Cap on delay (seconds). Each retry doubles the delay
            until this cap.
        backoff_factor: Multiplier applied to delay between retries.

    Returns:
        A decorator that wraps the target callable.

    Behavior:
        - On success: return result immediately.
        - On exception: log warning + sleep + retry until ``max_attempts``.
        - On final failure: re-raise the LAST exception.
    """
    if max_attempts < 1:
        raise ValueError(f"max_attempts must be >= 1, got {max_attempts}")
    if initial_delay < 0:
        raise ValueError(f"initial_delay must be >= 0, got {initial_delay}")
    if max_delay < initial_delay:
        raise ValueError(
            f"max_delay ({max_delay}) must be >= initial_delay ({initial_delay})"
        )

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            delay = initial_delay
            last_exc: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:  # noqa: BLE001 - intentional broad catch for retry
                    last_exc = e
                    if attempt >= max_attempts:
                        logger.warning(
                            "retry_with_repair: {} failed after {} attempts; raising last exception ({}: {})",
                            func.__name__,
                            max_attempts,
                            type(e).__name__,
                            e,
                        )
                        raise
                    logger.warning(
                        "retry_with_repair: {} attempt {}/{} failed ({}: {}); sleeping {:.2f}s then retrying",
                        func.__name__,
                        attempt,
                        max_attempts,
                        type(e).__name__,
                        e,
                        delay,
                    )
                    time.sleep(delay)
                    delay = min(delay * backoff_factor, max_delay)
            # Unreachable: loop either returns or raises. Keep type-checker happy.
            assert last_exc is not None
            raise last_exc

        return wrapper

    return decorator
