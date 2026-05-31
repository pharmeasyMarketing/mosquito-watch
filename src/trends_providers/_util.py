"""Shared helpers for Layer 2 trend providers.

Env / multi-key loading (with the Windows .env gotchas handled once), secret
masking, value/date normalization, weekly resampling, and a billing-error
heuristic -- used by BOTH the Apify and SerpApi providers, so the failover and
data-shaping logic lives in exactly one place.
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta, timezone

from .base import TrendPoint

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ENV_FILES = (".env", "apify.env", "serpapi.env")


# --- config / multi-key loading ---------------------------------------------

def read_env_file() -> dict:
    """KEY=VALUE pairs from a gitignored env file at the project root.

    Tolerates a UTF-8 BOM (Notepad), an `export ` prefix, comments, and quotes.
    Earlier files win; a real environment variable still overrides everything
    (see settings()).
    """
    out: dict[str, str] = {}
    for fname in _ENV_FILES:
        path = os.path.join(ROOT, fname)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8-sig") as fh:
            for raw in fh:
                line = raw.strip()
                if line.startswith("export "):
                    line = line[len("export "):].strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                out.setdefault(key.strip(), val.strip().strip('"').strip("'"))
    return out


def settings() -> dict:
    """Merged settings: real env vars win, then env-file values fill the gaps."""
    merged = dict(read_env_file())
    merged.update({k: v for k, v in os.environ.items() if v})
    return merged


def num_setting(s: dict, key: str, default):
    val = s.get(key)
    if val in (None, ""):
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def load_keys(prefix: str, s: dict | None = None) -> list[str]:
    """Ordered, de-duplicated secrets for a given prefix.

    Priority: <prefix>, then <prefix>_2/_3/... (numeric order), then any
    comma/space/newline list in <prefix>S. E.g. prefix="SERPAPI_KEY" reads
    SERPAPI_KEY, SERPAPI_KEY_2, ..., and SERPAPI_KEYS.
    """
    s = s if s is not None else settings()
    keys: list[str] = []
    if s.get(prefix):
        keys.append(s[prefix].strip())
    numbered = []
    pat = re.compile(rf"{re.escape(prefix)}_(\d+)$")
    for k, v in s.items():
        m = pat.match(k)
        if m and v and v.strip():
            numbered.append((int(m.group(1)), v.strip()))
    keys.extend(v for _, v in sorted(numbered))
    listed = s.get(prefix + "S")
    if listed:
        keys.extend(p for p in re.split(r"[,\s]+", listed.strip()) if p)
    seen: set[str] = set()
    return [k for k in keys if k and not (k in seen or seen.add(k))]


def mask(secret: str) -> str:
    t = secret or ""
    return (t[:10] + "..." + t[-4:]) if len(t) >= 16 else "key"


# --- data normalization -----------------------------------------------------

def date_token(weeks: int) -> str:
    """Map a week count onto the Google-Trends time-range token (shared by both
    providers: Apify's `timeRange` and SerpApi's `date` use the same vocabulary)."""
    if weeks <= 5:
        return "today 1-m"
    if weeks <= 13:
        return "today 3-m"
    if weeks <= 52:
        return "today 12-m"
    return "today 5-y"


def first_value(v) -> float:
    """Google Trends `value` may be an array (one entry per compared query),
    a numeric string, or a number. Coerce to a float, defaulting to 0.0."""
    if isinstance(v, list):
        v = v[0] if v else None
    if v is None or v == "":
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def ts_to_date(ts, fallback) -> str:
    """Unix timestamp (seconds, often a string) -> ISO date, else `fallback`."""
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError):
        return str(fallback or "")


def to_weekly(pairs: list[tuple[str, float]]) -> list[TrendPoint]:
    """Resample (iso_date, value) pairs to weekly TrendPoints.

    Google Trends returns DAILY resolution for short windows (~90 days), but the
    mock provider, orchestrator, and dashboard all assume WEEKLY points (so
    `delta_4w` means four weeks). Bucket by ISO week, average, label by week-start.
    """
    buckets: dict[tuple, dict] = {}
    for iso, val in pairs:
        try:
            dt = date.fromisoformat(iso)
        except (ValueError, TypeError):
            continue
        y, w, _ = dt.isocalendar()
        b = buckets.setdefault((y, w), {"dates": [], "vals": []})
        b["dates"].append(dt)
        b["vals"].append(val)
    out = []
    for k in sorted(buckets):
        b = buckets[k]
        start = min(b["dates"])
        monday = start - timedelta(days=start.weekday())
        out.append(TrendPoint(date=monday.isoformat(), value=round(sum(b["vals"]) / len(b["vals"]), 1)))
    return out


def looks_like_billing(err: Exception) -> bool:
    """Heuristic: does this error look like an out-of-budget / out-of-searches /
    bad-key problem (so we should fail over to the next key) rather than a
    transient blip (so we should not)?"""
    s = str(err).lower()
    return any(tok in s for tok in (
        " 401", " 402", " 403", " 429", "payment", "unauthorized", "forbidden",
        "usage limit", "quota", "exceeded", "insufficient", "credit",
        "out of searches", "ran out of searches", "no searches left",
    ))
