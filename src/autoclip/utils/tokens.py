"""Token estimation utilities for LLM input budget enforcement.

Used by M2a.6 Scripting handler K7 entry check (NarrativeIRTooLargeError when
input exceeds 32k token budget; >2h video not supported in M2a baseline).

Estimation strategy (M2a baseline):
- Chinese-dominant text: avg 2.5 chars/token (DeepSeek + qwen tokenizers
  empirical ratio observed during M2a.1 brainstorming Q7 discussion).
- Pure ASCII text: avg 4 chars/token (closer to GPT family ratio).
- Mixed text: weighted average based on CJK character ratio.

Why not tiktoken/transformers tokenizer here:
- tiktoken is GPT-specific; DeepSeek + qwen use different BPE merges.
- Loading a real tokenizer adds ~200ms cold start + ~50MB RSS per worker
  process; M2a is OK with ±10% estimation error since K7 is a guardrail
  (32k budget vs ~5k typical 90min input).
- M2b can swap to provider-specific tokenizer if K7 false-positives surface.
"""

from __future__ import annotations


def _is_cjk(ch: str) -> bool:
    """Return True if char is in CJK Unified Ideographs block (U+4E00–U+9FFF).

    This intentionally undercounts (excludes CJK Compatibility / Extension blocks)
    because the goal is a conservative ratio, not Unicode-perfect classification.
    """
    return "\u4e00" <= ch <= "\u9fff"


def estimate_tokens(text: str) -> int:
    """Estimate LLM token count for a text string (M2a baseline heuristic).

    Args:
        text: Arbitrary input string. Empty → 0.

    Returns:
        Estimated token count, rounded up (math.ceil) — never under-reports for K7.

    Notes:
        - Chinese chars: 1 token per 2.5 chars (CJK-heavy text)
        - Other chars: 1 token per 4 chars (ASCII / Latin)
        - Mixed text: per-char weighted (avoids one-pass-counts-all bias)
    """
    if not isinstance(text, str):
        raise TypeError(f"estimate_tokens expects str, got {type(text).__name__}")
    if not text:
        return 0

    cjk_count = sum(1 for ch in text if _is_cjk(ch))
    ascii_count = len(text) - cjk_count

    # CJK ratio 2.5 chars/token; ASCII ratio 4 chars/token.
    # Use ceil-equivalent integer math so empty fragments don't truncate to 0
    # when the other class dominates.
    cjk_tokens = (cjk_count * 10 + 24) // 25  # ceil(cjk_count / 2.5)
    ascii_tokens = (ascii_count + 3) // 4      # ceil(ascii_count / 4)

    return cjk_tokens + ascii_tokens
