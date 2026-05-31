"""Open-Meteo provider (DEFAULT for testing/demo).

Free, no API key. NOTE: the free endpoint is licensed for NON-COMMERCIAL use
only. A branded/commercial dashboard needs Open-Meteo's paid tier (~$29/mo) or
a switch to the NASA POWER provider (public domain). See README > Licensing.

Daily temp + precipitation come from the `daily` block; relative humidity is
only exposed hourly, so we pull `hourly.relative_humidity_2m` and average it
to a daily mean ourselves.
"""
from __future__ import annotations

from collections import defaultdict

from httputil import build_url, get_json

from .base import DailyWeather, WeatherProvider

ENDPOINT = "https://api.open-meteo.com/v1/forecast"


class OpenMeteoProvider(WeatherProvider):
    name = "open-meteo"
    attribution = "Weather data by Open-Meteo.com (CC BY 4.0)"

    def fetch_daily(self, lat: float, lon: float, past_days: int = 16) -> list[DailyWeather]:
        url = build_url(
            ENDPOINT,
            {
                "latitude": lat,
                "longitude": lon,
                "daily": "temperature_2m_max,temperature_2m_min,temperature_2m_mean,precipitation_sum",
                "hourly": "relative_humidity_2m",
                "past_days": past_days,
                "forecast_days": 1,   # include today so age-0 exists
                "timezone": "auto",
            },
        )
        data = get_json(url)

        daily = data.get("daily") or {}
        dates = daily.get("time") or []
        if not dates:
            raise RuntimeError("Open-Meteo returned no daily data")

        t_max = daily.get("temperature_2m_max") or []
        t_min = daily.get("temperature_2m_min") or []
        t_mean = daily.get("temperature_2m_mean") or []
        precip = daily.get("precipitation_sum") or []

        humidity_by_date = self._daily_mean_humidity(data.get("hourly") or {})

        records: list[DailyWeather] = []
        for i, date in enumerate(dates):
            records.append(
                DailyWeather(
                    date=date,
                    temp_mean_c=_at(t_mean, i),
                    temp_max_c=_at(t_max, i),
                    temp_min_c=_at(t_min, i),
                    humidity_pct=humidity_by_date.get(date),
                    precip_mm=_at(precip, i),
                )
            )
        return records

    @staticmethod
    def _daily_mean_humidity(hourly: dict) -> dict[str, float]:
        """Average hourly relative_humidity_2m into a per-date mean."""
        times = hourly.get("time") or []
        values = hourly.get("relative_humidity_2m") or []
        sums: dict[str, float] = defaultdict(float)
        counts: dict[str, int] = defaultdict(int)
        for ts, val in zip(times, values):
            if val is None:
                continue
            day = ts[:10]  # "2026-05-31T13:00" -> "2026-05-31"
            sums[day] += val
            counts[day] += 1
        return {day: sums[day] / counts[day] for day in sums if counts[day]}


def _at(seq: list, i: int):
    return seq[i] if i < len(seq) else None
