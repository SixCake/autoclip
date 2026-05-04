"""Application settings loaded from environment variables.

All secrets are wrapped in `SecretStr` to prevent accidental logging.
Settings are loaded with priority: env vars > .env file > defaults.

Reference: design.md §6 (config layer), §16.5 (zero-knowledge: data_dir lifecycle).
"""

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # === Storage ===
    data_dir: Path = Field(
        default=Path("./data"),
        description="Root directory for job artifacts. Auto-created on startup.",
    )

    # === Aliyun ASR (revised default per ADR-001 v0.3) ===
    aliyun_asr_app_key: SecretStr = Field(
        default=SecretStr(""),
        description="Aliyun NLS app key.",
    )
    aliyun_asr_token: SecretStr = Field(
        default=SecretStr(""),
        description="Aliyun NLS access token.",
    )

    # === Tongyi Qianwen LLM ===
    dashscope_api_key: SecretStr = Field(
        default=SecretStr(""),
        description="Dashscope API key for Tongyi Qianwen.",
    )

    # === Volcengine TTS (火山豆包) ===
    volcengine_tts_token: SecretStr = Field(
        default=SecretStr(""),
        description="Volcengine TTS access token.",
    )
    volcengine_tts_app_id: SecretStr = Field(
        default=SecretStr(""),
        description="Volcengine TTS app ID.",
    )

    # === Pipeline ===
    max_concurrent_jobs: int = Field(
        default=1,
        ge=1,
        le=10,
        description="Max concurrent pipeline jobs (MVP=1, single-user local).",
    )

    # === Logging ===
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG/INFO/WARNING/ERROR).",
    )

    def ensure_data_dir(self) -> None:
        """Create data_dir (and parents) if missing. Idempotent."""
        self.data_dir.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    """Factory for Settings (allows pytest monkeypatching)."""
    settings = Settings()
    settings.ensure_data_dir()
    return settings
