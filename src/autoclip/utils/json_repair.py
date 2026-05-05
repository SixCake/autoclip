"""JSON repair utilities for LLM output (M2a.4).

Provides ``try_repair_json`` to handle common LLM output failures:
1. Markdown fence stripping (```json ... ``` or ``` ... ```)
2. Extract first ``{...}`` or ``[...]`` block (LLM may add explanation text before/after)
3. Trailing comma fix (``,}`` / ``,]``)
4. Single quote -> double quote (simple cases only)
5. Multi-strategy candidate parsing - return first that parses

Design notes:
- No new dependencies (stdlib + loguru only)
- Deterministic algorithm, every step unit-testable
- Intentionally NOT using LangChain ``OutputFixingParser`` (B1=A decision)
"""

from __future__ import annotations

import json
import re
from typing import Any

from loguru import logger


class RepairFailedError(ValueError):
    """Raised when all repair strategies fail to produce parseable JSON."""

    def __init__(self, raw: str, attempts: list[str]) -> None:
        self.raw = raw
        self.attempts = attempts
        preview = raw[:200] + ("..." if len(raw) > 200 else "")
        super().__init__(
            f"Failed to repair JSON after {len(attempts)} strategies. "
            f"Raw preview: {preview!r}"
        )


# === Strategy 1: Markdown fence stripping ===

_FENCE_RE = re.compile(
    r"^\s*```(?:json|JSON)?\s*\n?(.*?)\n?```\s*$",
    re.DOTALL,
)


def _strip_fence(raw: str) -> str:
    """Strip markdown code fence (```json ... ``` or ``` ... ```)."""
    match = _FENCE_RE.match(raw.strip())
    if match:
        return match.group(1).strip()
    return raw


# === Strategy 2: Extract first {...} or [...] block ===

def _extract_json_block(raw: str) -> str:
    """Extract first balanced ``{...}`` or ``[...]`` block from raw text.

    Handles LLM responses with explanatory text before/after the JSON.
    Uses a simple bracket-counting state machine that respects string literals.
    """
    text = raw.strip()
    # Find first { or [
    start = -1
    open_char = ""
    close_char = ""
    for i, ch in enumerate(text):
        if ch == "{":
            start = i
            open_char, close_char = "{", "}"
            break
        if ch == "[":
            start = i
            open_char, close_char = "[", "]"
            break
    if start < 0:
        return text

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == open_char:
            depth += 1
        elif ch == close_char:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    # Unbalanced: return from start to end
    return text[start:]


# === Strategy 3: Trailing comma fix ===

_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


def _fix_trailing_comma(raw: str) -> str:
    """Remove trailing commas before } or ]."""
    return _TRAILING_COMMA_RE.sub(r"\1", raw)


# === Strategy 4: Single quote -> double quote ===

def _convert_single_quotes(raw: str) -> str:
    """Convert single-quoted strings to double-quoted (simple cases only).

    WARNING: This is a heuristic that only handles the common case where
    LLM emits Python-style ``{'key': 'value'}``. Does NOT handle escaped
    quotes inside strings - those cases will simply fail and another
    strategy will be tried.
    """
    # Skip if already contains double-quoted strings (likely valid JSON-ish)
    if '"' in raw and "'" not in raw:
        return raw
    # Naive replace: only if no double quotes at all (pure single-quote dict)
    if '"' not in raw and "'" in raw:
        return raw.replace("'", '"')
    return raw


# === Main entry ===

def try_repair_json(raw: str) -> Any:
    """Try multiple repair strategies; return first parseable JSON.

    Args:
        raw: Raw string from LLM (possibly with fence / explanation / minor errors).

    Returns:
        Parsed JSON value (dict / list / scalar).

    Raises:
        RepairFailedError: If all strategies fail.
        TypeError: If ``raw`` is not a str.
    """
    if not isinstance(raw, str):
        raise TypeError(f"raw must be str, got {type(raw).__name__}")

    attempts: list[str] = []

    # Strategy 0: try parsing raw directly (already valid JSON)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        attempts.append(f"raw: {e.msg}")

    # Build candidate pipeline
    s1 = _strip_fence(raw)
    if s1 != raw:
        try:
            return json.loads(s1)
        except json.JSONDecodeError as e:
            attempts.append(f"strip_fence: {e.msg}")

    s2 = _extract_json_block(s1)
    if s2 != s1:
        try:
            return json.loads(s2)
        except json.JSONDecodeError as e:
            attempts.append(f"extract_block: {e.msg}")

    s3 = _fix_trailing_comma(s2)
    if s3 != s2:
        try:
            return json.loads(s3)
        except json.JSONDecodeError as e:
            attempts.append(f"fix_trailing_comma: {e.msg}")

    s4 = _convert_single_quotes(s3)
    if s4 != s3:
        try:
            return json.loads(s4)
        except json.JSONDecodeError as e:
            attempts.append(f"convert_single_quotes: {e.msg}")

    # Last try: combined fix on extracted block
    combined = _convert_single_quotes(
        _fix_trailing_comma(_extract_json_block(_strip_fence(raw)))
    )
    try:
        result = json.loads(combined)
        logger.warning(
            "json_repair: combined strategy succeeded after individual strategies failed; "
            "attempts={}",
            attempts,
        )
        return result
    except json.JSONDecodeError as e:
        attempts.append(f"combined: {e.msg}")

    raise RepairFailedError(raw, attempts)
