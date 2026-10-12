"""Application settings, loaded from environment variables (and an optional .env file)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore",
                                      env_ignore_empty=True)

    database_path: Path = Path("data/studybuddy.db")

    # "none" means offline mode only: no provider is built and nothing is ever sent anywhere.
    llm_provider: Literal["none", "openai_compatible", "mock"] = "none"
    llm_api_key: SecretStr | None = None
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_model: str = ""
    llm_timeout_seconds: float = Field(default=30.0, gt=0)
    llm_max_retries: int = Field(default=2, ge=0, le=5)
    llm_max_passages_per_run: int = Field(default=20, ge=1, le=200)
    llm_cards_per_passage: int = Field(default=3, ge=1, le=10)
    mock_llm_mode: Literal["good", "fake_quotes", "mixed", "invalid_json"] = "good"

    new_cards_per_day: int = Field(default=20, ge=0)
    max_upload_mb: int = Field(default=5, ge=1, le=50)

    @property
    def llm_enabled(self) -> bool:
        return self.llm_provider != "none"

    @property
    def llm_host(self) -> str:
        """Host the passages are sent to in LLM mode, for display. Never includes the key."""
        if self.llm_provider == "mock":
            return "the built-in mock (no network)"
        return urlparse(self.llm_base_url).netloc or self.llm_base_url

    def config_problems(self) -> list[str]:
        """Human-readable configuration problems. Never includes secret values."""
        problems: list[str] = []
        if self.llm_provider == "openai_compatible":
            if self.llm_api_key is None or not self.llm_api_key.get_secret_value().strip():
                problems.append("LLM_API_KEY is not set")
            if not self.llm_model.strip():
                problems.append("LLM_MODEL is not set")
            if not self.llm_base_url.strip():
                problems.append("LLM_BASE_URL is not set")
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()
