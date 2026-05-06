"""Tests for autoclip.config.Settings."""

import pytest
from pydantic import SecretStr

from autoclip.config import Settings, get_settings


def test_settings_loads_from_env(monkeypatch, tmp_path):
    """Settings should load all required fields from environment variables."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "test_data"))
    monkeypatch.setenv("WHISPER_MODEL_SIZE", "medium")
    monkeypatch.setenv("WHISPER_DEVICE", "cpu")
    monkeypatch.setenv("WHISPER_COMPUTE_TYPE", "int8")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test123")
    monkeypatch.setenv("QWEN_TTS_MODEL", "qwen3-tts-instruct-flash")
    monkeypatch.setenv("MAX_CONCURRENT_JOBS", "3")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    settings = Settings(_env_file=None)  # Skip .env, use only env vars

    assert settings.data_dir == tmp_path / "test_data"
    assert settings.whisper_model_size == "medium"
    assert settings.whisper_device == "cpu"
    assert settings.whisper_compute_type == "int8"
    assert settings.dashscope_api_key.get_secret_value() == "sk-test123"
    assert settings.qwen_tts_model == "qwen3-tts-instruct-flash"
    assert settings.max_concurrent_jobs == 3
    assert settings.log_level == "DEBUG"


def test_whisper_defaults():
    """Whisper config should have sensible defaults (large-v3 / auto / default)."""
    settings = Settings(_env_file=None)
    assert settings.whisper_model_size == "large-v3"
    assert settings.whisper_device == "auto"
    assert settings.whisper_compute_type == "default"


def test_data_dir_auto_created(monkeypatch, tmp_path):
    """get_settings() should auto-create nested data_dir."""
    nested = tmp_path / "deep" / "nested" / "data"
    monkeypatch.setenv("DATA_DIR", str(nested))

    assert not nested.exists()
    get_settings()
    assert nested.exists()
    assert nested.is_dir()


def test_secrets_are_secret_str():
    """All credentials must be wrapped in SecretStr (no accidental logging).

    Note: whisper_* and qwen_tts_model are plain str (no credentials, just config).
    """
    settings = Settings(_env_file=None)
    assert isinstance(settings.dashscope_api_key, SecretStr)
    # whisper_* + qwen_tts_model are plain str (no secret semantics)
    assert isinstance(settings.whisper_model_size, str)
    assert isinstance(settings.whisper_device, str)
    assert isinstance(settings.qwen_tts_model, str)


def test_no_legacy_aliyun_asr_fields():
    """v0.4: aliyun_asr_app_key / aliyun_asr_token must be removed (ADR-004 三度修订)."""
    settings = Settings(_env_file=None)
    assert not hasattr(settings, "aliyun_asr_app_key"), (
        "aliyun_asr_app_key was removed in v0.4 (Part IV §21)"
    )
    assert not hasattr(settings, "aliyun_asr_token"), (
        "aliyun_asr_token was removed in v0.4 (Part IV §21)"
    )


def test_no_legacy_volcengine_fields():
    """Session 35: volcengine_tts_* fields removed when swapping to Qwen-TTS."""
    settings = Settings(_env_file=None)
    assert not hasattr(settings, "volcengine_tts_token"), (
        "volcengine_tts_token removed in Session 35 (replaced by Qwen-TTS)"
    )
    assert not hasattr(settings, "volcengine_tts_app_id"), (
        "volcengine_tts_app_id removed in Session 35 (replaced by Qwen-TTS)"
    )


def test_qwen_tts_model_default():
    """Default Qwen-TTS model must be the instruct variant (Session 35)."""
    settings = Settings(_env_file=None)
    assert settings.qwen_tts_model == "qwen3-tts-instruct-flash"


def test_max_concurrent_jobs_validation(monkeypatch):
    """max_concurrent_jobs must be 1-10."""
    monkeypatch.setenv("MAX_CONCURRENT_JOBS", "0")
    with pytest.raises(ValueError):
        Settings(_env_file=None)

    monkeypatch.setenv("MAX_CONCURRENT_JOBS", "11")
    with pytest.raises(ValueError):
        Settings(_env_file=None)
