"""Orchestration: question -> route (SLM) -> weather facts -> answer (LLM)."""

from __future__ import annotations

import datetime as dt
import logging

from jev.config import Settings
from jev.llm import LLMClient, LLMError
from jev.models import AskResponse, Intent
from jev.questions import render_question
from jev.router import SLMRouter
from jev.weather import WeatherClient, WeatherError, as_dict, hot_verdict

log = logging.getLogger(__name__)


class Jev:
    def __init__(self, settings: Settings, weather: WeatherClient, router: SLMRouter, llm: LLMClient):
        self.settings = settings
        self.weather = weather
        self.router = router
        self.llm = llm

    @classmethod
    def from_settings(cls, settings: Settings) -> "Jev":
        return cls(settings, WeatherClient(settings), SLMRouter(settings), LLMClient(settings))

    async def aclose(self) -> None:
        for c in (self.weather, self.router, self.llm):
            await c.aclose()

    async def ask(
        self,
        question: str | None = None,
        location: str | None = None,
        date: dt.date | None = None,
        today: dt.date | None = None,
    ) -> AskResponse:
        today = today or dt.date.today()
        template = question or self.settings.default_question
        rendered = render_question(template, location, date or today)

        parsed = await self.router.route(rendered, today)
        loc = location or parsed.location or self.settings.default_location
        on = date or parsed.date or today
        rendered = render_question(template, loc, on)

        facts = await self._facts(parsed.intent, loc, on, today)
        answer, answered_by = await self._answer(rendered, parsed.intent, facts)
        return AskResponse(
            question=rendered,
            answer=answer,
            intent=parsed.intent,
            location=loc,
            date=on,
            facts=facts,
            router=parsed.router,
            answered_by=answered_by,
        )

    async def _facts(self, intent: Intent, location: str, on: dt.date, today: dt.date) -> dict:
        unit = self.weather.unit_symbol
        facts: dict = {"intent": intent.value, "requested_location": location, "date": on.isoformat(), "unit": unit}
        if intent == Intent.UNKNOWN:
            facts["error"] = (
                "Unsupported question. Jev answers: current temperature, historical median "
                "temperature, and whether it is hot for the time of year."
            )
            return facts
        try:
            place = await self.weather.geocode(location)
            facts["location"] = place.label
            if intent in (Intent.CURRENT_TEMPERATURE, Intent.IS_HOT):
                facts["observed"] = as_dict(await self.weather.day_summary(place, on, today))
            if intent in (Intent.HISTORICAL_MEDIAN, Intent.IS_HOT):
                facts["historical"] = as_dict(await self.weather.historical(place, on))
            if intent == Intent.IS_HOT:
                facts["verdict"] = hot_verdict(facts["observed"]["today_high"], facts["historical"])
        except WeatherError as exc:
            facts["error"] = str(exc)
        return facts

    async def _answer(self, question: str, intent: Intent, facts: dict) -> tuple[str, str]:
        if self.settings.llm_enabled:
            try:
                return await self.llm.answer(question, facts), self.llm.name
            except LLMError as exc:
                log.warning("LLM answer failed, using template: %s", exc)
                facts.setdefault("warnings", []).append(str(exc))
        return template_answer(intent, facts), "template"


def template_answer(intent: Intent, facts: dict) -> str:
    if "error" in facts:
        return f"Sorry, I couldn't answer that: {facts['error']}"
    u = facts["unit"]
    loc = facts.get("location", facts["requested_location"])
    date = facts["date"]
    if intent == Intent.CURRENT_TEMPERATURE:
        o = facts["observed"]
        return (
            f"The temperature in {loc} on {date} is {o['temperature']}{u} "
            f"(high {o['today_high']}{u}, low {o['today_low']}{u})."
        )
    if intent == Intent.HISTORICAL_MEDIAN:
        h = facts["historical"]
        return (
            f"Historically (last {h['years']} years, ±{h['window_days']} days around {date[5:]}), "
            f"{loc} has a median high of {h['median_high']}{u}, median daily mean of "
            f"{h['median_mean']}{u}, and median low of {h['median_low']}{u}."
        )
    # IS_HOT
    o, h, v = facts["observed"], facts["historical"], facts["verdict"]
    yes_no = "Yes" if v["is_hot"] else "No"
    sign = "+" if v["anomaly_vs_median_high"] >= 0 else ""
    return (
        f"{yes_no} — {loc} is {v['level']} for this time of year. The high on {date} is "
        f"{o['today_high']}{u} vs. a historical median high of {h['median_high']}{u} "
        f"({sign}{v['anomaly_vs_median_high']}{u}); hot threshold (75th percentile) is {h['p75_high']}{u}."
    )
