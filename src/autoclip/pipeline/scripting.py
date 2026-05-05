"""Scripting stage handler — M2a.6 LLM-driven plot outline + narrative IR + greedy binding.

Reference:
- design.md §8 (Scripting stage products: timeline.json)
- docs/plans/tasks/M2a-scripting-main.md §M2a.6
- M2a brainstorming Q4/Q6/Q7/Q8 → K3/K7/K8/K10 contract clauses

Responsibilities:
1. Load shots.json + asr.json + state.json (pull target_duration_sec + style_preset).
2. Compute full_text + timestamped_text; K7 entry check (>32k tokens raises).
3. Plot outline LLM call (DeepSeek primary; LangChain HTTP retry + repair retry).
4. Narrative IR LLM call (with plot_outline as character grounding).
5. Naive greedy binding (M2a.5 bind_naively).
6. Serialize timeline.json.

Progress milestones (K10 v0.6 — 4 收敛):
- 0.05  handler entry, files loaded
- 0.30  plot_outline LLM call DONE (response + parsed)
- 0.65  narrative_ir LLM call DONE (response + parsed; JSON repair if any)
- 0.95  binding DONE
- 1.00  DONE (set automatically by mark_stage(DONE) at end)

v0.6 修订: 进度从 8 数值收敛到 4 (删 START 拆分 + 删 0.65 dead milestone).
原 8 数值在 90min 视频 Scripting ~2.5min 下平均节点 18s, START/DONE 拆分对前端体验
几乎无差别. K10 契约弱化: progress 单调递增 + 至少含上述 4 个数值 + DONE=1.0.

Contract with PipelineRunner (per runner.py `_stage_entrypoint`):
- We do NOT wrap the body in try/except — entrypoint already catches and marks FAILED.
- We do NOT call mark_stage(RUNNING, progress=0.0) — entrypoint already did it.
- We DO actively call mark_stage(SCRIPT, DONE) at the end (clearer than relying on safety net).
- Cancellation signaled by raising ScriptingCancelledError.

K-clause contracts (M2a brainstorming v0.5 落地):
- K3: every LLM.invoke() goes through LlmCallsRecorder callback → llm_calls/scripting_*.json
- K7 (v0.6 双闸门): 输入 estimate_tokens(timestamped_text) > INPUT_TOKEN_BUDGET_K7 (90000)
       → raise NarrativeIRTooLargeError; 输出 narrative_ir max_tokens 按 target_sentences
       动态算 (calc_narrative_ir_max_tokens) 防 600s 档位 100% 失败
- K8: plot_outline / narrative_ir final failure → raise *Error (NO graceful fallback)
- K9: llm_calls/ written here; cleanup deferred to M3.6 (not this task)
- K10 (v0.6 收敛): 4 progress milestones (0.05/0.30/0.65/0.95) 单调递增, 末次 DONE=1.0
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger

from autoclip.algo.greedy_binder import BindingResult, bind_naively
from autoclip.algo.narrative_ir import NarrativeIR, PlotOutline
from autoclip.algo.shot_detector import Shot
from autoclip.pipeline.runner import register_stage_handler
from autoclip.pipeline.state import JobStateFile, Stage, StageStatus
from autoclip.prompts.narrative_ir import (
    build_narrative_ir_messages,
    parse_narrative_ir_response,
)
from autoclip.prompts.plot_outline import (
    build_plot_outline_messages,
    parse_plot_outline_response,
)
from autoclip.providers.llm import LlmCallsRecorder, get_llm
from autoclip.utils.json_repair import RepairFailedError, try_repair_json
from autoclip.utils.retry import retry_with_repair
from autoclip.utils.tokens import (
    INPUT_TOKEN_BUDGET_K7,
    calc_narrative_ir_max_tokens,
    estimate_tokens,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SHOTS_FILENAME = "shots.json"
ASR_FILENAME = "asr.json"
TIMELINE_FILENAME = "timeline.json"
STAGE_NAME = "scripting"  # used by LlmCallsRecorder filename prefix

# K7 (v0.6 双闸门): 输入闸门常量已迁至 utils/tokens.INPUT_TOKEN_BUDGET_K7 (90000);
# 输出闸门 narrative_ir max_tokens 改为按 target_sentences 动态算
# (calc_narrative_ir_max_tokens), 不再硬编码于此.

# Default plot_outline + narrative_ir LLM tuning (per design.md §8 / brainstorming Q3)
PLOT_OUTLINE_TEMPERATURE = 0.3
PLOT_OUTLINE_MAX_TOKENS = 2000
NARRATIVE_IR_TEMPERATURE = 0.7
# NARRATIVE_IR_MAX_TOKENS 删除 (v0.6) - 改为运行期 calc_narrative_ir_max_tokens(target_sentences)

# JSON dump style (match shots.json / asr.json / state.json)
_JSON_DUMP_KWARGS: dict[str, Any] = {
    "ensure_ascii": False,
    "indent": 2,
    "sort_keys": False,
}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ScriptingError(RuntimeError):
    """Base error for Scripting stage failures."""


class ScriptingCancelledError(ScriptingError):
    """Raised when `.cancel` flag is observed mid-stage."""


class NarrativeIRTooLargeError(ScriptingError):
    """K7: input timestamped_text exceeds 32k token budget; >2h video unsupported in M2a."""


class PlotOutlineError(ScriptingError):
    """K8: plot_outline LLM/parse failed terminally; stage→FAILED, no fallback (Q6=A)."""


class NarrativeIRError(ScriptingError):
    """K8: narrative_ir LLM/parse failed terminally; stage→FAILED, no fallback."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_cancel(state: JobStateFile, where: str) -> None:
    """Raise ScriptingCancelledError if user requested cancellation."""
    if state.is_cancelled():
        raise ScriptingCancelledError(f"cancelled before {where}")


