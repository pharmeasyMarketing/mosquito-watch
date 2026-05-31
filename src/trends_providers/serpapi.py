"""SerpApi provider (managed Google Trends API -- a production candidate).

Calls SerpApi's `google_trends` engine over plain HTTPS (stdlib only). Unlike
Apify, the timeline and the by-state breakdown are SEPARATE calls:
    interest_over_time  -> data_type=TIMESERIES
    interest_by_region  -> data_type=GEO_MAP_0  (single-query "interest by region")
so a full 4-group build is 2 searches/group * 4 = 8 searches. It is fast
(seconds, not minutes) and, on SerpApi's trial caps, free.

Multi-key failover: set one or more keys via env / .env files:
    SERPAPI_KEY=primary
    SERPAPI_KEY_2=backup                     # ...or SERPAPI_KEYS=a,b,c
Before each search the provider checks the active key's remaining monthly
searches (GET /account.json -- free, NOT counted against the quota) and rotates
to the next key when it runs low (or hits a self-imposed cap). An out-of-searches
/ auth error mid-build also fails over. Knobs (env / .env):
    SERPAPI_MIN_RESERVE            switch when fewer than this many searches remain (default 3)
    SERPAPI_MAX_SEARCHES_PER_KEY   our self-measured cap per key (default: none)
Check balances: python src/serpapi_balances.py
"""
from __future__ import annotations

from httputil import build_url, get_json  # stdlib helpers (src/ is on sys.path)

from ._util import (date_token, first_value, load_keys, looks_like_billing,
                    mask, num_setting, settings, to_weekly, ts_to_date)
from .base import RegionInterest, TrendPoint, TrendsProvider

ENDPOINT = "https://serpapi.com/search.json"
ACCOUNT_ENDPOINT = "https://serpapi.com/account.json"
IST_TZ = "-330"  # SerpApi tz is minutes of (UTC - local); IST is UTC+5:30
DEFAULT_MIN_RESERVE = 3.0


def _load_keys() -> list[str]:
    keys = load_keys("SERPAPI_KEY")
    if not keys:
        raise RuntimeError(
            "No SerpApi key found. Add SERPAPI_KEY=... (and optionally SERPAPI_KEY_2, ...) "
            "to a .env / serpapi.env at the project root, or use --provider mock."
        )
    return keys


def _searches_left(key: str) -> float | None:
    """Remaining monthly searches for this key (None on failure). The account
    endpoint is free and is NOT counted against the quota."""
    try:
        data = get_json(build_url(ACCOUNT_ENDPOINT, {"api_key": key}), timeout=20, retries=2)
        left = data.get("total_searches_left")
        return None if left is None else float(left)
    except Exception:
        return None


class SerpApiTrendsProvider(TrendsProvider):
    name = "serpapi"
    attribution = "Google Trends via SerpApi"

    def __init__(self) -> None:
        s = settings()
        self._keys = _load_keys()
        self._ki = 0
        self._used: dict[str, int] = {k: 0 for k in self._keys}
        self.min_reserve = num_setting(s, "SERPAPI_MIN_RESERVE", DEFAULT_MIN_RESERVE)
        self.max_searches_per_key = num_setting(s, "SERPAPI_MAX_SEARCHES_PER_KEY", None)
        self.searches_total = 0
        self.switch_log: list[dict] = []
        self.keys_used: set[str] = set()

    def _switch(self, key: str, reason: str) -> None:
        self.switch_log.append({"from_key": mask(key), "reason": reason})
        self._ki += 1

    def _ensure_key(self) -> str:
        while self._ki < len(self._keys):
            key = self._keys[self._ki]
            cap = self.max_searches_per_key
            if cap is not None and self._used.get(key, 0) >= cap:
                self._switch(key, f"reached self-imposed cap {int(cap)} searches")
                continue
            left = _searches_left(key)
            if left is not None and left < (self.min_reserve or 0):
                self._switch(key, f"only {int(left)} searches left (< {int(self.min_reserve or 0)} reserve)")
                continue
            return key
        raise RuntimeError(
            f"All {len(self._keys)} SerpApi key(s) are out of searches. "
            "Add another SERPAPI_KEY_N, top up the plan, or use --provider mock."
        )

    def _search(self, params: dict) -> dict:
        """Run one SerpApi search (1 quota search) with key failover."""
        while True:
            key = self._ensure_key()
            url = build_url(ENDPOINT, {**params, "api_key": key})
            try:
                data = get_json(url, timeout=40, retries=2)
                if isinstance(data, dict) and data.get("error"):
                    raise RuntimeError(f"SerpApi error: {data['error']}")
            except Exception as err:
                if looks_like_billing(err):
                    self._switch(key, f"failing over: {err}")
                    continue
                raise
            self._used[key] = self._used.get(key, 0) + 1
            self.searches_total += 1
            self.keys_used.add(mask(key))
            return data

    def meta(self) -> dict:
        return {
            "keys_configured": len(self._keys),
            "keys_used": sorted(self.keys_used),
            "searches_total": self.searches_total,
            "searches_by_key": {mask(k): v for k, v in self._used.items() if v},
            "switches": self.switch_log,
        }

    def interest_over_time(self, terms, geo="IN", weeks=12):
        q = " + ".join(terms)
        data = self._search({
            "engine": "google_trends", "data_type": "TIMESERIES",
            "q": q, "geo": geo, "date": date_token(weeks), "tz": IST_TZ,
        })
        timeline = (data.get("interest_over_time") or {}).get("timeline_data") or []
        if not timeline:
            raise RuntimeError(f"SerpApi returned no TIMESERIES timeline for {q!r}")
        pairs = []
        for row in timeline:
            vals = row.get("values") or []
            value = first_value(vals[0].get("extracted_value") if vals else None)
            pairs.append((ts_to_date(row.get("timestamp"), row.get("date")), value))
        weekly = to_weekly(pairs)
        if len(weekly) < 2:
            raise RuntimeError("SerpApi timeline did not resample to enough weekly points")
        return weekly[-weeks:]

    def interest_by_region(self, terms, geo="IN", weeks=12, regions=None):
        q = " + ".join(terms)
        data = self._search({
            "engine": "google_trends", "data_type": "GEO_MAP_0",
            "q": q, "geo": geo, "region": "REGION", "date": date_token(weeks), "tz": IST_TZ,
        })
        rows = data.get("interest_by_region") or []
        if not rows:
            raise RuntimeError(f"SerpApi returned no GEO_MAP_0 regions for {q!r}")
        out = []
        for r in rows:
            raw = r.get("extracted_value")
            out.append(RegionInterest(
                geo_name=str(r.get("location", "")),
                geo_code=str(r.get("geo", "")),
                value=first_value(raw if raw is not None else r.get("value")),
            ))
        return out
