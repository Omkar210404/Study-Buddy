"""Provider factory and retry wrapper. Switching provider is a configuration change, not a code change."""

import asyncio

from app.config import Settings
from app.errors import ConfigError, LLMError
from app.llm.base import LLMProvider, LLMRequest, LLMResponse
from app.llm.mock import MockProvider
from app.llm.openai_compatible import OpenAICompatibleProvider


class RetryingProvider(LLMProvider):
    """Retries retryable errors (timeouts, rate limits, 5xx) with exponential backoff."""

    def __init__(self, inner: LLMProvider, max_retries: int = 2, base_delay: float = 1.0,
                 max_delay: float = 20.0):
        self.inner = inner
        self.name = inner.name
        self.model = inner.model
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay

    async def complete(self, request: LLMRequest) -> LLMResponse:
        attempt = 0
        while True:
            try:
                return await self.inner.complete(request)
            except LLMError as exc:
                if not exc.retryable or attempt >= self.max_retries:
                    raise
                attempt += 1
                delay = self.base_delay * (2 ** (attempt - 1))
                retry_after = getattr(exc, "retry_after", None)
                if retry_after is not None:
                    delay = max(delay, retry_after)  # the provider says when capacity is back
                await asyncio.sleep(min(delay, self.max_delay))

    async def aclose(self) -> None:
        await self.inner.aclose()


def build_provider(settings: Settings) -> LLMProvider | None:
    """None in offline mode: no provider object exists, so nothing can be sent anywhere."""
    if settings.llm_provider == "none":
        return None
    if settings.llm_provider == "mock":
        return MockProvider(mode=settings.mock_llm_mode)
    problems = settings.config_problems()
    if problems:
        raise ConfigError("LLM mode is not configured: " + "; ".join(problems))
    inner = OpenAICompatibleProvider(
        api_key=settings.llm_api_key.get_secret_value(),  # type: ignore[union-attr]
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    return RetryingProvider(inner, max_retries=settings.llm_max_retries)
