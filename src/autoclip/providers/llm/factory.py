"""LLM factory: DeepSeek primary + dashscope fallback via LangChain."""

from __future__ import annotations

import os
from typing import Literal

from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI


def get_llm(
    provider: Literal["deepseek", "dashscope"] | None = None,
    *,
    json_mode: bool = False,
    callbacks: list[BaseCallbackHandler] | None = None,
    temperature: float = 0.3,
    max_tokens: int = 2000,
    **model_kwargs,
) -> BaseChatModel:
    """Return a LangChain BaseChatModel instance.

    Args:
        provider: "deepseek" (default, reads AUTOCLIP_LLM_PROVIDER env var) or "dashscope".
        json_mode: If True, inject response_format={"type":"json_object"} into model_kwargs.
        callbacks: List of BaseCallbackHandler instances (e.g. LlmCallsRecorder).
        temperature: Sampling temperature.
        max_tokens: Max output tokens.
        **model_kwargs: Extra kwargs passed to the underlying ChatModel.

    Returns:
        BaseChatModel instance (ChatOpenAI for deepseek, ChatTongyi for dashscope).

    Raises:
        RuntimeError: If required API key env var is missing.
    """
    # Resolve provider from arg or env var
    if provider is None:
        provider = os.environ.get("AUTOCLIP_LLM_PROVIDER", "deepseek")

    # Prepare common model_kwargs
    final_model_kwargs = dict(model_kwargs)
    if json_mode:
        final_model_kwargs["response_format"] = {"type": "json_object"}

    if provider == "deepseek":
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise RuntimeError(
                "DEEPSEEK_API_KEY not set; cannot init deepseek provider. "
                "Set it via environment variable."
            )
        return ChatOpenAI(
            model="deepseek-chat",
            base_url="https://api.deepseek.com/v1",
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=2,
            callbacks=callbacks or [],
            model_kwargs=final_model_kwargs,
        )
    elif provider == "dashscope":
        api_key = os.environ.get("DASHSCOPE_API_KEY")
        if not api_key:
            raise RuntimeError(
                "DASHSCOPE_API_KEY not set; cannot init dashscope provider. "
                "Set it via environment variable."
            )
        return ChatTongyi(
            model="qwen-plus",
            api_key=api_key,
            temperature=temperature,
            max_retries=2,
            callbacks=callbacks or [],
            model_kwargs=final_model_kwargs,
        )
    else:
        raise ValueError(f"Unknown provider: {provider}. Must be 'deepseek' or 'dashscope'.")
