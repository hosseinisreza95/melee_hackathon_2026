"""Thin OpenAI-compatible client. Provider, model, key and base URL come from .env only.

Why a wrapper: the challenge requires a replaceable AI provider and no personal key in the repo.
Every LLM call in the project goes through `chat_json()` / `chat_tools()` here, so switching to
Gemini (OpenAI-compatible endpoint), Azure OpenAI or a local server is a 4-line .env change.
The key is never logged; `LLMUnavailable` lets callers degrade gracefully (deterministic answers).
"""
from __future__ import annotations

import json
import logging
from typing import Any

from ..config import settings

log = logging.getLogger(__name__)


class LLMUnavailable(RuntimeError):
    """No key configured or the provider failed; callers must fall back, never invent."""


class LLMClient:
    def __init__(self, model: str | None = None):
        if not settings.ai_api_key:
            raise LLMUnavailable("AI_API_KEY not configured")
        from openai import OpenAI  # imported lazily so the rest of the app works without the package configured

        self.model = model or settings.ai_model
        self.provider = settings.ai_provider
        self._client = OpenAI(api_key=settings.ai_api_key, base_url=settings.ai_base_url)

    # ------------------------------------------------------------------ primitives
    def chat(self, messages: list[dict], tools: list[dict] | None = None, temperature: float = 0.0,
             response_format: dict | None = None, max_tokens: int = 1500) -> Any:
        reasoning = self.model.startswith(("gpt-5", "o1", "o3", "o4"))  # reasoning models: fixed temperature, max_completion_tokens
        kw: dict[str, Any] = {"model": self.model, "messages": messages}
        if reasoning:
            kw["max_completion_tokens"] = max(max_tokens * 8, 8000)  # reasoning tokens count against the limit
            if self.model.startswith("gpt-5") and settings.ai_reasoning_effort:
                kw["reasoning_effort"] = settings.ai_reasoning_effort
        else:
            kw["temperature"] = temperature
            kw["max_tokens"] = max_tokens
        if tools:
            kw["tools"] = tools
            kw["tool_choice"] = "auto"
        if response_format:
            kw["response_format"] = response_format
        try:
            return self._client.chat.completions.create(**kw)
        except Exception as e:  # noqa: BLE001
            # never include the request (may contain the key in headers) in logs
            log.warning("LLM call failed: %s: %s", type(e).__name__, str(e)[:200])
            raise LLMUnavailable(f"{type(e).__name__}: {str(e)[:200]}") from e

    def chat_json(self, system: str, user: str, schema: dict | None = None, max_tokens: int = 4000) -> dict:
        """Ask for a JSON object; validate it parses. Schema enforcement when the provider supports it."""
        rf: dict = {"type": "json_object"}
        if schema:
            rf = {"type": "json_schema", "json_schema": {"name": "answer", "schema": schema, "strict": False}}
        resp = self.chat([{"role": "system", "content": system}, {"role": "user", "content": user}],
                         response_format=rf, max_tokens=max_tokens)
        choice = resp.choices[0]
        txt = choice.message.content or ""
        if not txt.strip():
            raise LLMUnavailable(f"empty answer (finish_reason={getattr(choice, 'finish_reason', None)})")
        try:
            return json.loads(txt)
        except json.JSONDecodeError as e:
            raise LLMUnavailable(f"non-JSON answer: {txt[:120]}") from e

    def usage(self, resp) -> dict:
        u = getattr(resp, "usage", None)
        return {"prompt_tokens": getattr(u, "prompt_tokens", None), "completion_tokens": getattr(u, "completion_tokens", None), "model": self.model}


_client: LLMClient | None = None


def get_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
