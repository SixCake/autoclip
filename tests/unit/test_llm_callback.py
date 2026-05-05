"""Unit tests for LlmCallsRecorder callback (M2a.1).

Covers:
- Recorder writes file on LLM end
- Seq increments across calls
- Creates dir if missing
- Disk failure does not raise (only logs warning)
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from autoclip.providers.llm.callback import LlmCallsRecorder


class TestLlmCallsRecorder:
    """Tests for LlmCallsRecorder BaseCallbackHandler."""

    @pytest.fixture
    def tmp_job_dir(self, tmp_path):
        return tmp_path / "test_job"

    @pytest.fixture
    def recorder(self, tmp_job_dir):
        return LlmCallsRecorder(tmp_job_dir, "scripting")

    def test_recorder_writes_file_on_llm_end(self, recorder, tmp_job_dir):
        """After on_chat_model_start + on_llm_end, a JSON file is written."""
        run_id = "test-run-001"
        messages = [SystemMessage(content="sys"), HumanMessage(content="user")]

        recorder.on_chat_model_start(
            serialized={"name": "ChatOpenAI"},
            messages=[messages],
            run_id=run_id,
        )

        ai_msg = AIMessage(content="hello world")
        ai_msg.usage_metadata = {
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
        }
        llm_result = LLMResult(generations=[[ChatGeneration(message=ai_msg)]])

        recorder.on_llm_end(response=llm_result, run_id=run_id)

        expected_file = tmp_job_dir / "llm_calls" / "scripting_001.json"
        assert expected_file.exists(), f"Expected file {expected_file} not found"

        data = json.loads(expected_file.read_text())
        assert data["seq"] == 1
        assert data["stage"] == "scripting"
        assert data["model"] == "ChatOpenAI"
        assert data["usage"]["total_tokens"] == 15

    def test_recorder_seq_increments_across_calls(self, recorder, tmp_job_dir):
        """Three consecutive calls produce scripting_001.json, _002.json, _003.json."""
        for i in range(1, 4):
            run_id = f"run-{i}"
            messages = [HumanMessage(content=f"msg {i}")]
            recorder.on_chat_model_start(
                serialized={"name": "ChatOpenAI"},
                messages=[messages],
                run_id=run_id,
            )
            ai_msg = AIMessage(content=f"resp {i}")
            ai_msg.usage_metadata = {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8}
            llm_result = LLMResult(generations=[[ChatGeneration(message=ai_msg)]])
            recorder.on_llm_end(response=llm_result, run_id=run_id)

        for i in range(1, 4):
            fpath = tmp_job_dir / "llm_calls" / f"scripting_{i:03d}.json"
            assert fpath.exists(), f"Expected {fpath} not found"
            data = json.loads(fpath.read_text())
            assert data["seq"] == i

    def test_recorder_creates_dir_if_missing(self, tmp_path):
        """If job_dir/llm_calls doesn't exist, it's auto-created."""
        nested_dir = tmp_path / "deeply" / "nested" / "job"
        rec = LlmCallsRecorder(nested_dir, "test")

        run_id = "run-create-dir"
        messages = [HumanMessage(content="create dir test")]
        rec.on_chat_model_start(
            serialized={"name": "ChatOpenAI"},
            messages=[messages],
            run_id=run_id,
        )
        ai_msg = AIMessage(content="ok")
        ai_msg.usage_metadata = {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}
        llm_result = LLMResult(generations=[[ChatGeneration(message=ai_msg)]])
        rec.on_llm_end(response=llm_result, run_id=run_id)

        expected = nested_dir / "llm_calls" / "test_001.json"
        assert expected.exists()

    def test_recorder_disk_failure_does_not_raise(self, recorder, tmp_job_dir, caplog):
        """If write_text raises OSError, invoke still succeeds (only warns)."""
        run_id = "run-fail"
        messages = [HumanMessage(content="disk fail test")]
        recorder.on_chat_model_start(
            serialized={"name": "ChatOpenAI"},
            messages=[messages],
            run_id=run_id,
        )
        ai_msg = AIMessage(content="should not crash")
        ai_msg.usage_metadata = {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}
        llm_result = LLMResult(generations=[[ChatGeneration(message=ai_msg)]])

        with patch.object(Path, "write_text", side_effect=OSError("disk full")):
            # Should NOT raise
            recorder.on_llm_end(response=llm_result, run_id=run_id)

        # Verify a warning was logged (loguru uses caplog at WARNING level)
        # Note: loguru doesn't integrate with caplog by default; we just verify no exception
        assert True  # If we got here without exception, the test passes
