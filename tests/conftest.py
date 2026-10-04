"""Shared fixtures: a fake Open-Meteo / SLM / LLM backend served through httpx.MockTransport."""

from __future__ import annotations

import datetime as dt
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from jev.api import create_app
from jev.config import Settings
from jev.llm import LLMClient
from jev.pipeline import Jev
from jev.router import SLMRouter
from jev.weather import WeatherClient

TODAY = dt.date(2026, 10, 4)


def fake_open_meteo(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    p = request.url.params
    if "geocoding" in url:
        return httpx.Response(200, json={"results": [
            {"name": p["name"], "admin1": "Georgia", "country_code": "US",
             "latitude": 33.9, "longitude": -83.3, "timezone": "America/New_York"},
            {"name": p["name"], "admin1": "Texas", "country_code": "US",
             "latitude": 30.27, "longitude": -97.74, "timezone": "America/Chicago"},
        ]})
    if "archive" in url and p["start_date"] != p["end_date"]:
        start, end = dt.date.fromisoformat(p["start_date"]), dt.date.fromisoformat(p["end_date"])
        days, d = [], start
        while d <= end:
            days.append(d)
            d += dt.timedelta(days=1)
        # Highs spread 80..89 so median=84.5, p75~=86.75, p90~=88.1 (deterministic per-day)
        highs = [80 + (x.toordinal() % 10) for x in days]
        return httpx.Response(200, json={"daily": {
            "time": [x.isoformat() for x in days],
            "temperature_2m_max": highs,
            "temperature_2m_mean": [h - 10 for h in highs],
            "temperature_2m_min": [h - 20 for h in highs],
        }})
    if "current" in p:
        return httpx.Response(200, json={
            "current": {"time": "2026-10-04T15:00", "temperature_2m": 91.0},
            "daily": {"temperature_2m_max": [93.0], "temperature_2m_min": [70.0]},
        })
    # single-day forecast/archive
    return httpx.Response(200, json={"daily": {
        "temperature_2m_max": [75.0], "temperature_2m_min": [55.0], "temperature_2m_mean": [65.0]}})


def fake_slm(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    q = body["messages"][-1]["content"].lower()
    intent = "historical_median" if "median" in q else "is_hot" if "hot" in q else "current_temperature"
    content = json.dumps({"intent": intent, "location": None, "date": None})
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def fake_llm(request: httpx.Request) -> httpx.Response:
    if "anthropic" in str(request.url):
        return httpx.Response(200, json={"content": [{"type": "text", "text": "LLM says hot."}]})
    return httpx.Response(200, json={"choices": [{"message": {"content": "LLM says hot."}}]})


def make_settings(**overrides) -> Settings:
    base = dict(_env_file=None, test_mode=True, slm_url="", llm_provider="none", llm_api_key="")
    base.update(overrides)
    return Settings(**base)


def make_jev(settings: Settings) -> Jev:
    return Jev(
        settings,
        WeatherClient(settings, httpx.AsyncClient(transport=httpx.MockTransport(fake_open_meteo))),
        SLMRouter(settings, httpx.AsyncClient(transport=httpx.MockTransport(fake_slm))),
        LLMClient(settings, httpx.AsyncClient(transport=httpx.MockTransport(fake_llm))),
    )


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def client(settings, monkeypatch):
    monkeypatch.setattr("jev.pipeline.dt.date", _FrozenDate)
    with TestClient(create_app(settings, make_jev(settings))) as c:
        yield c


class _FrozenDate(dt.date):
    @classmethod
    def today(cls):
        return TODAY
