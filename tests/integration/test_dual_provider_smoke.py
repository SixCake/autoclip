"""Integration smoke tests for dual LLM providers (M2a.1).

Requires:
- DEEPSEEK_API_KEY env var set
- DASHSCOPE_API_KEY env var set
- RUN_INTEGRATION=1 env var set

Runs:
- DeepSeek: ask "1+1=?", verify response contains "2" and usage_metadata.total_tokens > 0
- Dashscope: same question, same verification
- Both write to {tmp_path}/llm_calls/smoke_001.json etc.
"""

import os
import pytest
from pathlib import Path

from langchain_core.messages import HumanMessage

from autoclip.providers.llm.factory import get_llm
from autoclip.providers.llm.callback import LlmCallsRecorder


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("RUN_INTEGRATION"),
    reason="Set RUN_INTEGRATION=1 to run integration tests",
)
class TestDualProviderSmoke:
    """Smoke tests for DeepSeek and dashscope providers."""

    @pytest.fixture
    def tmp_job_dir(self, tmp_path):
        return tmp_path / "smoke_test_job"

    def test_deepseek_smoke(self, tmp_job_dir):
        """DeepSeek provider returns correct answer and writes llm_calls file."""
        if not os.environ.get("DEEPSEEK_API_KEY"):
            pytest.skip("DEEPSEEK_API_KEY not set")

        recorder = LlmCallsRecorder(tmp_job_dir, "smoke")
        llm = get_llm(provider="deepseek", callbacks=[recorder])

        result = llm.invoke([HumanMessage(content="1+1=?")])

        assert "2" in result.content.lower(), f"Expected '2' in response, got: {result.content}"
        assert hasattr(result, "usage_metadata"), "AIMessage should have usage_metadata"
        assert result.usage_metadata["total_tokens"] > 0, "Should have non-zero token usage"

        # Verify llm_calls file was written
        call_file = tmp_job_dir / "llm_calls" / "smoke_001.json"
        assert call_file.exists(), f"Expected {call_file} to exist"

    def test_dashscope_smoke(self, tmp_job_dir):
        """Dashscope provider returns correct answer and writes llm_calls file."""
        if not os.environ.get("DASHSCOPE_API_KEY"):
            pytest.skip("DASHSCOPE_API_KEY not set")

        recorder = LlmCallsRecorder(tmp_job_dir, "smoke")
        llm = get_llm(provider="dashscope", callbacks=[recorder])

        result = llm.invoke([HumanMessage(content="1+1=?")])

        assert "2" in result.content.lower(), f"Expected '2' in response, got: {result.content}"
        assert hasattr(result, "usage_metadata"), "AIMessage should have usage_metadata"
        assert result.usage_metadata["total_tokens"] > 0, "Should have non-zero token usage"

        # Verify llm_calls file was written
        call_file = tmp_job_dir / "llm_calls" / "smoke_001.json"
        assert call_file.exists(), f"Expected {call_file} to exist"
