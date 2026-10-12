"""The OpenAI-compatible provider against a fake transport. Nothing here opens a socket."""

import asyncio
import json

import httpx
import pytest

from app.config import Settings
from app.errors import (
    ConfigError,
    LLMAuthError,
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
    MalformedOutputError,
)
from app.llm.base import LLMRequest
from app.llm.factory import RetryingProvider, build_provider
from app.llm.mock import MockProvider
from app.llm.openai_compatible import OpenAICompatibleProvider

REQUEST = LLMRequest(system="You write flashcards.", user="Passage: a router forwards packets.",
                     metadata={"passage": "LOCAL ONLY", "max_cards": 3})


def run(coroutine):
    return asyncio.run(coroutine)


def provider_with(handler) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(api_key="test-key", model="test-model",
                                    base_url="https://llm.invalid/v1/",
                                    transport=httpx.MockTransport(handler))


def ok_body(content: str = '{"cards": []}') -> dict:
    return {"model": "served-model", "choices": [{"message": {"content": content}}]}


def test_request_payload_holds_the_prompts_and_nothing_else():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok_body())

    response = run(provider_with(handler).complete(REQUEST))
    assert response.text == '{"cards": []}' and response.model == "served-model"
    assert seen["url"] == "https://llm.invalid/v1/chat/completions"
    assert seen["auth"] == "Bearer test-key"
    assert seen["body"] == {
        "model": "test-model",
        "messages": [
            {"role": "system", "content": "You write flashcards."},
            {"role": "user", "content": "Passage: a router forwards packets."},
        ],
        "temperature": 0.2,
        "max_tokens": 900,
        "response_format": {"type": "json_object"},
    }
    assert "LOCAL ONLY" not in json.dumps(seen["body"])  # request metadata never leaves the machine


@pytest.mark.parametrize("status, error, retryable", [
    (401, LLMAuthError, False),
    (403, LLMAuthError, False),
    (429, LLMRateLimitError, True),
    (500, LLMProviderError, True),
    (400, LLMProviderError, False),
])
def test_http_errors_are_mapped(status, error, retryable):
    def handler(request):
        return httpx.Response(status, json={"error": {"message": "something went wrong"}},
                              headers={"retry-after": "7"})

    with pytest.raises(error) as excinfo:
        run(provider_with(handler).complete(REQUEST))
    assert excinfo.value.retryable is retryable
    assert f"HTTP {status}" in str(excinfo.value) and "test-key" not in str(excinfo.value)
    if status == 429:
        assert excinfo.value.retry_after == 7.0


def test_timeouts_and_connection_errors_are_mapped():
    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    def refused(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(LLMTimeoutError):
        run(provider_with(timeout).complete(REQUEST))
    with pytest.raises(LLMProviderError):
        run(provider_with(refused).complete(REQUEST))


@pytest.mark.parametrize("body", [{"choices": []}, {"choices": [{"message": {"content": "  "}}]}, {}])
def test_unusable_bodies_are_malformed_output(body):
    with pytest.raises(MalformedOutputError):
        run(provider_with(lambda request: httpx.Response(200, json=body)).complete(REQUEST))


def test_retrying_provider_retries_retryable_errors_only():
    flaky = MockProvider(fail_with=LLMProviderError("HTTP 500"), fail_times=2)
    response = run(RetryingProvider(flaky, max_retries=2, base_delay=0).complete(REQUEST))
    assert response.provider == "mock" and len(flaky.calls) == 3

    down = MockProvider(fail_with=LLMProviderError("HTTP 500"))
    with pytest.raises(LLMProviderError):
        run(RetryingProvider(down, max_retries=1, base_delay=0).complete(REQUEST))
    assert len(down.calls) == 2

    locked = MockProvider(fail_with=LLMAuthError("HTTP 401"))
    with pytest.raises(LLMAuthError):
        run(RetryingProvider(locked, max_retries=3, base_delay=0).complete(REQUEST))
    assert len(locked.calls) == 1


def settings(**values) -> Settings:
    return Settings(_env_file=None, **values)


def test_offline_mode_builds_no_provider_at_all():
    assert build_provider(settings(llm_provider="none")) is None
    assert settings(llm_provider="none").llm_enabled is False


def test_mock_provider_is_built_with_the_configured_mode():
    provider = build_provider(settings(llm_provider="mock", mock_llm_mode="fake_quotes"))
    assert isinstance(provider, MockProvider) and provider.mode == "fake_quotes"


def test_real_provider_needs_a_key_and_a_model():
    with pytest.raises(ConfigError) as excinfo:
        build_provider(settings(llm_provider="openai_compatible", llm_api_key=None, llm_model=""))
    assert "LLM_API_KEY is not set" in str(excinfo.value) and "LLM_MODEL is not set" in str(excinfo.value)

    configured = settings(llm_provider="openai_compatible", llm_api_key="secret-value",
                          llm_model="some-model", llm_base_url="https://api.groq.com/openai/v1")
    provider = build_provider(configured)
    assert isinstance(provider, RetryingProvider) and provider.model == "some-model"
    assert configured.llm_host == "api.groq.com"
    assert "secret-value" not in repr(configured)
    run(provider.aclose())
