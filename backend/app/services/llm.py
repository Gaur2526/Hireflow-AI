"""Optional Claude-powered structured extraction.

The product works end to end with no LLM key at all - every call site has a
deterministic fallback. When ``ANTHROPIC_API_KEY`` is present we get much
better job-description understanding and screening-question design.
"""

from __future__ import annotations

from typing import TypeVar

import anthropic
from pydantic import BaseModel

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMUnavailable(RuntimeError):
    """Raised when no key is configured or the API call fails.

    Callers are expected to catch this and fall back to heuristics.
    """


class LLMClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.anthropic_api_key
        self.model = model or settings.llm_model
        self.max_tokens = max_tokens or settings.llm_max_tokens
        self._client: anthropic.AsyncAnthropic | None = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _get_client(self) -> anthropic.AsyncAnthropic:
        if not self.configured:
            raise LLMUnavailable("ANTHROPIC_API_KEY is not configured")
        if self._client is None:
            self._client = anthropic.AsyncAnthropic(api_key=self.api_key, max_retries=2)
        return self._client

    async def structured(
        self,
        *,
        system: str,
        prompt: str,
        output_model: type[T],
        effort: str = "medium",
    ) -> T:
        """Return a validated instance of ``output_model``.

        Uses the Messages API structured-output mode so the model is constrained
        to our JSON schema rather than asked politely for JSON.
        """
        client = self._get_client()
        try:
            response = await client.messages.parse(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                output_config={"effort": effort},
                output_format=output_model,
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.AuthenticationError as exc:
            raise LLMUnavailable("Anthropic rejected the API key") from exc
        except anthropic.RateLimitError as exc:
            raise LLMUnavailable("Anthropic rate limit hit") from exc
        except anthropic.APIStatusError as exc:
            raise LLMUnavailable(f"Anthropic API error {exc.status_code}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMUnavailable("Could not reach the Anthropic API") from exc

        if response.stop_reason == "refusal":
            raise LLMUnavailable("Anthropic declined the request")

        parsed = response.parsed_output
        if parsed is None:
            raise LLMUnavailable("Anthropic returned no structured output")

        log.info(
            "llm.structured",
            model=self.model,
            output=output_model.__name__,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        return parsed


def get_llm() -> LLMClient:
    return LLMClient()
