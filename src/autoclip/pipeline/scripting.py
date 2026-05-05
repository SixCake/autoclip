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

Progress milestones (K10 — 8 fine-grained):
- 0.05  handler entry, files loaded
- 0.10  plot_outline LLM call START (sending request)
- 0.25  plot_outline LLM call DONE (response + parsed)
- 0.30  narrative_ir LLM call START
- 0.60  narrative_ir LLM call DONE
- 0.65  JSON repair chain done (recorded as separate milestone whether or not triggered)
- 0.80  binding START
- 0.95  binding DONE
- 1.00  timeline.json written (DONE marked at end)

Contract with PipelineRunner (per runner.py `_stage_entrypoint`):
- We do NOT wrap the body in try/except — entrypoint already catches and marks FAILED.
- We do NOT call mark_stage(RUNNING, progress=0.0) — entrypoint already did it.
- We DO actively call mark_stage(SCRIPT, DONE) at the end (clearer than relying on safety net).
- Cancellation signaled by raising ScriptingCancelledError.

K-clause contracts (M2a brainstorming v0.5 落地):
- K3: every LLM.invoke() goes through LlmCallsRecorder callback → llm_calls/scripting_*.json
- K7: estimate_tokens(timestamped_text) > 32000 → raise NarrativeIRTooLargeError
- K8: plot_outline / narrative_ir final failure → raise *Error (NO graceful fallback)
- K9: llm_calls/ written here; cleanup deferred to M3.6 (not this task)
- K10: 8 progress milestones strictly ordered, verified by unit test
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
from autoclip.utils.tokens import estimate_tokens

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SHOTS_FILENAME = "shots.json"
ASR_FILENAME = "asr.json"
TIMELINE_FILENAME = "timeline.json"
STAGE_NAME = "scripting"  # used by LlmCallsRecorder filename prefix

# K7 entry budget (tokens). >2h video typically blows this; M2b/M3 will sharded.
TOKEN_BUDGET_K7 = 32000

# Default plot_outline + narrative_ir LLM tuning (per design.md §8 / brainstorming Q3)
PLOT_OUTLINE_TEMPERATURE = 0.3
PLOT_OUTLINE_MAX_TOKENS = 2000
NARRATIVE_IR_TEMPERATURE = 0.7
NARRATIVE_IR_MAX_TOKENS = 8000

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

    # --- K7 entry check ---
    est_tokens = estimate_tokens(timestamped_text)
    if est_tokens > TOKEN_BUDGET_K7:
        raise NarrativeIRTooLargeError(
            f"input exceeds {TOKEN_BUDGET_K7} token budget "
            f"(estimated {est_tokens} tokens); >2h video not supported in M2a"
        )
    logger.info("[scripting] K7 check OK: estimated {} tokens", est_tokens)

    # --- Step 1: instantiate callback recorder (K3) ---
    recorder = LlmCallsRecorder(job_dir, stage=STAGE_NAME)

    # --- Step 2: plot_outline LLM call ---
    _check_cancel(state, "plot_outline_llm")
    state.mark_stage(Stage.SCRIPT, StageStatus.RUNNING, progress=0.10)
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
    state.mark_stage(Stage.SCRIPT, StageStatus.RUNNING, progress=0.25)
    logger.info(
        "[scripting] plot_outline DONE: title={!r} n_chars={} n_acts={}",
        plot_outline.title_guess,
        len(plot_outline.main_characters),
        len(plot_outline.key_acts),
    )

    # --- Step 3: narrative_ir LLM call ---
    _check_cancel(state, "narrative_ir_llm")
    state.mark_stage(Stage.SCRIPT, StageStatus.RUNNING, progress=0.30)
    logger.info("[scripting] narrative_ir LLM call START")

    ir_llm = get_llm(
        json_mode=True,
        callbacks=[recorder],
        temperature=NARRATIVE_IR_TEMPERATURE,
        max_tokens=NARRATIVE_IR_MAX_TOKENS,
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
    state.mark_stage(Stage.SCRIPT, StageStatus.RUNNING, progress=0.60)
    logger.info(
        "[scripting] narrative_ir DONE: n_paragraphs={} n_sentences={}",
        len(narrative_ir.paragraphs),
        narrative_ir.total_sentences(),
    )

    # --- Step 4: JSON repair chain milestone (recorded regardless of triggered) ---
    state.mark_stage(Stage.SCRIPT, StageStatus.RUNNING, progress=0.65)

    # --- Step 5: greedy binding (M2a.5) ---
    _check_cancel(state, "binding")
    state.mark_stage(Stage.SCRIPT, StageStatus.RUNNING, progress=0.80)
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

    # --- Step 6: serialize timeline.json (progress 1.0 via DONE) ---
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
            }
            for idx, seg in enumerate(binding_result.segments)
        ],
    }
    _atomic_write_json(timeline_path, timeline_payload)
    logger.info("[scripting] timeline.json written: n_segments={}",
                len(timeline_payload["segments"]))

    # --- Step 7: mark DONE (progress=1.0 set automatically) ---
    state.mark_stage(Stage.SCRIPT, StageStatus.DONE)
    logger.info("[scripting] DONE job_dir={}", job_dir)


# Register on import (PipelineRunner imports this module via _STAGE_MODULES).
register_stage_handler(Stage.SCRIPT, run_scripting)
