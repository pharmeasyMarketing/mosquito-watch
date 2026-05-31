"""PyTrends provider (real, unofficial -- dev / light use only).

Reads Google Trends through the community `pytrends` library. PyTrends is
ARCHIVED / read-only since 2025-04-17, unmaintained, and easily rate-limited --
fine for development or light personal use, NOT recommended for a branded
production dashboard. For production, use a managed Trends API behind this same
interface (see serpapi.py).

`pytrends` is an OPTIONAL dependency: it is imported LAZILY inside the methods so
that merely registering this provider never breaks the zero-dependency default
(the mock). Install it only if you want to use this provider:

    pip install pytrends
"""
from __future__ import annotations

from .base import RegionInterest, TrendPoint, TrendsProvider


def _timeframe(weeks: int) -> str:
    """Map a week count onto the nearest Google Trends timeframe token."""
    if weeks <= 5:
        return "today 1-m"
    if weeks <= 13:
        return "today 3-m"
    if weeks <= 52:
        return "today 12-m"
    return "today 5-y"


class PyTrendsProvider(TrendsProvider):
    name = "pytrends"
    attribution = "Google Trends via pytrends (unofficial, archived 2025-04-17)"

    def _client(self):
        try:
            from pytrends.request import TrendReq  # lazy: optional dependency
        except ImportError as err:
            raise RuntimeError(
                "pytrends is not installed. Run `pip install pytrends`, "
                "or use --provider mock / --provider serpapi."
            ) from err
        # tz is an offset in minutes; 330 = IST (UTC+5:30).
        return TrendReq(hl="en-IN", tz=330)

    def interest_over_time(self, terms, geo="IN", weeks=12):
        kw = " + ".join(terms)
        py = self._client()
        py.build_payload([kw], geo=geo, timeframe=_timeframe(weeks))
        df = py.interest_over_time()
        if df is None or df.empty or kw not in df.columns:
            raise RuntimeError(f"pytrends returned no interest_over_time for {kw!r}")
        points = []
        for idx, row in df.iterrows():
            # Skip the trailing partial week pytrends flags, if present.
            if "isPartial" in df.columns and bool(row.get("isPartial")):
                continue
            points.append(TrendPoint(date=idx.date().isoformat(), value=float(row[kw])))
        return points[-weeks:]

    def interest_by_region(self, terms, geo="IN", weeks=12, regions=None):
        kw = " + ".join(terms)
        py = self._client()
        py.build_payload([kw], geo=geo, timeframe=_timeframe(weeks))
        df = py.interest_by_region(resolution="REGION", inc_low_vol=True, inc_geo_code=False)
        if df is None or df.empty or kw not in df.columns:
            raise RuntimeError(f"pytrends returned no interest_by_region for {kw!r}")
        return [RegionInterest(geo_name=str(name), value=float(row[kw])) for name, row in df.iterrows()]
