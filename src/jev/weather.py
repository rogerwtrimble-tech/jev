"""Weather data via Open-Meteo (free, no API key).

* Geocoding:  City/State -> lat/lon (US state abbreviations supported)
* Forecast:   current temperature + today's high/low
* Archive:    historical daily temperatures around the same calendar date
"""

from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import asdict, dataclass

import httpx

from jev.config import Settings

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri",
    "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "DC": "District of Columbia", "PR": "Puerto Rico",
}


class WeatherError(RuntimeError):
    pass


@dataclass
class Place:
    name: str
    region: str | None
    country: str | None
    latitude: float
    longitude: float
    timezone: str

    @property
    def label(self) -> str:
        return ", ".join(p for p in (self.name, self.region, self.country) if p)


@dataclass
class CurrentConditions:
    temperature: float
    today_high: float
    today_low: float
    observed_at: str


@dataclass
class HistoricalStats:
    median_high: float
    median_mean: float
    median_low: float
    p75_high: float
    p90_high: float
    years: int
    window_days: int
    samples: int


class WeatherClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self._client = client or httpx.AsyncClient(timeout=settings.weather_timeout_seconds)

    @property
    def unit_symbol(self) -> str:
        return "°F" if self.settings.temperature_unit == "fahrenheit" else "°C"

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, url: str, params: dict) -> dict:
        try:
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            raise WeatherError(f"Weather service request failed: {exc}") from exc

    # -- geocoding ---------------------------------------------------------
    async def geocode(self, location: str) -> Place:
        parts = [p.strip() for p in location.split(",") if p.strip()]
        if not parts:
            raise WeatherError("Empty location")
        city = parts[0]
        region_hint = parts[1] if len(parts) > 1 else None
        if region_hint and region_hint.upper() in US_STATES:
            region_hint = US_STATES[region_hint.upper()]

        data = await self._get(
            self.settings.geocoding_url, {"name": city, "count": 20, "language": "en", "format": "json"}
        )
        results = data.get("results") or []
        if not results:
            raise WeatherError(f"Could not find location '{location}'")

        match = results[0]
        if region_hint:
            hint = region_hint.lower()
            for r in results:
                if hint in {(r.get("admin1") or "").lower(), (r.get("country") or "").lower(),
                            (r.get("country_code") or "").lower()}:
                    match = r
                    break
        return Place(
            name=match["name"],
            region=match.get("admin1"),
            country=match.get("country_code"),
            latitude=match["latitude"],
            longitude=match["longitude"],
            timezone=match.get("timezone") or "auto",
        )

    # -- current -----------------------------------------------------------
    async def current(self, place: Place) -> CurrentConditions:
        data = await self._get(
            self.settings.forecast_url,
            {
                "latitude": place.latitude,
                "longitude": place.longitude,
                "current": "temperature_2m",
                "daily": "temperature_2m_max,temperature_2m_min",
                "forecast_days": 1,
                "timezone": place.timezone,
                "temperature_unit": self.settings.temperature_unit,
            },
        )
        try:
            return CurrentConditions(
                temperature=float(data["current"]["temperature_2m"]),
                today_high=float(data["daily"]["temperature_2m_max"][0]),
                today_low=float(data["daily"]["temperature_2m_min"][0]),
                observed_at=str(data["current"]["time"]),
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise WeatherError("Unexpected forecast response") from exc

    async def day_summary(self, place: Place, on: dt.date, today: dt.date) -> CurrentConditions:
        """Temperatures for a specific date: live data for today, archive for past, forecast for future."""
        if on == today:
            return await self.current(place)
        if on > today and (on - today).days > 15:
            raise WeatherError("Forecasts are only available up to 16 days ahead")
        url = self.settings.forecast_url if on > today or (today - on).days <= 5 else self.settings.archive_url
        data = await self._get(
            url,
            {
                "latitude": place.latitude,
                "longitude": place.longitude,
                "start_date": on.isoformat(),
                "end_date": on.isoformat(),
                "daily": "temperature_2m_max,temperature_2m_min,temperature_2m_mean",
                "timezone": place.timezone,
                "temperature_unit": self.settings.temperature_unit,
            },
        )
        try:
            d = data["daily"]
            hi, lo = float(d["temperature_2m_max"][0]), float(d["temperature_2m_min"][0])
            mean = d.get("temperature_2m_mean", [None])[0]
            return CurrentConditions(
                temperature=float(mean) if mean is not None else round((hi + lo) / 2, 1),
                today_high=hi,
                today_low=lo,
                observed_at=on.isoformat(),
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise WeatherError("Unexpected weather response") from exc

    # -- historical --------------------------------------------------------
    async def historical(self, place: Place, on: dt.date) -> HistoricalStats:
        years = self.settings.history_years
        window = self.settings.history_window_days
        last_year = on.year - 1
        start = dt.date(last_year - years + 1, 1, 1)
        end = dt.date(last_year, 12, 31)
        data = await self._get(
            self.settings.archive_url,
            {
                "latitude": place.latitude,
                "longitude": place.longitude,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "daily": "temperature_2m_max,temperature_2m_mean,temperature_2m_min",
                "timezone": place.timezone,
                "temperature_unit": self.settings.temperature_unit,
            },
        )
        daily = data.get("daily") or {}
        times = daily.get("time") or []
        highs, means, lows = [], [], []
        for i, day in enumerate(times):
            d = dt.date.fromisoformat(day)
            if not _within_window(d, on, window):
                continue
            hi = daily["temperature_2m_max"][i]
            mn = daily["temperature_2m_mean"][i]
            lo = daily["temperature_2m_min"][i]
            if None in (hi, mn, lo):
                continue
            highs.append(hi)
            means.append(mn)
            lows.append(lo)
        if not highs:
            raise WeatherError("No historical data available for this location/date")
        return HistoricalStats(
            median_high=round(statistics.median(highs), 1),
            median_mean=round(statistics.median(means), 1),
            median_low=round(statistics.median(lows), 1),
            p75_high=round(_percentile(highs, 75), 1),
            p90_high=round(_percentile(highs, 90), 1),
            years=years,
            window_days=window,
            samples=len(highs),
        )


def _within_window(d: dt.date, target: dt.date, window: int) -> bool:
    """True if `d` falls within +/- `window` days of target's month/day (in d's year)."""
    for year in (d.year - 1, d.year, d.year + 1):
        try:
            anchor = target.replace(year=year)
        except ValueError:  # Feb 29 in a non-leap year
            anchor = dt.date(year, 2, 28)
        if abs((d - anchor).days) <= window:
            return True
    return False


def _percentile(values: list[float], pct: float) -> float:
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * pct / 100
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def hot_verdict(today_high: float, stats: dict) -> dict:
    """Compare today's high with the historical distribution for this time of year."""
    anomaly = round(today_high - stats["median_high"], 1)
    if today_high >= stats["p90_high"]:
        level = "very hot"
    elif today_high >= stats["p75_high"]:
        level = "hot"
    elif today_high >= stats["median_high"]:
        level = "warmer than usual"
    else:
        level = "not hot"
    return {"is_hot": today_high >= stats["p75_high"], "level": level, "anomaly_vs_median_high": anomaly}


def as_dict(obj) -> dict:
    return asdict(obj)
