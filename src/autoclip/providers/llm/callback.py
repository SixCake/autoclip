"""LlmCallsRecorder: LangChain BaseCallbackHandler that writes each LLM call to disk."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage
from loguru import logger


class LlmCallsRecorder(BaseCallbackHandler):
    """Writes each LLM call to {job_dir}/llm_calls/{stage}_{seq:03d}.json."""

    def __init__(self, job_dir: Path, stage: str) -> None:
        self.job_dir = Path(job_dir)
        self.stage = stage
        self._seq = 0
        self._run_id_to_start: dict[str, dict] = {}
        # Ensure llm_calls directory exists
        (self.job_dir / "llm_calls").mkdir(parents=True, exist_ok=True)

    def on_chat_model_start(
        self,
        serialized: dict,
        messages: list[list[BaseMessage]],
        run_id: str,
        **kwargs,
    ) -> None:
        """Capture request start time and messages."""
        self._run_id_to_start[run_id] = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "messages": [
                {"role": msg.type if hasattr(msg, "type") else msg.__class__.__name__.lower().replace("message", ""), "content": msg.content}
                for msg_list in messages
                for msg in msg_list
            ],
            "model_name": serialized.get("name", "unknown"),
        }

    def on_llm_end(self, response, run_id: str, **kwargs) -> None:
        """Capture response and write to disk."""
        start_info = self._run_id_to_start.pop(run_id, {})
        if not start_info:
            logger.warning(f"LlmCallsRecorder: no start info for run_id={run_id}")
            return

        self._seq += 1
        seq_str = f"{self._seq:03d}"
        filename = f"{self.stage}_{seq_str}.json"
        filepath = self.job_dir / "llm_calls" / filename

        # Extract usage from response
        usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        response_text = ""
        try:
            # LangChain LLMResult structure
            if hasattr(response, "generations") and response.generations:
                gen = response.generations[0][0]  # First generation
                if hasattr(gen, "message") and gen.message:
                    msg = gen.message
                    response_text = msg.content if hasattr(msg, "content") else str(msg)
                    if hasattr(msg, "usage_metadata") and msg.usage_metadata:
                        usage = {
                            "input_tokens": msg.usage_metadata.get("input_tokens", 0),
                            "output_tokens": msg.usage_metadata.get("output_tokens", 0),
                            "total_tokens": msg.usage_metadata.get("total_tokens", 0),
                        }
        except Exception as e:
            logger.warning(f"LlmCallsRecorder: failed to extract usage: {e}")

        ended_at = datetime.now(timezone.utc).isoformat()
        started_at_str = start_info.get("started_at", "")
        duration_sec = 0.0
        try:
            if started_at_str:
                started_dt = datetime.fromisoformat(started_at_str)
                ended_dt = datetime.fromisoformat(ended_at)
                duration_sec = (ended_dt - started_dt).total_seconds()
        except Exception:
            pass

        record = {
            "seq": self._seq,
            "stage": self.stage,
            "model": start_info.get("model_name", "unknown"),
            "messages": start_info.get("messages", []),
            "response": response_text,
            "usage": usage,
            "started_at": started_at_str,
            "ended_at": ended_at,
            "duration_sec": round(duration_sec, 3),
        }

        try:
            filepath.write_text(json.dumps(record, indent=2, ensure_ascii=False))
        except OSError as e:
            logger.warning(f"LlmCallsRecorder: failed to write {filepath}: {e}")
            # Do NOT raise — observability should not block business logic