def _load_shots(shots_path: Path) -> list[Shot]:
    """Read shots.json into list[Shot]. Raises ScriptingError on schema violation."""
    if not shots_path.exists():
        raise ScriptingError(
            f"required input missing: {shots_path} (Index stage M1.8 produces this)"
        )
    with shots_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    raw_shots = payload.get("shots", [])
    if not raw_shots:
        raise ScriptingError(f"shots.json contains 0 shots — Index stage produced empty output")
    return [
        Shot(idx=s["idx"], start_sec=float(s["start_sec"]), end_sec=float(s["end_sec"]))
        for s in raw_shots
    ]


def _load_asr(asr_path: Path) -> dict[str, Any]:
    """Read asr.json. Returns full payload (sentences + language + provider)."""
    if not asr_path.exists():
        raise ScriptingError(
            f"required input missing: {asr_path} (Index stage M1.8 produces this)"
        )
    with asr_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if "sentences" not in payload:
        raise ScriptingError(f"asr.json schema invalid: missing 'sentences' field")
    return payload


def _build_full_text(asr_payload: dict[str, Any]) -> str:
    """Concatenate sentence texts (no timestamps) for plot_outline input."""
    return "".join(s.get("text", "") for s in asr_payload["sentences"])


def _build_timestamped_text(asr_payload: dict[str, Any]) -> str:
    """Build timestamped script for narrative_ir input.

    Format: each sentence on its own line as `[start_sec-end_sec] text`.
    """
    lines = []
    for s in asr_payload["sentences"]:
        start = float(s.get("start_sec", 0.0))
        end = float(s.get("end_sec", 0.0))
        text = s.get("text", "")
        lines.append(f"[{start:.2f}-{end:.2f}] {text}")
    return "\n".join(lines)


def _video_duration_sec(shots: list[Shot]) -> float:
    """Return last shot's end_sec as proxy for total video duration."""
    return max(s.end_sec for s in shots) if shots else 0.0


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Atomic JSON write using tmp+rename (same pattern as state.json)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, **_JSON_DUMP_KWARGS)
        f.flush()
    tmp.replace(path)


# ---------------------------------------------------------------------------
# LLM call helpers (with M2a.4 retry_with_repair + JSON repair fallback)
# ---------------------------------------------------------------------------


