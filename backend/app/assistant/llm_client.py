"""The model behind the assistant: an interface and an OpenAI-compatible HTTP implementation.

OpenRouter, Groq, a local Ollama server and many paid providers speak this chat API, so the provider, model and key
are only configuration (`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`). The key is never logged.
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.config import get_settings
from app.errors import ApiError

logger = logging.getLogger("app.assistant")

NOT_CONFIGURED = "ASSISTANT_NOT_CONFIGURED"


class AssistantError(ApiError):
    """An assistant failure with a stable code the page can explain (see the status table in the README)."""


def not_configured() -> AssistantError:
    return AssistantError(
        503,
        NOT_CONFIGURED,
        "The assistant is not configured. Set LLM_API_KEY and LLM_MODEL in .env (a free OpenRouter key works; see the README), then restart the backend.",
    )


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # the raw JSON text the model produced


@dataclass
class LLMReply:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    message: dict[str, Any] = field(default_factory=dict)  # the assistant message to append to the conversation


class LLMClient(Protocol):
    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> LLMReply: ...


class OpenAICompatibleClient:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> LLMReply:
        body: dict[str, Any] = {"model": self.model, "messages": messages}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=body,
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                )
        except httpx.TimeoutException as exc:
            logger.warning("model %s timed out after %.0f s", self.model, self.timeout)
            raise AssistantError(504, "ASSISTANT_TIMEOUT", "The model did not answer in time. Please try again.") from exc
        except httpx.HTTPError as exc:
            logger.warning("model %s unreachable: %s", self.model, exc.__class__.__name__)
            raise AssistantError(502, "ASSISTANT_UNAVAILABLE", "The model provider could not be reached. Please try again later.") from exc
        logger.info(
            "model %s status=%s request_id=%s elapsed_ms=%d",
            self.model,
            response.status_code,
            response.headers.get("x-request-id", "-"),
            (time.monotonic() - started) * 1000,
        )
        return parse_reply(response)


def provider_message(data: Any) -> str:
    """The provider's own explanation, if it sent one (it never contains our key)."""
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or "")[:300]
    return str(error)[:300] if error else ""


def raise_for_status(status: int, response: httpx.Response, data: Any) -> None:
    detail = provider_message(data)
    if status in (401, 403):
        raise AssistantError(502, "ASSISTANT_UNAUTHORIZED", "The model provider rejected the API key. Check LLM_API_KEY.")
    if status == 429:
        retry = response.headers.get("Retry-After")
        headers = {"Retry-After": retry} if retry and retry.isdigit() else None
        raise AssistantError(
            429,
            "ASSISTANT_RATE_LIMITED",
            "The model provider's limit was reached (free models have daily and per-minute limits). Wait a little and try again."
            + (f" ({detail})" if detail else ""),
            headers=headers,
        )
    if status >= 500:
        raise AssistantError(502, "ASSISTANT_UNAVAILABLE", "The model provider failed. Please try again later.")
    raise AssistantError(
        502,
        "ASSISTANT_BAD_RESPONSE",
        "The model provider refused the request" + (f": {detail}" if detail else " (check LLM_MODEL; it must support tools)."),
    )


def parse_reply(response: httpx.Response) -> LLMReply:
    try:
        data = response.json()
    except ValueError:
        data = None
    if response.status_code != 200:
        raise_for_status(response.status_code, response, data)
    if not isinstance(data, dict):
        raise AssistantError(502, "ASSISTANT_BAD_RESPONSE", "The model provider sent an answer the assistant cannot read.")
    if not data.get("choices"):
        # Some providers answer 200 with an error body (for example when a free model is busy).
        error = data.get("error")
        code = error.get("code") if isinstance(error, dict) else None
        if isinstance(code, int) and code >= 400:
            raise_for_status(code, response, data)
        raise AssistantError(502, "ASSISTANT_BAD_RESPONSE", "The model provider sent an empty answer. Please try again.")
    message = data["choices"][0].get("message") or {}
    calls = []
    for raw in message.get("tool_calls") or []:
        function = raw.get("function") or {}
        calls.append(ToolCall(id=str(raw.get("id") or ""), name=str(function.get("name") or ""), arguments=function.get("arguments") or ""))
    content = message.get("content")
    return LLMReply(content=content if isinstance(content, str) else None, tool_calls=calls, message=message)


def get_llm_client() -> LLMClient:
    """The configured model (a FastAPI dependency, so tests can replace it). 503 when not configured."""
    settings = get_settings()
    key = settings.llm_api_key.get_secret_value()
    if not key or not settings.llm_model:
        raise not_configured()
    return OpenAICompatibleClient(settings.llm_base_url, key, settings.llm_model, settings.llm_timeout_seconds)
