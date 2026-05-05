"""Assembly stage handler — TTS synthesis + duration adapter.

Responsibilities:
1. Load timeline.json (segments + narrative_ir sentences)
2. Flatten all sentences in order → batch TTS synthesis
3. Duration adapter: if total TTS duration deviates >20% from target, warn
4. Write assembly.json with per-sentence TTS paths + durations

Progress milestones:
- 0.1  files loaded
- 0.6  TTS batch complete
- 0.95 assembly.json written
- 1.0  DONE
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ..pipeline.runner import register_stage_handler
from ..pipeline.state import JobStateFile, Stage, StageStatus
from ..providers.tts import VolcengineTTSProvider

logger = logging.getLogger(__name__)

_DURATION_DEVIATION_WARN_THRESHOLD = 0.20  # 20%


def _load_sentences_from_timeline(timeline: dict) -> list[dict]:
    """Extract ordered sentence list from timeline.json narrative_ir paragraphs."""
    sentences: list[dict] = []
    narrative_ir = timeline.get("narrative_ir", {})
    for paragraph in narrative_ir.get("paragraphs", []):
        for sentence in paragraph.get("sentences", []):
            sentences.append({
                "sentence_idx": sentence["sentence_idx"],
                "text": sentence["text"],
            })
    # Sort by sentence_idx to guarantee order
    sentences.sort(key=lambda s: s["sentence_idx"])
    return sentences


def run_assembly(job_dir: Path) -> None:
    """Assembly stage: TTS synthesis for all narrative sentences."""
    state = JobStateFile(job_dir)

    # --- Load timeline.json ---
    timeline_path = job_dir / "timeline.json"
    if not timeline_path.exists():
        raise FileNotFoundError(f"timeline.json not found in {job_dir}")

    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    state.mark_stage(Stage.ASSEMBLY, StageStatus.RUNNING, progress=0.1)

    # Extract target_duration_sec from state
    state_data = state.load()
    target_duration_sec = state_data.get("target_duration_sec", 90)

    # Flatten sentences
    sentences = _load_sentences_from_timeline(timeline)
    if not sentences:
        raise ValueError("No sentences found in timeline.json narrative_ir")

    logger.info("[assembly] Found %d sentences to synthesize", len(sentences))

    # TTS output dir
    tts_dir = job_dir / "tts"
    tts_dir.mkdir(parents=True, exist_ok=True)

    # --- Batch TTS synthesis ---
    provider = VolcengineTTSProvider()
    logger.info("[assembly] Using TTS provider: %s", provider.name)
    tts_result = provider.synthesize_batch(sentences, tts_dir)
    state.mark_stage(Stage.ASSEMBLY, StageStatus.RUNNING, progress=0.6)

    # Duration adapter: warn if deviation >20%
    total_tts_duration = tts_result.total_duration_sec
    if target_duration_sec > 0:
        deviation = abs(total_tts_duration - target_duration_sec) / target_duration_sec
        if deviation > _DURATION_DEVIATION_WARN_THRESHOLD:
            logger.warning(
                "[assembly] TTS duration %.1fs deviates %.0f%% from target %ds — "
                "consider adjusting sentence count",
                total_tts_duration, deviation * 100, target_duration_sec,
            )
        else:
            logger.info(
                "[assembly] TTS duration %.1fs vs target %ds (deviation %.0f%%) — OK",
                total_tts_duration, target_duration_sec, deviation * 100,
            )

    # Build assembly.json payload
    assembly_payload = {
        "total_tts_duration_sec": total_tts_duration,
        "target_duration_sec": target_duration_sec,
        "tts_provider": provider.name,
        "sentences": [
            {
                "sentence_idx": seg.sentence_idx,
                "text": seg.text,
                "audio_path": str(seg.audio_path.relative_to(job_dir)),
                "actual_duration_sec": seg.actual_duration_sec,
            }
            for seg in tts_result.segments
        ],
    }

    assembly_path = job_dir / "assembly.json"
    assembly_path.write_text(
        json.dumps(assembly_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    state.mark_stage(Stage.ASSEMBLY, StageStatus.RUNNING, progress=0.95)
    logger.info("[assembly] assembly.json written: %d sentences, total %.1fs", len(sentences), total_tts_duration)

    state.mark_stage(Stage.ASSEMBLY, StageStatus.DONE)


# Register handler when module is imported
register_stage_handler(Stage.ASSEMBLY, run_assembly)
