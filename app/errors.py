"""Error types. Messages are written for the person using the app and never contain secrets."""


class StudyBuddyError(Exception):
    """Base class for errors the web layer turns into a readable message."""


class IngestionError(StudyBuddyError):
    """The notes could not be read (unsupported type, scanned PDF, too large, empty)."""


class ConfigError(StudyBuddyError):
    """LLM mode was requested but is not configured correctly."""


class LLMError(StudyBuddyError):
    """Base class for provider failures. `retryable` tells the retry wrapper whether to try again."""

    error_type = "llm_error"
    retryable = False


class LLMAuthError(LLMError):
    error_type = "auth_error"


class LLMRateLimitError(LLMError):
    error_type = "rate_limit"
    retryable = True

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class LLMTimeoutError(LLMError):
    error_type = "timeout"
    retryable = True


class LLMProviderError(LLMError):
    error_type = "provider_error"
    retryable = True


class MalformedOutputError(LLMError):
    """The provider answered, but not with the JSON we asked for."""

    error_type = "malformed_output"
