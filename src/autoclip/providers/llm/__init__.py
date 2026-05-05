"""LLM providers via LangChain BaseChatModel abstraction.

Exports:
    get_llm: Factory function returning DeepSeek (primary) or dashscope (fallback).
    LlmCallsRecorder: BaseCallbackHandler that writes each call to {job_dir}/llm_calls/.
"""

from autoclip.providers.llm.factory import get_llm
from autoclip.providers.llm.callback import LlmCallsRecorder

__all__ = ["get_llm", "LlmCallsRecorder"]
