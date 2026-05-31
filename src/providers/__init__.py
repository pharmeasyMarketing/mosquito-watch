"""Provider registry. Add a new source here and it's instantly selectable
by name from the CLI / WEATHER_PROVIDER env var."""
from __future__ import annotations

from .base import DailyWeather, WeatherProvider
from .nasa_power import NasaPowerProvider
from .open_meteo import OpenMeteoProvider

_REGISTRY = {
    OpenMeteoProvider.name: OpenMeteoProvider,
    NasaPowerProvider.name: NasaPowerProvider,
}

DEFAULT_PROVIDER = OpenMeteoProvider.name


def available() -> list[str]:
    return sorted(_REGISTRY)


def get_provider(name: str) -> WeatherProvider:
    try:
        return _REGISTRY[name]()
    except KeyError:
        raise SystemExit(
            f"Unknown provider '{name}'. Available: {', '.join(available())}"
        )


__all__ = ["DailyWeather", "WeatherProvider", "get_provider", "available", "DEFAULT_PROVIDER"]
