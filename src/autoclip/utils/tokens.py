"""Token estimation utilities for LLM input budget enforcement.

Used by M2a.6 Scripting handler K7 entry check (NarrativeIRTooLargeError when
input exceeds 90k token budget; >4h video not supported in M2a baseline).

Also exposes calc_narrative_ir_max_tokens(target_sentences) for the K7 output
gate — dynamic max_tokens calculation per target_duration_sec档位 (v0.6 双闸门).

Estimation strategy (M2a baseline):
- Chinese-dominant text: avg 2.5 chars/token (DeepSeek + qwen tokenizers
  empirical ratio observed during M2a.1 brainstorming Q7 discussion).
- Pure ASCII text: avg 4 chars/token (closer to GPT family ratio).
- Mixed text: weighted average based on CJK character ratio.

Why not tiktoken/transformers tokenizer here:
- tiktoken is GPT-specific; DeepSeek + qwen use different BPE merges.
- Loading a real tokenizer adds ~200ms cold start + ~50MB RSS per worker
  process; M2a is OK with ±10% estimation error since K7 is a guardrail
  (90k budget vs ~18k typical 90min input — wide safety margin).
- M2b can swap to provider-specific tokenizer if K7 false-positives surface.

v0.6 修订 (adhoc self-review, 2026-05-05):
- TOKEN_BUDGET_K7 (32000) 改名为 INPUT_TOKEN_BUDGET_K7 + 数值升至 90000
  原因: 32k 在 M2a 是死分支 (DeepSeek 128k context + ASR 截 40k 字符 ≈ 18k tokens
  总输入, 永远到不了 32k); 真正瓶颈是输出 max_tokens, 见 calc_narrative_ir_max_tokens()
- 新增 calc_narrative_ir_max_tokens() — 修复 600s 档位 100% 失败的 P0 bug
  (硬编码 8000 max_tokens 在 100 句目标下永远截断 → JSON 不完整 → repair 失败 → FAILED)
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



# ---------------------------------------------------------------------------
# K7 双闸门 (v0.6) — 输入闸门 + 输出闸门
# ---------------------------------------------------------------------------

# 输入闸门: DeepSeek 128k context window 留 30k 给输出的安全水位.
# 触发场景: ~4h+ 视频 (90k tokens ≈ 225k CJK 字符 ≈ 4 小时密集对白).
# v0.6 之前 = 32000, 实际从未触发 (M2a baseline 测试视频均 < 5k tokens).
INPUT_TOKEN_BUDGET_K7 = 90000

# 输出闸门动态参数 (calc_narrative_ir_max_tokens 公式系数)
_OUTPUT_TOKEN_PER_SENTENCE = 80   # M2a v0.6: prompt 删 evidence_keywords 后每句 ~80 token
_OUTPUT_TOKEN_OVERHEAD = 1000     # paragraph 包裹 + topic 字段 + JSON 结构 overhead
_OUTPUT_TOKEN_MIN = 2000          # clamp lower: 防 10s 档位算出 800 不够
_OUTPUT_TOKEN_MAX = 16000         # clamp upper: 防千秒级档位超 DeepSeek 输出上限


def calc_narrative_ir_max_tokens(target_sentences: int) -> int:
    """Compute max_tokens for narrative_ir LLM call (K7 输出闸门).

    Args:
        target_sentences: Estimated sentence count = int(target_duration_sec / 6).

    Returns:
        Clamped max_tokens value in [_OUTPUT_TOKEN_MIN, _OUTPUT_TOKEN_MAX].

    Examples:
        - target_sentences=10  (60s 档位):  10*80 + 1000 = 1800  → clamp → 2000
        - target_sentences=50  (300s 档位): 50*80 + 1000 = 5000  → 5000
        - target_sentences=100 (600s 档位): 100*80 + 1000 = 9000 → 9000
        - target_sentences=200 (1200s档位): 200*80 + 1000 = 17000 → clamp → 16000

    M2b.5 prompt v2 加回 evidence_keywords 后, 系数应回升至 ~120
    (在 M2b.5 实施时同步更新此处常量, 见 docs/plans/tasks/M2b-scripting-robust.md §M2b.5 v0.6).
    """
    if target_sentences < 0:
        raise ValueError(f"target_sentences must be >= 0, got {target_sentences}")
    raw = target_sentences * _OUTPUT_TOKEN_PER_SENTENCE + _OUTPUT_TOKEN_OVERHEAD
    return max(_OUTPUT_TOKEN_MIN, min(raw, _OUTPUT_TOKEN_MAX))
