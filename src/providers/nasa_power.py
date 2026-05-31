"""NASA POWER provider (quick-switch alternative; public domain).

NASA POWER is U.S. government work in the PUBLIC DOMAIN -- free for any use
including commercial, no API key. Trade-offs vs Open-Meteo: no forecast and a
~2-7 day latency (data is reanalysis/satellite-derived). Both are fine for an
environmental index the project already designs around 1-2 week lags.

Switch to this provider with:  --provider nasa-power   (or WEATHER_PROVIDER=nasa-power)

Parameters requested (daily): T2M (mean temp), T2M_MAX, T2M_MIN, RH2M (relative
humidity), PRECTOTCORR (bias-corrected precipitation, mm/day). Missing values
are returned as -999 and are converted to None.
"""
from __future__ import annotations

from datetime import date, timedelta

from httputil import build_url, get_json

from .base import DailyWeather, WeatherProvider

ENDPOINT = "https://power.larc.nasa.gov/api/temporal/daily/point"
FILL_VALUE = -999.0


class NasaPowerProvider(WeatherProvider):
    name = "nasa-power"
    attribution = "Weather data by NASA POWER (MERRA-2 / GMAO), public domain"

    def fetch_daily(self, lat: float, lon: float, past_days: int = 16) -> list[DailyWeather]:
        # Pad the start to absorb NASA's latency so we still cover `past_days`
        # worth of *available* observations.
        end = date.today()
        start = end - timedelta(days=past_days + 6)

        url = build_url(
            ENDPOINT,
            {
                "parameters": "T2M,T2M_MAX,T2M_MIN,RH2M,PRECTOTCORR",
                "community": "AG",
                "latitude": lat,
                "longitude": lon,
                "start": start.strftime("%Y%m%d"),
                "end": end.strftime("%Y%m%d"),
                "format": "JSON",
            },
        )
        data = get_json(url)

        params = (((data.get("properties") or {}).get("parameter")) or {})
        t_mean = params.get("T2M") or {}
        t_max = params.get("T2M_MAX") or {}
        t_min = params.get("T2M_MIN") or {}
        rh = params.get("RH2M") or {}
        precip = params.get("PRECTOTCORR") or {}

        if not t_mean and not precip:
            raise RuntimeError("NASA POWER returned no parameter data")

        all_days = sorted(set(t_mean) | set(precip) | set(rh))
        records: list[DailyWeather] = []
        for ymd in all_days:
            rec = DailyWeather(
                date=f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}",
                temp_mean_c=_clean(t_mean.get(ymd)),
                temp_max_c=_clean(t_max.get(ymd)),
                temp_min_c=_clean(t_min.get(ymd)),
                humidity_pct=_clean(rh.get(ymd)),
                precip_mm=_clean(precip.get(ymd)),
            )
            # Drop trailing days NASA hasn't filled yet (all key fields missing).
            if rec.temp_mean_c is None and rec.precip_mm is None:
                continue
            records.append(rec)
        return records


def _clean(val):
    """Convert NASA's -999 fill value (and Nones) to None."""
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    return None if f <= FILL_VALUE else f
