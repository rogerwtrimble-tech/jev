"""LLM providers used to write the final natural-language answer.

Supported LLM_PROVIDER values:
  none               - deterministic templated answer (no network, no key)
  openai             - OpenAI Chat Completions
  anthropic          - Anthropic Messages API
  openai_compatible  - any OpenAI-compatible gateway at LLM_BASE_URL
"""

from __future__ import annotations

import json
import logging

import httpx

from jev.config import Settings

log = logging.getLogger(__name__)

DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-sonnet-5-5",
    "openai_compatible": "gpt-4o-mini",
}

ANSWER_SYSTEM_PROMPT = """You are Jev, a concise weather assistant.
Answer the user's question in 1-3 sentences using ONLY the facts provided as JSON.
Always include the numbers with units. Do not invent data. If facts contain an
"error", explain briefly that the data could not be retrieved."""


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self._client = client or httpx.AsyncClient(timeout=settings.llm_timeout_seconds)

    async def aclose(self) -> None:
        await self._client.aclose()

    @property
    def model(self) -> str:
        return self.settings.llm_model or DEFAULT_MODELS.get(self.settings.llm_provider, "")

    @property
    def name(self) -> str:
        if not self.settings.llm_enabled:
            return "template"
        return f"{self.settings.llm_provider}:{self.model}"

    async def answer(self, question: str, facts: dict) -> str:
        provider = self.settings.llm_provider
        if provider == "none":
            raise LLMError("LLM disabled")
        if not self.settings.llm_api_key and provider != "openai_compatible":
            raise LLMError(f"LLM_API_KEY is required for provider '{provider}'")
        user_msg = f"Question: {question}\n\nFacts (JSON):\n{json.dumps(facts, default=str, indent=2)}"
        try:
            if provider == "anthropic":
                return await self._anthropic(user_msg)
            return await self._openai(user_msg)
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMError(f"LLM call failed: {exc}") from exc

    async def _openai(self, user_msg: str) -> str:
        if self.settings.llm_provider == "openai_compatible":
            if not self.settings.llm_base_url:
                raise LLMError("LLM_BASE_URL is required for provider 'openai_compatible'")
            base = self.settings.llm_base_url.rstrip("/")
        else:
            base = "https://api.openai.com/v1"
        headers = {"Content-Type": "application/json"}
        if self.settings.llm_api_key:
            headers["Authorization"] = f"Bearer {self.settings.llm_api_key}"
        resp = await self._client.post(
            f"{base}/chat/completions",
            headers=headers,
            json={
                "model": self.model,
                "temperature": 0.2,
                "messages": [
                    {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()

    async def _anthropic(self, user_msg: str) -> str:
        base = (self.settings.llm_base_url or "https://api.anthropic.com").rstrip("/")
        resp = await self._client.post(
            f"{base}/v1/messages",
            headers={
                "x-api-key": self.settings.llm_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": 300,
                "system": ANSWER_SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_msg}],
            },
        )
        resp.raise_for_status()
        blocks = resp.json()["content"]
        return "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
