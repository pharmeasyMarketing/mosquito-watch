"""Layer 1 -- Breeding-favorability scoring.

A TRANSPARENT weighted formula (deliberately not machine learning), so the
output can be explained to journalists and public-health readers in a sentence
and tuned by editing config/scoring.json.

The model in one line:
    score = 100 * temperature_suitability * (weighted blend of humidity + recent rain + lagged rain)

Temperature is a *limiting multiplier*, not just another weighted term: if it's
too cold (<~18C) or too hot (>~35C), mosquitoes don't breed no matter how wet or
humid it is, so the whole score is gated to ~0. Within a suitable temperature
band, the score reflects how much standing water (recent + lagged rain) and
humidity favor breeding. Rainfall response is concave with a heavy-rain penalty
(very heavy rain can flush out eggs and larvae). Lagged rain (7-14 days ago)
carries the most weight because adult emergence lags rainfall by ~1-2 weeks.

This is an ENVIRONMENTAL favorability index -- not a case-count prediction and
not a medical/diagnostic tool.
"""
from __future__ import annotations

import math
from datetime import date

from providers.base import DailyWeather


# --- small math helpers -----------------------------------------------------

def clamp01(x: float) -> float:
    return 0.0 if x < 0 else (1.0 if x > 1 else x)


def _mean(values: list) -> float | None:
    nums = [v for v in values if v is not None]
    return sum(nums) / len(nums) if nums else None


def _sum(values: list) -> float:
    """Sum, treating missing (None) days as 0mm -- 'no rain recorded' ~ dry."""
    return float(sum(v for v in values if v is not None))


# --- factor sub-scores (each 0..1) ------------------------------------------

def temperature_suitability(t_mean_c: float, cfg: dict) -> float:
    c = cfg["temperature"]
    lo, opt_lo, opt_hi, hi = c["min_c"], c["opt_low_c"], c["opt_high_c"], c["max_c"]
    if t_mean_c <= lo or t_mean_c >= hi:
        return 0.0
    if t_mean_c < opt_lo:
        return clamp01((t_mean_c - lo) / (opt_lo - lo))
    if t_mean_c <= opt_hi:
        return 1.0
    return clamp01((hi - t_mean_c) / (hi - opt_hi))


def humidity_favorability(rh_pct: float, cfg: dict) -> float:
    h = cfg["humidity"]
    return clamp01((rh_pct - h["low_pct"]) / (h["high_pct"] - h["low_pct"]))


def rain_favorability(total_mm: float, cfg: dict) -> float:
    """Rainfall suitability (v2, model L1-0.2.0), normalized to 0..1.

    A concave, saturating response to accumulated rainfall, with a heavy-rain
    penalty: moderate rain creates and refills the standing water mosquitoes
    breed in, but very heavy rain can flush out eggs and larvae, so favorability
    is non-monotonic.

        S_R(R) = (1 - exp(-R / scale_mm)) * F(R)
        F(R)   = 1                                    if R <= heavy_threshold
               = exp(-(R - heavy_threshold) / decay)  if R >  heavy_threshold
    """
    r = cfg["rainfall"]
    rain = max(0.0, total_mm)
    scale = r.get("scale_mm", 30.0)
    heavy = r.get("heavy_rain_threshold_mm", 150.0)
    decay = r.get("heavy_rain_decay_mm", 100.0)
    base = 1.0 - math.exp(-rain / scale)
    penalty = 1.0 if rain <= heavy else math.exp(-(rain - heavy) / decay)
    return clamp01(base * penalty)


def bucket_for(score: float, cfg: dict) -> str:
    b = cfg["buckets"]
    if score >= b["very_high"]:
        return "Very High"
    if score >= b["high"]:
        return "High"
    if score >= b["moderate"]:
        return "Moderate"
    return "Low"


# --- main entry point -------------------------------------------------------

def score_location(records: list[DailyWeather], cfg: dict) -> dict:
    """Score one location from its normalized daily records.

    Returns {"ok": True, ...full result...} or {"ok": False, "reason": ...}
    so the orchestrator can apply the data-quality guard.
    """
    parsed: list[tuple[date, DailyWeather]] = []
    for r in records:
        try:
            parsed.append((date.fromisoformat(r.date), r))
        except (ValueError, TypeError):
            continue
    if not parsed:
        return {"ok": False, "reason": "no parseable dated records"}

    as_of = max(d for d, _ in parsed)
    w = cfg["windows"]
    cur_days, lag_s, lag_e = w["current_days"], w["lag_start_day"], w["lag_end_day"]

    current = [r for d, r in parsed if 0 <= (as_of - d).days < cur_days]
    lagged = [r for d, r in parsed if lag_s <= (as_of - d).days < lag_e]

    temp_mean = _mean([r.temp_mean_c for r in current])
    humidity = _mean([r.humidity_pct for r in current])
    rain_recent_mm = _sum([r.precip_mm for r in current])
    rain_lagged_mm = _sum([r.precip_mm for r in lagged])

    if temp_mean is None:
        return {"ok": False, "reason": "no temperature data in current window"}

    tf = temperature_suitability(temp_mean, cfg)
    hf = humidity_favorability(humidity, cfg) if humidity is not None else 0.0
    rr = rain_favorability(rain_recent_mm, cfg)
    rl = rain_favorability(rain_lagged_mm, cfg)

    wt = cfg["weights"]
    within_temp = wt["humidity"] * hf + wt["rain_recent"] * rr + wt["rain_lagged"] * rl
    score = round(100.0 * tf * within_temp, 1)

    latest = max(parsed, key=lambda p: p[0])[1]

    return {
        "ok": True,
        "score": score,
        "bucket": bucket_for(score, cfg),
        "components": {
            "temperature_suitability": round(tf, 3),
            "humidity": round(hf, 3),
            "rain_recent": round(rr, 3),
            "rain_lagged": round(rl, 3),
        },
        "inputs": {
            "as_of_date": as_of.isoformat(),
            "temp_mean_c": round(temp_mean, 1),
            "temp_max_c": round(latest.temp_max_c, 1) if latest.temp_max_c is not None else None,
            "temp_min_c": round(latest.temp_min_c, 1) if latest.temp_min_c is not None else None,
            "humidity_pct": round(humidity, 1) if humidity is not None else None,
            "rain_recent_mm": round(rain_recent_mm, 1),
            "rain_lagged_mm": round(rain_lagged_mm, 1),
            "days_in_current_window": len(current),
            "days_in_lagged_window": len(lagged),
        },
    }
