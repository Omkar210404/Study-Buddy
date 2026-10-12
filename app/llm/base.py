"""Provider-agnostic LLM interface. The rest of the app depends only on this module."""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class LLMRequest(BaseModel):
    system: str
    user: str
    temperature: float = 0.2
    max_tokens: int = 900
    # Ask the provider for a JSON object.
    json_mode: bool = True
    # Local bookkeeping only (which passage, how many cards). Never sent to a real provider;
    # the mock reads it to build its reply.
    metadata: dict[str, Any] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    text: str
    model: str
    provider: str
    latency_ms: float


class LLMProvider(ABC):
    """Every provider implements one async method. Errors are raised as `app.errors.LLMError` subclasses."""

    name: str = "base"
    model: str = "unknown"

    @abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResponse:
        ...

    async def aclose(self) -> None:  # pragma: no cover - default no-op
        return None
