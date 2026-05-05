"""Unit tests for LLM factory (M2a.1).

Covers:
- Default provider is deepseek (ChatOpenAI)
- Explicit dashscope returns ChatTongyi
- json_mode passes response_format
- Missing API key raises RuntimeError
- Callbacks are attached
"""

from pathlib import Path

import pytest
from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_openai import ChatOpenAI

from autoclip.providers.llm.factory import get_llm


class TestGetLlmFactory:
    """Tests for get_llm() factory function."""

    def test_get_llm_default_provider_is_deepseek(self, monkeypatch):
        """No provider arg + no env var → returns ChatOpenAI with deepseek-chat model."""
        # Ensure AUTOCLIP_LLM_PROVIDER is unset
        monkeypatch.delenv("AUTOCLIP_LLM_PROVIDER", raising=False)
        # Provide a dummy DEEPSEEK_API_KEY so init doesn't raise
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-dummy-key")

        llm = get_llm()

        assert isinstance(llm, ChatOpenAI)
        assert llm.model_name == "deepseek-chat"
        # ChatOpenAI stores base_url in openai_api_base attribute
        assert llm.openai_api_base == "https://api.deepseek.com/v1"

    def test_get_llm_dashscope_explicit(self, monkeypatch):
        """provider='dashscope' → returns ChatTongyi with qwen-plus model."""
        monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-dashscope-dummy")

        llm = get_llm(provider="dashscope")

        assert isinstance(llm, ChatTongyi)
        # ChatTongyi stores model name in model_name attribute
        assert llm.model_name == "qwen-plus"

    def test_get_llm_json_mode_passes_response_format(self, monkeypatch):
        """json_mode=True injects response_format into model_kwargs."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-dummy")

        llm = get_llm(json_mode=True)

        assert isinstance(llm, ChatOpenAI)
        assert llm.model_kwargs.get("response_format") == {"type": "json_object"}

    def test_get_llm_missing_api_key_raises(self, monkeypatch):
        """Missing DEEPSEEK_API_KEY when provider=deepseek raises RuntimeError."""
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("AUTOCLIP_LLM_PROVIDER", raising=False)

        with pytest.raises(RuntimeError) as exc_info:
            get_llm()

        assert "DEEPSEEK_API_KEY not set" in str(exc_info.value)

    def test_get_llm_with_callbacks_attaches(self, monkeypatch):
        """Passing callbacks list attaches them to the returned model."""
        from autoclip.providers.llm.callback import LlmCallsRecorder

        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-dummy")
        recorder = LlmCallsRecorder(Path("/tmp/test_job"), "test_stage")

        llm = get_llm(callbacks=[recorder])

        assert isinstance(llm, ChatOpenAI)
        # LangChain stores callbacks in .callbacks attribute
        assert recorder in llm.callbacks
