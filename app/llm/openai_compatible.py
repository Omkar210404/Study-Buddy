"""Provider for any OpenAI-compatible Chat Completions API (Groq, OpenRouter, OpenAI, Ollama, ...).

Plain httpx, no vendor SDK. What leaves the machine is exactly the payload built in
`_build_payload`: the system prompt and the user prompt, which holds one passage of the notes.
"""

import time

import httpx

from app.errors import (
    LLMAuthError,
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
    MalformedOutputError,
)
from app.llm.base import LLMProvider, LLMRequest, LLMResponse


class OpenAICompatibleProvider(LLMProvider):
    name = "openai_compatible"

    def __init__(self, api_key: str, model: str, base_url: str, timeout_seconds: float = 30.0,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.model = model
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            headers={"Authorization": f"Bearer {api_key}"},
            transport=transport,
        )

    def _build_payload(self, request: LLMRequest) -> dict:
        payload: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.json_mode:
            payload["response_format"] = {"type": "json_object"}
        return payload

    async def complete(self, request: LLMRequest) -> LLMResponse:
        started = time.perf_counter()
        try:
            response = await self._client.post("/chat/completions", json=self._build_payload(request))
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"provider timeout: {type(exc).__name__}") from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError(f"provider connection error: {type(exc).__name__}") from exc

        status = response.status_code
        if status >= 400:
            detail = f"provider returned HTTP {status}: {self._error_message(response)}"
            if status in (401, 403):
                raise LLMAuthError(detail)
            if status == 429:
                raise LLMRateLimitError(detail, retry_after=self._retry_after(response))
            error = LLMProviderError(detail)
            # Other 4xx (bad model name, bad payload) will not succeed on a retry.
            error.retryable = status >= 500
            raise error

        try:
            body = response.json()
            text = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise MalformedOutputError("provider response missing choices[0].message.content") from exc
        if not isinstance(text, str) or not text.strip():
            raise MalformedOutputError("provider returned empty content")

        return LLMResponse(
            text=text,
            model=body.get("model") or self.model,
            provider=self.name,
            latency_ms=round((time.perf_counter() - started) * 1000, 1),
        )

    @staticmethod
    def _retry_after(response: httpx.Response) -> float | None:
        try:
            return float(response.headers["retry-after"])
        except (KeyError, ValueError):
            return None

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        """The provider's own error text, truncated. Providers do not echo API keys in error bodies."""
        try:
            error = response.json().get("error")
            message = error.get("message") if isinstance(error, dict) else str(error)
        except (ValueError, AttributeError):
            message = response.text
        return (message or "no error message")[:200]

    async def aclose(self) -> None:
        await self._client.aclose()
