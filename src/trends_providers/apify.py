"""Apify provider (managed Google Trends scraping).

Runs the official `apify/google-trends-scraper` actor through Apify's REST API
and normalizes the result to the TrendsProvider interface. Stdlib HTTP only.

One actor run returns BOTH the interest-over-time timeline AND the regional
breakdown (interestBySubregion = India states), so we run the actor ONCE per
group and cache it (4 runs per build, not 8). Plain HTTPS, so it works in a
headless cron. Trade-off vs SerpApi: each run takes minutes and bills compute
(~$0.07-0.10/run here), so daily builds get expensive -- see README.

Auth + multi-token failover: set one or more tokens via env / .env files:
    APIFY_TOKEN=apify_api_primary
    APIFY_TOKEN_2=apify_api_backup           # ...or APIFY_TOKENS=a,b,c
Before each run the provider checks the active token's remaining monthly budget
(GET /v2/users/me/limits) and rotates to the next token when it runs low (or
hits a self-imposed per-token cap). A billing/auth error mid-run also fails over.
Knobs (env / .env): APIFY_MIN_RESERVE_USD, APIFY_MAX_SPEND_PER_TOKEN_USD,
APIFY_EST_RUN_COST_USD. Check balances: python src/apify_balances.py
"""
from __future__ import annotations

import time

from httputil import get_json, post_json  # stdlib helpers (src/ is on sys.path)

from ._util import (date_token, first_value, load_keys, looks_like_billing,
                    mask, num_setting, settings, to_weekly, ts_to_date)
from .base import RegionInterest, TrendPoint, TrendsProvider

ACTOR = "apify~google-trends-scraper"  # "/" is written as "~" in the REST path
RUNS_ENDPOINT = f"https://api.apify.com/v2/acts/{ACTOR}/runs"
RUN_STATUS_ENDPOINT = "https://api.apify.com/v2/actor-runs/{run_id}"
DATASET_ITEMS_ENDPOINT = "https://api.apify.com/v2/datasets/{dataset_id}/items"
LIMITS_ENDPOINT = "https://api.apify.com/v2/users/me/limits"
POLL_INTERVAL_S = 5.0
MAX_WAIT_S = 540.0  # one run scrapes timeline + all regions/cities; allow ~9 min
DEFAULT_MIN_RESERVE_USD = 0.10
DEFAULT_EST_RUN_COST_USD = 0.05


def _load_tokens() -> list[str]:
    keys = load_keys("APIFY_TOKEN")
    if not keys:
        raise RuntimeError(
            "No Apify token found. Add APIFY_TOKEN=apify_api_... (and optionally "
            "APIFY_TOKEN_2, ...) to a .env / apify.env at the project root, or use --provider mock."
        )
    return keys


_mask = mask  # re-exported for apify_balances.py


def _account_remaining_usd(token: str) -> float | None:
    """Remaining monthly usage budget (USD) for this token's account, or None."""
    try:
        data = get_json(
            LIMITS_ENDPOINT, timeout=20, retries=2,
            headers={"Authorization": "Bearer " + token},
        ).get("data") or {}
        mx = (data.get("limits") or {}).get("maxMonthlyUsageUsd")
        cur = (data.get("current") or {}).get("monthlyUsageUsd")
        if mx is None or cur is None:
            return None
        return float(mx) - float(cur)
    except Exception:
        return None


