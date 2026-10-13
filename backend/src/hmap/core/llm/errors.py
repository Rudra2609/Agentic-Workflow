"""LLM-specific errors. Transient provider faults reuse :class:`hmap.core.errors.ModelTransientError` (retryable)."""

from hmap.core.errors import ErrorCode, HmapError, ModelTransientError


class LLMError(HmapError):
    """Non-retryable LLM gateway problem (configuration, provider rejection, cache miss)."""

    code = ErrorCode.DEPENDENCY


class LLMConfigError(LLMError):
    """Bad or missing configuration, e.g. no model mapped for a role (``HMAP_ROLE_MAP``)."""


class LLMProviderError(LLMError):
    """The provider rejected the request (4xx other than rate limiting): unknown model, bad request, auth."""


class ReplayMissError(LLMError):
    """``replay`` mode found no cached answer for the request; the message lists the key ingredients."""


class StructuredOutputError(HmapError):
    """The model did not produce schema-valid JSON after the repair retries."""

    code = ErrorCode.WRONG_RESULT


class FakeLLMError(LLMError):
    """``FakeLLM`` has no scripted answer for a call."""


class VisionUnavailable(LLMError):
    """No vision model can answer right now (no ``vision`` cloud route, cloud not allowed, or every key failed).
    There is no local vision fallback: callers use their own (e.g. Tesseract OCR)."""


class CloudRateLimited(ModelTransientError):
    """Cloud provider kept answering 429 after bounded retries (the gateway then falls back to local)."""


__all__ = [
    "CloudRateLimited",
    "FakeLLMError",
    "LLMConfigError",
    "LLMError",
    "LLMProviderError",
    "ModelTransientError",
    "ReplayMissError",
    "StructuredOutputError",
    "VisionUnavailable",
]
