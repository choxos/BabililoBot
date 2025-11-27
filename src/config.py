"""Configuration management for BabililoBot."""

import json
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram
    telegram_bot_token: str

    # OpenRouter
    openrouter_api_key: str
    openrouter_default_model: str = "google/gemma-3-27b-it:free"

    # Database
    database_url: str = "postgresql+asyncpg://babililo:babililo_secret@localhost:5432/babililo_db"

    # Bot Configuration
    admin_user_ids: str = "[]"
    rate_limit_messages: int = 10
    rate_limit_window_seconds: int = 60
    conversation_context_size: int = 20

    # Application
    log_level: str = "INFO"

    @property
    def admin_ids(self) -> List[int]:
        """Parse admin user IDs from JSON string."""
        try:
            return json.loads(self.admin_user_ids)
        except (json.JSONDecodeError, TypeError):
            return []

    @property
    def openrouter_base_url(self) -> str:
        """OpenRouter API base URL."""
        return "https://openrouter.ai/api/v1"


# Available free models on OpenRouter
FREE_MODELS = [
    ("google/gemma-3-27b-it:free", "Gemma 3 27B"),
    ("google/gemma-3-12b-it:free", "Gemma 3 12B"),
    ("meta-llama/llama-4-scout:free", "Llama 4 Scout"),
    ("meta-llama/llama-4-maverick:free", "Llama 4 Maverick"),
    ("mistralai/mistral-small-3.1-24b-instruct:free", "Mistral Small 3.1"),
    ("qwen/qwen3-32b:free", "Qwen 3 32B"),
    ("qwen/qwen3-14b:free", "Qwen 3 14B"),
    ("deepseek/deepseek-r1-0528:free", "DeepSeek R1"),
    ("microsoft/phi-4:free", "Phi 4"),
    ("x-ai/grok-4.1-fast:free", "Grok 4.1 Fast"),
]


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()

