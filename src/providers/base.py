"""Weather provider interface for Layer 1.

Every provider returns the SAME normalized shape (a list of DailyWeather),
so the scoring formula never knows or cares which source produced the data.
Swapping Open-Meteo <-> NASA POWER (or a future paid tier) is a one-line change
in build_layer1.py / the WEATHER_PROVIDER env var.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class DailyWeather:
    """One day of normalized weather for one location.

    Any field may be None when a source is missing that day/variable; the
    scoring layer skips None values when aggregating.
    """
    date: str               # ISO date, "YYYY-MM-DD"
    temp_mean_c: float | None
    temp_max_c: float | None
    temp_min_c: float | None
    humidity_pct: float | None   # daily mean relative humidity, %
    precip_mm: float | None      # daily total precipitation, mm


class WeatherProvider(ABC):
    """Base class. Implementations fetch raw data and normalize to DailyWeather."""

    name: str = "base"
    #: Human-readable attribution string, surfaced in data.json for the dashboard.
    attribution: str = ""

    @abstractmethod
    def fetch_daily(self, lat: float, lon: float, past_days: int = 16) -> list[DailyWeather]:
        """Return ~past_days of daily records for (lat, lon), any order.

        Implementations should raise on a hard failure (network/parse) so the
        orchestrator can count it as a failed city rather than scoring garbage.
        """
        raise NotImplementedError
