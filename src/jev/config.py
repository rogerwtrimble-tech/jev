"""Application settings, loaded from environment variables / `.env`."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# The three predefined questions used when TEST_MODE=true.
TEST_QUESTIONS: list[str] = [
    "What is the current temperature in {location} on {date}?",
    "What is the median temperature for {location} historically?",
    "Is it hot in {location} on {date}?",
]

LLMProvider = Literal["none", "openai", "anthropic", "openai_compatible"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Mode -------------------------------------------------------------
    test_mode: bool = Field(default=True, description="Use the 3 built-in test questions.")

    # --- (1) Questions ----------------------------------------------------
    questions_file: str = "config/questions.yaml"

    # --- (2) SLM ----------------------------------------------------------
    slm_url: str = ""
    slm_model: str = "phi3:mini"
    slm_api_key: str = ""
    slm_timeout_seconds: float = 15.0

    # --- (3) LLM ----------------------------------------------------------
    llm_provider: LLMProvider = "none"
    llm_api_key: str = ""
    llm_model: str = ""
    llm_base_url: str = ""
    llm_timeout_seconds: float = 30.0

    # --- Defaults ---------------------------------------------------------
    default_question: str = "Is it currently hot in {location} for this time of the year?"
    default_location: str = "Austin, TX"
    temperature_unit: Literal["fahrenheit", "celsius"] = "fahrenheit"
    history_years: int = Field(default=30, ge=1, le=80)
    history_window_days: int = Field(default=7, ge=0, le=45)

    # --- Weather data (Open-Meteo, free, no key) --------------------------
    geocoding_url: str = "https://geocoding-api.open-meteo.com/v1/search"
    forecast_url: str = "https://api.open-meteo.com/v1/forecast"
    archive_url: str = "https://archive-api.open-meteo.com/v1/archive"
    weather_timeout_seconds: float = 20.0

    @property
    def slm_enabled(self) -> bool:
        return bool(self.slm_url.strip())

    @property
    def llm_enabled(self) -> bool:
        return self.llm_provider != "none"


@lru_cache
def get_settings() -> Settings:
    return Settings()
