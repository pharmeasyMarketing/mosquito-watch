"""Mock / sample Trends provider (DEFAULT for development).

Generates DETERMINISTIC, clearly-synthetic search interest so the Layer 2
pipeline and dashboard can be built and demoed without hitting Google Trends or
paying for a managed API. The numbers are NOT real -- is_sample=True flows all
the way into fever_signal.json, and the dashboard badges the section as sample
data so nobody mistakes it for a live signal.

Determinism: every value is derived from a SHA-256 hash of a seed string, so
re-runs produce identical numbers (no random churn in the committed data file).
The national series carries a gentle upward trend so the "watch attention rise
through the season" story renders sensibly in the demo.
"""
from __future__ import annotations

import hashlib
import math
from datetime import date as _date, timedelta

from .base import RegionInterest, TrendPoint, TrendsProvider

# Used only when interest_by_region is called without a `regions` hint (e.g. in a
# quick manual test). The orchestrator always passes the full config state list.
_FALLBACK_REGIONS = [
    {"name": "Maharashtra", "code": "IN-MH"},
    {"name": "Delhi", "code": "IN-DL"},
    {"name": "Tamil Nadu", "code": "IN-TN"},
    {"name": "West Bengal", "code": "IN-WB"},
    {"name": "Kerala", "code": "IN-KL"},
    {"name": "Karnataka", "code": "IN-KA"},
]


def _hash01(*parts) -> float:
    """Deterministic pseudo-random float in [0, 1) from the given parts."""
    seed = "|".join(str(p) for p in parts)
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return (int(digest[:8], 16) % 1_000_000) / 1_000_000.0


def _query(terms: list[str]) -> str:
    # Google Trends treats " + " as OR; use it as the combined-query seed/label.
    return " + ".join(terms)


def _recent_sundays(weeks: int) -> list[str]:
    """`weeks` weekly ISO dates (Sundays), oldest first, ending this week."""
    today = _date.today()
    last_sunday = today - timedelta(days=(today.weekday() + 1) % 7)
    return [(last_sunday - timedelta(weeks=(weeks - 1 - i))).isoformat() for i in range(weeks)]


def _monsoon(d) -> float:
    """0..1 seasonal weight peaking in late Aug (the monsoon fever season)."""
    doy = d.timetuple().tm_yday
    return math.exp(-((doy - 240) ** 2) / (2 * 55.0 ** 2))


class MockTrendsProvider(TrendsProvider):
    name = "mock"
    attribution = "SAMPLE synthetic data for development -- not real Google Trends"
    is_sample = True

    def interest_over_time(self, terms, geo="IN", weeks=12, date=None):
        q = _query(terms)
        if date and " " in str(date):                  # custom span "start end"
            return self._span_series(q, geo, str(date))
        base = 35.0 + 30.0 * _hash01("base", q)        # 35..65 per-group baseline
        dates = _recent_sundays(weeks)
        points = []
        for i, d in enumerate(dates):
            frac = i / (weeks - 1) if weeks > 1 else 1.0
            trend = 22.0 * frac                         # rises into the season
            noise = 10.0 * (_hash01(q, geo, i) - 0.5)   # +/-5 weekly wiggle
            value = max(0.0, min(100.0, base + trend + noise))
            points.append(TrendPoint(date=d, value=round(value, 1)))
        return points

    def _span_series(self, q, geo, date_str):
        """Weekly synthetic series across a custom date span, shaped by a monsoon
        seasonal curve (peak ~Aug/Sep) and normalized to peak 100 like Trends.
        `geo` seeds the noise so different states look distinct."""
        parts = date_str.split(" ")
        start = _date.fromisoformat(parts[0])
        end = min(_date.fromisoformat(parts[1]), _date.today())   # no future data
        base = 25.0 + 20.0 * _hash01("base", q)
        d = start - timedelta(days=start.weekday())               # first Monday
        raw = []
        while d <= end:
            noise = 8.0 * (_hash01(q, geo, d.isoformat()) - 0.5)
            raw.append((d, base + 60.0 * _monsoon(d) + noise))
            d += timedelta(weeks=1)
        peak = max((v for _, v in raw), default=1.0) or 1.0
        return [TrendPoint(date=dd.isoformat(), value=round(max(0.0, min(100.0, 100.0 * v / peak)), 1))
                for dd, v in raw]

    def interest_by_region(self, terms, geo="IN", weeks=12, regions=None):
        q = _query(terms)
        src = regions or _FALLBACK_REGIONS
        raw = []
        for s in src:
            name = s["name"] if isinstance(s, dict) else str(s)
            code = s.get("code", "") if isinstance(s, dict) else ""
            raw.append((name, code, 10.0 + 90.0 * _hash01("region", q, name)))
        # Mirror Google's interest_by_region: rescale so the busiest region = 100.
        peak = max((v for _, _, v in raw), default=0.0) or 1.0
        return [
            RegionInterest(geo_name=n, geo_code=c, value=round(100.0 * v / peak, 1))
            for (n, c, v) in raw
        ]
