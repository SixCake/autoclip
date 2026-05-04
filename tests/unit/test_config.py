"""Tests for autoclip.config.Settings."""

import pytest
from pydantic import SecretStr

from autoclip.config import Settings, get_settings


def test_settings_loads_from_env(monkeypatch, tmp_path):
    """Settings should load all required fields from environment variables."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "test_data"))
    monkeypatch.setenv("ALIYUN_ASR_APP_KEY", "test_app_key")
    monkeypatch.setenv("ALIYUN_ASR_TOKEN", "test_asr_token")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test123")
    monkeypatch.setenv("VOLCENGINE_TTS_TOKEN", "tts_token")
    monkeypatch.setenv("VOLCENGINE_TTS_APP_ID", "tts_app_id")
    monkeypatch.setenv("MAX_CONCURRENT_JOBS", "3")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    settings = Settings(_env_file=None)  # Skip .env, use only env vars

    assert settings.data_dir == tmp_path / "test_data"
    assert settings.aliyun_asr_app_key.get_secret_value() == "test_app_key"
    assert settings.aliyun_asr_token.get_secret_value() == "test_asr_token"
    assert settings.dashscope_api_key.get_secret_value() == "sk-test123"
    assert settings.volcengine_tts_token.get_secret_value() == "tts_token"
    assert settings.volcengine_tts_app_id.get_secret_value() == "tts_app_id"
    assert settings.max_concurrent_jobs == 3
    assert settings.log_level == "DEBUG"


def test_data_dir_auto_created(monkeypatch, tmp_path):
    """get_settings() should auto-create nested data_dir."""
    nested = tmp_path / "deep" / "nested" / "data"
    monkeypatch.setenv("DATA_DIR", str(nested))

    assert not nested.exists()
    get_settings()
    assert nested.exists()
    assert nested.is_dir()


def test_secrets_are_secret_str():
    """All secrets must be wrapped in SecretStr (no accidental logging)."""
    settings = Settings(_env_file=None)
    assert isinstance(settings.aliyun_asr_app_key, SecretStr)
    assert isinstance(settings.aliyun_asr_token, SecretStr)
    assert isinstance(settings.dashscope_api_key, SecretStr)
    assert isinstance(settings.volcengine_tts_token, SecretStr)
    assert isinstance(settings.volcengine_tts_app_id, SecretStr)


def test_max_concurrent_jobs_validation(monkeypatch):
    """max_concurrent_jobs must be 1-10."""
    monkeypatch.setenv("MAX_CONCURRENT_JOBS", "0")
    with pytest.raises(ValueError):
        Settings(_env_file=None)

    monkeypatch.setenv("MAX_CONCURRENT_JOBS", "11")
    with pytest.raises(ValueError):
        Settings(_env_file=None)
