"""Configuration management for BabililoBot."""

import json
from functools import lru_cache
from typing import List, Dict, Tuple

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


# Available free models on OpenRouter, categorized by company
FREE_MODELS_BY_CATEGORY: Dict[str, List[Tuple[str, str]]] = {
    "🔷 Google": [
        ("google/gemma-3-27b-it:free", "Gemma 3 27B"),
        ("google/gemma-3-12b-it:free", "Gemma 3 12B"),
        ("google/gemma-3n-e4b-it:free", "Gemma 3n 4B"),
        ("google/gemma-3n-e2b-it:free", "Gemma 3n 2B"),
        ("google/gemini-2.0-flash-exp:free", "Gemini 2.0 Flash"),
    ],
    "🦙 Meta": [
        ("meta-llama/llama-3.3-70b-instruct:free", "Llama 3.3 70B"),
        ("meta-llama/llama-3.2-3b-instruct:free", "Llama 3.2 3B"),
    ],
    "🌙 Qwen": [
        ("qwen/qwen3-235b-a22b:free", "Qwen3 235B"),
        ("qwen/qwen3-coder:free", "Qwen3 Coder 480B"),
        ("qwen/qwen3-4b:free", "Qwen3 4B"),
    ],
    "🔮 DeepSeek": [
        ("deepseek/deepseek-r1-distill-llama-70b:free", "R1 Distill Llama 70B"),
    ],
    "⚡ xAI": [
        ("x-ai/grok-4.1-fast:free", "Grok 4.1 Fast"),
    ],
    "🌊 Mistral": [
        ("mistralai/mistral-7b-instruct:free", "Mistral 7B"),
    ],
    "🟢 NVIDIA": [
        ("nvidia/nemotron-nano-12b-v2-vl:free", "Nemotron Nano 12B VL"),
        ("nvidia/nemotron-nano-9b-v2:free", "Nemotron Nano 9B"),
    ],
    "🌟 MoonshotAI": [
        ("moonshotai/kimi-k2:free", "Kimi K2"),
    ],
    "🧠 Nous Research": [
        ("nousresearch/hermes-3-llama-3.1-405b:free", "Hermes 3 405B"),
    ],
    "🔬 TNG": [
        ("tngtech/deepseek-r1t2-chimera:free", "DeepSeek R1T2 Chimera"),
        ("tngtech/deepseek-r1t-chimera:free", "DeepSeek R1T Chimera"),
        ("tngtech/tng-r1t-chimera:free", "R1T Chimera"),
    ],
    "🎯 Others": [
        ("alibaba/tongyi-deepresearch-30b-a3b:free", "Tongyi DeepResearch 30B"),
        ("openai/gpt-oss-20b:free", "GPT-OSS 20B"),
        ("z-ai/glm-4.5-air:free", "GLM 4.5 Air"),
        ("kwaipilot/kat-coder-pro:free", "KAT-Coder Pro"),
        ("meituan/longcat-flash-chat:free", "LongCat Flash"),
        ("cognitivecomputations/dolphin-mistral-24b-venice-edition:free", "Venice Uncensored"),
    ],
}

# Flat list of all models (for backward compatibility)
FREE_MODELS: List[Tuple[str, str]] = []
for category, models in FREE_MODELS_BY_CATEGORY.items():
    FREE_MODELS.extend(models)


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