class ApifyTrendsProvider(TrendsProvider):
    name = "apify"
    attribution = "Google Trends via Apify (apify/google-trends-scraper)"

    def __init__(self) -> None:
        s = settings()
        self._tokens = _load_tokens()
        self._ti = 0
        self._spend: dict[str, float] = {t: 0.0 for t in self._tokens}
        self.min_reserve_usd = num_setting(s, "APIFY_MIN_RESERVE_USD", DEFAULT_MIN_RESERVE_USD)
        self.est_run_cost_usd = num_setting(s, "APIFY_EST_RUN_COST_USD", DEFAULT_EST_RUN_COST_USD)
        self.max_spend_per_token_usd = num_setting(s, "APIFY_MAX_SPEND_PER_TOKEN_USD", None)
        self._cache: dict[tuple, dict] = {}
        self.cost_usd_total = 0.0
        self.run_costs: list[dict] = []
        self.switch_log: list[dict] = []
        self.tokens_used: set[str] = set()

    def _switch(self, token: str, reason: str) -> None:
        self.switch_log.append({"from_token": mask(token), "reason": reason})
        self._ti += 1

    def _ensure_token(self, need_usd: float) -> str:
        while self._ti < len(self._tokens):
            token = self._tokens[self._ti]
            cap = self.max_spend_per_token_usd
            if cap is not None and self._spend.get(token, 0.0) >= cap:
                self._switch(token, f"reached self-imposed cap ${cap:.2f}")
                continue
            remaining = _account_remaining_usd(token)
            threshold = max(self.min_reserve_usd or 0.0, need_usd)
            if remaining is not None and remaining < threshold:
                self._switch(token, f"account budget ${remaining:.2f} below ${threshold:.2f}")
                continue
            return token
        raise RuntimeError(
            f"All {len(self._tokens)} Apify token(s) are out of budget or exhausted. "
            "Add another APIFY_TOKEN_N, top up the account, or use --provider mock."
        )

    def _wait(self, run_id: str, status: str | None, headers: dict) -> dict:
        waited = 0.0
        run: dict = {}
        while status != "SUCCEEDED":
            if status in ("FAILED", "ABORTED", "TIMED-OUT", "TIMING-OUT"):
                raise RuntimeError(f"Apify run ended with status {status}")
            if waited >= MAX_WAIT_S:
                raise RuntimeError(f"Apify run did not finish within {int(MAX_WAIT_S)}s (last status {status})")
            time.sleep(POLL_INTERVAL_S)
            waited += POLL_INTERVAL_S
            run = get_json(RUN_STATUS_ENDPOINT.format(run_id=run_id), timeout=30, retries=2, headers=headers).get("data") or {}
            status = run.get("status")
        if run.get("usageTotalUsd") is None:  # cost can lag the SUCCEEDED flip
            run = get_json(RUN_STATUS_ENDPOINT.format(run_id=run_id), timeout=30, retries=2, headers=headers).get("data") or {}
        return run

    def _run(self, terms, geo, weeks, date=None) -> dict:
        query = " + ".join(terms)          # Google Trends OR operator -> one series
        is_span = bool(date and " " in str(date))
        tr = str(date) if is_span else date_token(weeks)
        key = (query, geo, tr)
        if key in self._cache:
            return self._cache[key]
        payload = {"searchTerms": [query], "geo": geo}
        payload["customTimeRange" if is_span else "timeRange"] = tr
        measured = [c["usd"] for c in self.run_costs if c.get("usd") is not None]
        need = max([self.est_run_cost_usd or 0.0] + measured)

        while True:
            token = self._ensure_token(need)
            headers = {"Authorization": "Bearer " + token}
            try:
                run = post_json(RUNS_ENDPOINT, payload, timeout=60, retries=1, headers=headers).get("data") or {}
                run_id, dataset_id = run.get("id"), run.get("defaultDatasetId")
                if not run_id or not dataset_id:
                    raise RuntimeError("Apify did not return a run id / dataset id")
                run_obj = self._wait(run_id, run.get("status"), headers)
                items = get_json(DATASET_ITEMS_ENDPOINT.format(dataset_id=dataset_id), timeout=60, retries=2, headers=headers)
                if not isinstance(items, list) or not items:
                    raise RuntimeError(f"Apify run produced no dataset items for {query!r}")
            except Exception as err:
                if looks_like_billing(err):
                    self._switch(token, f"billing/auth error, failing over: {err}")
                    continue
                raise

            cost = run_obj.get("usageTotalUsd")
            self.tokens_used.add(mask(token))
            if cost is not None:
                self._spend[token] = self._spend.get(token, 0.0) + float(cost)
                self.cost_usd_total += float(cost)
            self.run_costs.append({"query": query, "usd": cost, "token": mask(token)})
            self._cache[key] = items[0]
            return items[0]

    def meta(self) -> dict:
        return {
            "tokens_configured": len(self._tokens),
            "tokens_used": sorted(self.tokens_used),
            "cost_usd_total": round(self.cost_usd_total, 6),
            "run_costs": self.run_costs,
            "switches": self.switch_log,
        }

    def interest_over_time(self, terms, geo="IN", weeks=12, date=None):
        item = self._run(terms, geo, weeks, date=date)
        timeline = (
            item.get("interestOverTime_timelineData")
            or (item.get("interestOverTime") or {}).get("timelineData")
            or []
        )
        if not timeline:
            raise RuntimeError("Apify result had no interest-over-time timeline data")
        pairs = [(ts_to_date(r.get("time"), r.get("formattedAxisTime")), first_value(r.get("value"))) for r in timeline]
        weekly = to_weekly(pairs)
        if len(weekly) < 2:
            raise RuntimeError("Apify timeline did not resample to enough weekly points")
        # A custom `date` span (year-over-year) keeps ALL weeks; the rolling
        # weeks-based window truncates to the most recent `weeks`.
        return weekly if date else weekly[-weeks:]

    def interest_by_region(self, terms, geo="IN", weeks=12, regions=None):
        item = self._run(terms, geo, weeks)
        rows = (
            item.get("interestBySubregion")
            or item.get("interestByRegion")
            or item.get("interestBy")
            or item.get("interestByCity")
            or []
        )
        if not rows:
            raise RuntimeError("Apify result had no regional interest (interestBySubregion/interestBy)")
        return [
            RegionInterest(
                geo_name=str(r.get("geoName", "") or r.get("name", "")),
                geo_code=str(r.get("geoCode", "") or r.get("code", "")),
                value=first_value(r.get("value")),
            )
            for r in rows
        ]
