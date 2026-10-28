"""Thin LLM client. Provider, model, key and base URL come from .env only.

Why a wrapper: the challenge requires a replaceable AI provider and no personal key in the repo.
Every LLM call in the project goes through `chat_json()` here. `AI_PROVIDER=anthropic` (default) uses Claude
(Sonnet 5.5) through the official Anthropic SDK; any other value uses an OpenAI-compatible endpoint (OpenAI,
Gemini, Azure OpenAI, local server), so switching provider is a 4-line .env change.
The key is never logged; `LLMUnavailable` lets callers degrade gracefully (deterministic answers).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from ..config import settings

log = logging.getLogger(__name__)


class LLMUnavailable(RuntimeError):
    """No key configured or the provider failed; callers must fall back, never invent."""


CLAUDE_DEFAULT_MODEL = "claude-sonnet-5-5"
_CLAUDE_EFFORTS = {"low", "medium", "high", "xhigh", "max"}
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)


class LLMClient:
    def __init__(self, model: str | None = None):
        if not settings.ai_api_key:
            raise LLMUnavailable("AI_API_KEY not configured")
        self.model = model or settings.ai_model
        self.provider = settings.ai_provider
        if self.provider == "anthropic":
            if self.model.startswith(("gpt", "o1", "o3", "o4", "gemini")):  # stale AI_MODEL left from another provider
                self.model = CLAUDE_DEFAULT_MODEL
            import anthropic  # imported lazily so the rest of the app works without the package configured

            self._client = anthropic.Anthropic(api_key=settings.ai_api_key, base_url=settings.ai_base_url, timeout=120.0, max_retries=2)
        else:
            from openai import OpenAI

            self._client = OpenAI(api_key=settings.ai_api_key, base_url=settings.ai_base_url)

    # ------------------------------------------------------------------ primitives
    def chat(self, messages: list[dict], tools: list[dict] | None = None, temperature: float = 0.0,
             response_format: dict | None = None, max_tokens: int = 1500) -> Any:
        if self.provider == "anthropic":
            raise LLMUnavailable("chat() is OpenAI-compatible only; use chat_json() with the anthropic provider")
        reasoning = self.model.startswith(("gpt-5", "o1", "o3", "o4"))  # reasoning models: fixed temperature, max_completion_tokens
        kw: dict[str, Any] = {"model": self.model, "messages": messages}
        if reasoning:
            kw["max_completion_tokens"] = max(max_tokens * 8, 8000)  # reasoning tokens count against the limit
            if self.model.startswith("gpt-5"):
                kw["reasoning_effort"] = settings.ai_reasoning_effort or "minimal"
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
        if self.provider == "anthropic":
            return self._chat_json_claude(system, user, schema, max_tokens)
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

    def _chat_json_claude(self, system: str, user: str, schema: dict | None, max_tokens: int) -> dict:
        """Claude Messages API. Sonnet 5.5 rejects temperature and forced tool_choice, so the JSON is requested in the prompt."""
        effort = (settings.ai_reasoning_effort or "low").lower()
        effort = effort if effort in _CLAUDE_EFFORTS else "low"  # 'minimal' (gpt-5 wording) -> low
        base: dict[str, Any] = {
            "model": self.model, "system": system, "messages": [{"role": "user", "content": user}],
            "max_tokens": min(max(max_tokens * 3, 8000), 32000),  # thinking tokens count against the limit
        }
        # The project schemas (nested, nullable) are rejected by structured outputs ("Schema is too complex", after ~100 s),
        # so the schema goes in the prompt; the reply is parsed and validated by the caller (Pydantic) and the grounding guard.
        hint = f"valid for this JSON schema:\n{json.dumps(schema)}" if schema else "(any shape the instructions ask for)"
        kw = {**base, "system": f"{system}\n\nReply with ONLY one JSON object (no prose, no code fence) {hint}", "output_config": {"effort": effort}}
        try:
            with self._client.messages.stream(**kw) as stream:
                msg = stream.get_final_message()
        except Exception as e:  # noqa: BLE001
            log.warning("LLM call failed: %s: %s", type(e).__name__, str(e)[:200])
            raise LLMUnavailable(f"{type(e).__name__}: {str(e)[:200]}") from e
        self._last_usage = getattr(msg, "usage", None)
        if msg.stop_reason in ("refusal", "max_tokens"):
            raise LLMUnavailable(f"no usable answer (stop_reason={msg.stop_reason})")
        txt = _FENCE.sub("", "".join(b.text for b in msg.content if b.type == "text").strip())
        if not txt:
            raise LLMUnavailable(f"empty answer (stop_reason={msg.stop_reason})")
        try:
            return json.loads(txt)
        except json.JSONDecodeError as e:
            raise LLMUnavailable(f"non-JSON answer: {txt[:120]}") from e

    def usage(self, resp=None) -> dict:
        u = getattr(resp, "usage", None) or getattr(self, "_last_usage", None)
        return {"prompt_tokens": getattr(u, "prompt_tokens", None) or getattr(u, "input_tokens", None),
                "completion_tokens": getattr(u, "completion_tokens", None) or getattr(u, "output_tokens", None), "model": self.model}


_client: LLMClient | None = None


def get_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
