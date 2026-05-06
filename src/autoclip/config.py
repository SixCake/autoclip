"""Application settings loaded from environment variables.

All secrets are wrapped in `SecretStr` to prevent accidental logging.
Settings are loaded with priority: env vars > .env file > defaults.

Reference: design.md Part IV §21 (local whisper ASR), §6 (config layer), §16.5 (zero-knowledge: data_dir lifecycle).
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

    # === Local ASR — faster-whisper (design.md Part IV §21.1, ADR-004 三度修订) ===
    # No credentials required. Model weights cached at ~/.cache/huggingface/hub/.
    whisper_model_size: str = Field(
        default="large-v3",
        description=(
            "faster-whisper model size: tiny / base / small / medium / large-v3. "
            "Default large-v3 (3.1GB, M3 Pro realtime ratio 4-5x). "
            "Low-RAM machines can downgrade to medium (1.5GB)."
        ),
    )
    whisper_device: str = Field(
        default="auto",
        description=(
            "Inference device: auto / cpu / cuda / mps. "
            "'auto' lets faster-whisper pick best available."
        ),
    )
    whisper_compute_type: str = Field(
        default="default",
        description=(
            "Compute precision: default / int8 / float16 / float32. "
            "'default' lets faster-whisper choose per device (int8 on CPU, float16 on GPU)."
        ),
    )
    whisper_language: str | None = Field(
        default=None,
        description=(
            "ASR language code: 'en' / 'zh' / 'ja' / etc., or None for auto-detection. "
            "Default None (Whisper auto-detects). Set explicitly if auto-detection fails."
        ),
    )

    # === Tongyi Qianwen LLM ===
    dashscope_api_key: SecretStr = Field(
        default=SecretStr(""),
        description="Dashscope API key for Tongyi Qianwen.",
    )

    # === Qwen-TTS (Session 35: 替换 Volcengine, 复用 dashscope_api_key) ===
    # Qwen-TTS shares the same DashScope API key as the LLM (Tongyi Qianwen).
    # Voice ↔ content matching is configured at: providers/tts/voice_map.py
    # Style instructions are built at:           providers/tts/instructions.py
    qwen_tts_model: str = Field(
        default="qwen3-tts-instruct-flash",
        description=(
            "Qwen-TTS model name. instruct variant is required for the "
            "instructions parameter (style/语速/情感 control)."
        ),
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