def _invoke_llm_with_repair(
    llm: Any,
    messages: list,
    parse_fn,
    error_cls: type[Exception],
    label: str,
):
    """Invoke LLM, parse response, repair on JSON failure, retry up to 3 times.

    Args:
        llm: BaseChatModel from get_llm()
        messages: list[BaseMessage] from prompt builder
        parse_fn: callable(raw: str) -> Pydantic model (raises ValueError on schema fail)
        error_cls: terminal exception class to raise on final failure (PlotOutlineError / NarrativeIRError)
        label: human-readable label for logging (e.g. "plot_outline")

    Returns:
        Parsed result from parse_fn.

    Raises:
        error_cls: when all retries + repair attempts exhausted (K8 hard failure).
    """

    @retry_with_repair(max_attempts=3, initial_delay=1.0, max_delay=8.0, backoff_factor=2.0)
    def _attempt():
        ai_msg = llm.invoke(messages)
        raw = ai_msg.content if hasattr(ai_msg, "content") else str(ai_msg)
        try:
            return parse_fn(raw)
        except (ValueError, json.JSONDecodeError) as e:
            logger.warning(
                "[scripting] {} parse failed ({}); attempting JSON repair", label, e
            )
            try:
                # try_repair_json returns parsed JSON value (dict/list); parse_fn
                # expects a raw string, so re-serialize before re-parse.
                repaired_obj = try_repair_json(raw)
                return parse_fn(json.dumps(repaired_obj, ensure_ascii=False))
            except (RepairFailedError, ValueError, json.JSONDecodeError) as repair_err:
                # Re-raise as ValueError so retry_with_repair triggers another attempt
                raise ValueError(
                    f"{label} parse + repair both failed: {repair_err}"
                ) from repair_err

    try:
        return _attempt()
    except Exception as e:
        # Final failure → wrap in caller's terminal error class (K8)
        raise error_cls(
            f"{label} terminally failed after retries + repair: {e}"
        ) from e


# ---------------------------------------------------------------------------
# Stage handler
# ---------------------------------------------------------------------------


