"""Request / response schemas and internal data types."""

from __future__ import annotations

import datetime as dt
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Intent(str, Enum):
    CURRENT_TEMPERATURE = "current_temperature"
    HISTORICAL_MEDIAN = "historical_median"
    IS_HOT = "is_hot"
    UNKNOWN = "unknown"


class ParsedQuestion(BaseModel):
    """Structured interpretation of a free-form question (produced by the SLM or rules)."""

    intent: Intent
    location: str | None = None
    date: dt.date | None = None
    router: str = Field(description="Which router produced this: 'slm' or 'rules'.")


class AskRequest(BaseModel):
    question: str | None = Field(
        default=None,
        description="Free-form question. May contain {location} and {date} placeholders. "
        "Defaults to DEFAULT_QUESTION.",
        examples=["Is it currently hot in {location} for this time of the year?"],
    )
    location: str | None = Field(default=None, description="City/State, e.g. 'Austin, TX'.", examples=["Austin, TX"])
    date: dt.date | None = Field(default=None, description="Date of interest (defaults to today).")


class BatchRequest(BaseModel):
    location: str | None = Field(default=None, examples=["Phoenix, AZ"])
    date: dt.date | None = None


class AskResponse(BaseModel):
    question: str
    answer: str
    intent: Intent
    location: str | None
    date: dt.date
    facts: dict[str, Any]
    router: str
    answered_by: str


class BatchResponse(BaseModel):
    test_mode: bool
    location: str
    date: dt.date
    results: list[AskResponse]


class QuestionsResponse(BaseModel):
    test_mode: bool
    source: str
    questions: list[str]


class HealthResponse(BaseModel):
    status: str
    version: str
    test_mode: bool
    slm_configured: bool
    llm_provider: str
