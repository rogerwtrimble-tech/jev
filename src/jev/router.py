"""Question routing: turn a free-form question into a ParsedQuestion.

The SLM (any OpenAI-compatible endpoint) is used when SLM_URL is set; the
deterministic rule-based router is used otherwise, or as a fallback if the SLM
call fails or returns something unusable.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re

import httpx

from jev.config import Settings
from jev.models import Intent, ParsedQuestion

log = logging.getLogger(__name__)

SLM_SYSTEM_PROMPT = """You are a router for a weather question service.
Classify the user's question into exactly one intent:
- "current_temperature": asks for the current/now/today temperature
- "historical_median": asks for the median/average/normal/typical/historical temperature
- "is_hot": asks whether it is hot/warm/cold compared to normal for the time of year
- "unknown": anything else
Extract the location (City, State) if present, and the date (YYYY-MM-DD) if present.
Respond with ONLY a JSON object: {"intent": "...", "location": "... or null", "date": "YYYY-MM-DD or null"}"""

_ISO_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_LOCATION = re.compile(
    r"\b(?:in|for|at)\s+([A-Z][\w.' -]*?,\s*[A-Za-z][\w ]*?)(?=\s+(?:on|for|this|right|today|historically|currently|now)\b|[?.!]|$)"
)
_LOCATION_LOOSE = re.compile(r"\b(?:in|for|at)\s+([A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*)*)")


def rule_route(question: str, today: dt.date) -> ParsedQuestion:
    q = question.lower()
    if any(w in q for w in ("median", "average", "normal", "typical", "historically", "historical")):
        intent = Intent.HISTORICAL_MEDIAN
    elif any(w in q for w in ("hot", "warm", "cold", "cool", "heat")):
        intent = Intent.IS_HOT
    elif "temperature" in q or "temp" in q or "how warm" in q:
        intent = Intent.CURRENT_TEMPERATURE
    else:
        intent = Intent.UNKNOWN

    date = None
    if m := _ISO_DATE.search(question):
        try:
            date = dt.date.fromisoformat(m.group(1))
        except ValueError:
            date = None
    elif "today" in q or "now" in q or "currently" in q:
        date = today

    location = None
    if m := _LOCATION.search(question):
        location = m.group(1).strip()
    elif m := _LOCATION_LOOSE.search(question):
        location = m.group(1).strip()
    if location and "{" in location:
        location = None
    return ParsedQuestion(intent=intent, location=location, date=date, router="rules")


class SLMRouter:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self._client = client or httpx.AsyncClient(timeout=settings.slm_timeout_seconds)

    async def aclose(self) -> None:
        await self._client.aclose()

    def _endpoint(self) -> str:
        url = self.settings.slm_url.rstrip("/")
        if url.endswith("/chat/completions"):
            return url
        if url.endswith("/v1"):
            return url + "/chat/completions"
        return url + "/v1/chat/completions"

    async def route(self, question: str, today: dt.date) -> ParsedQuestion:
        fallback = rule_route(question, today)
        if not self.settings.slm_enabled:
            return fallback
        headers = {"Content-Type": "application/json"}
        if self.settings.slm_api_key:
            headers["Authorization"] = f"Bearer {self.settings.slm_api_key}"
        payload = {
            "model": self.settings.slm_model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": SLM_SYSTEM_PROMPT},
                {"role": "user", "content": f"Today is {today.isoformat()}.\nQuestion: {question}"},
            ],
        }
        try:
            resp = await self._client.post(self._endpoint(), json=payload, headers=headers)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            data = _extract_json(content)
            intent = Intent(data.get("intent", "unknown"))
            location = data.get("location") or None
            date_str = data.get("date") or None
            date = dt.date.fromisoformat(date_str) if date_str else None
        except Exception as exc:  # noqa: BLE001 - any SLM failure falls back to rules
            log.warning("SLM routing failed, using rule-based router: %s", exc)
            return fallback
        return ParsedQuestion(
            intent=intent if intent != Intent.UNKNOWN else fallback.intent,
            location=location if location and "{" not in location else fallback.location,
            date=date or fallback.date,
            router="slm",
        )


def _extract_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object in SLM output: {text!r}")
    return json.loads(text[start : end + 1])