def run_scripting(job_dir: Path) -> None:
    """Stage handler entrypoint registered with `Stage.SCRIPT`."""
    state = JobStateFile(job_dir)

    shots_path = job_dir / SHOTS_FILENAME
    asr_path = job_dir / ASR_FILENAME
    timeline_path = job_dir / TIMELINE_FILENAME

    logger.info("[scripting] start job_dir={}", job_dir)

    # --- Step 0: load inputs (progress 0.05) ---
    state_data = state.load()
    target_duration_sec = int(state_data["target_duration_sec"])
    # style_preset reserved for M2b.5 multi-style support; M2a baseline always uses "plot_summary"
    style_preset = state_data.get("style_preset", "plot_summary")

    shots = _load_shots(shots_path)
    asr_payload = _load_asr(asr_path)
    full_text = _build_full_text(asr_payload)
    timestamped_text = _build_timestamped_text(asr_payload)
    video_duration_sec = _video_duration_sec(shots)

    logger.info(
        "[scripting] loaded: n_shots={} n_sentences={} video_dur={:.1f}s "
        "target_dur={}s style_preset={}",
        len(shots),
        len(asr_payload["sentences"]),
        video_duration_sec,
        target_duration_sec,
        style_preset,
    )
    state.mark_stage(Stage.SCRIPT, StageStatus.RUNNING, progress=0.05)

    # --- K7 输入闸门 check (v0.6: 32000 → 90000) ---
    est_tokens = estimate_tokens(timestamped_text)
    if est_tokens > INPUT_TOKEN_BUDGET_K7:
        raise NarrativeIRTooLargeError(
            f"input exceeds {INPUT_TOKEN_BUDGET_K7} token budget "
            f"(estimated {est_tokens} tokens); >4h video not supported in M2a"
        )
    logger.info("[scripting] K7 input gate OK: estimated {} tokens (budget {})",
                est_tokens, INPUT_TOKEN_BUDGET_K7)

    # --- Step 1: instantiate callback recorder (K3) ---
    recorder = LlmCallsRecorder(job_dir, stage=STAGE_NAME)

    # --- Step 2: plot_outline LLM call (v0.6: 删 0.10 START, 仅留 0.30 DONE) ---
    _check_cancel(state, "plot_outline_llm")
    logger.info("[scripting] plot_outline LLM call START")

    plot_llm = get_llm(
        json_mode=True,
        callbacks=[recorder],
        temperature=PLOT_OUTLINE_TEMPERATURE,
        max_tokens=PLOT_OUTLINE_MAX_TOKENS,
    )
    plot_messages = build_plot_outline_messages(full_text, video_duration_sec)
    plot_outline: PlotOutline = _invoke_llm_with_repair(
        plot_llm,
        plot_messages,
        parse_plot_outline_response,
        PlotOutlineError,
        "plot_outline",
    )
    state.mark_stage(Stage.SCRIPT, StageStatus.RUNNING, progress=0.30)
    logger.info(
        "[scripting] plot_outline DONE: title={!r} n_chars={} n_acts={}",
        plot_outline.title_guess,
        len(plot_outline.main_characters),
        len(plot_outline.key_acts),
    )

    # --- Step 3: narrative_ir LLM call (v0.6: 删 0.30 START + max_tokens 动态算) ---
    _check_cancel(state, "narrative_ir_llm")
    # K7 输出闸门: max_tokens 按 target_sentences 动态算 (修复 600s 档位 100% 失败)
    target_sentences = int(target_duration_sec / 6)
    ir_max_tokens = calc_narrative_ir_max_tokens(target_sentences)
    logger.info(
        "[scripting] narrative_ir LLM call START (target_sentences={} max_tokens={})",
        target_sentences, ir_max_tokens,
    )

    ir_llm = get_llm(
        json_mode=True,
        callbacks=[recorder],
        temperature=NARRATIVE_IR_TEMPERATURE,
        max_tokens=ir_max_tokens,
    )
    ir_messages = build_narrative_ir_messages(
        plot_outline.to_dict(), timestamped_text, float(target_duration_sec)
    )
    narrative_ir: NarrativeIR = _invoke_llm_with_repair(
        ir_llm,
        ir_messages,
        parse_narrative_ir_response,
        NarrativeIRError,
        "narrative_ir",
    )
    state.mark_stage(Stage.SCRIPT, StageStatus.RUNNING, progress=0.65)
    logger.info(
        "[scripting] narrative_ir DONE: n_paragraphs={} n_sentences={}",
        len(narrative_ir.paragraphs),
        narrative_ir.total_sentences(),
    )

    # --- Step 4: greedy binding (M2a.5) ---
    # v0.6: 删除独立的 0.65 "JSON repair done" 里程碑 (dead milestone, 已并入 narrative_ir DONE);
    # 删除 0.80 binding START 节点 (与 0.95 DONE 间隔太短, 用户感知不到).
    _check_cancel(state, "binding")
    logger.info("[scripting] binding START: n_sentences={} n_shots={}",
                narrative_ir.total_sentences(), len(shots))

    binding_result: BindingResult = bind_naively(narrative_ir, shots)
    state.mark_stage(Stage.SCRIPT, StageStatus.RUNNING, progress=0.95)
    logger.info(
        "[scripting] binding DONE: total={} fallback={} ratio={:.3f}",
        binding_result.total_count,
        binding_result.fallback_count,
        binding_result.fallback_ratio,
    )

    # --- Step 5: serialize timeline.json (v0.6: 加 target_duration_sec_estimate 字段) ---
    # 字数加权预估目标播放时长 (M3.2 TTS 实跑后回填真值改名 target_duration_sec).
    # 不污染 BoundSegment dataclass — algo 层不感知"目标时长"产品概念.
    total_chars = sum(len(seg.sentence_text) for seg in binding_result.segments) or 1
    timeline_payload = {
        "plot_outline": plot_outline.to_dict(),
        "narrative_ir": narrative_ir.to_dict(),
        "binding_stats": {
            "total_segments": binding_result.total_count,
            "fallback_count": binding_result.fallback_count,
            "fallback_ratio": binding_result.fallback_ratio,
        },
        "segments": [
            {
                "order_idx": idx,
                "paragraph_idx": seg.paragraph_idx,
                "sentence_idx": seg.sentence_idx,
                "sentence_text": seg.sentence_text,
                "source_start_sec": seg.source_start_sec,
                "source_end_sec": seg.source_end_sec,
                "duration_sec": seg.duration_sec,
                "source_shot_ids": list(seg.source_shot_ids),
                "binding_method": seg.binding_method.value,
                "target_duration_sec_estimate": (
                    len(seg.sentence_text) / total_chars * target_duration_sec
                ),
            }
            for idx, seg in enumerate(binding_result.segments)
        ],
    }
    _atomic_write_json(timeline_path, timeline_payload)
    logger.info("[scripting] timeline.json written: n_segments={}",
                len(timeline_payload["segments"]))

    # --- Step 6: mark DONE (progress=1.0 set automatically; v0.6: 仅 4 个 RUNNING 数值 0.05/0.30/0.65/0.95) ---
    state.mark_stage(Stage.SCRIPT, StageStatus.DONE)
    logger.info("[scripting] DONE job_dir={}", job_dir)


# Register on import (PipelineRunner imports this module via _STAGE_MODULES).
register_stage_handler(Stage.SCRIPT, run_scripting)
