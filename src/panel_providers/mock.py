"""Mock / sample Fever Panel provider (DEFAULT until the backend feed is wired).

Generates DETERMINISTIC, clearly-synthetic Fever Panel numbers so the Layer 3 v1
pipeline and dashboard can be built and demoed without real PharmEasy diagnostics
data. The numbers are NOT real -- is_sample=True flows all the way into
panel_signal.json, and the dashboard badges the layer as sample / coming soon so
nobody mistakes it for a live signal.

Shape of the demo:
  - tests booked rise through the monsoon and peak around early September;
  - positivity per disease follows a disease-specific monsoon curve;
  - this_year (the partial season) tracks last_year's same week -- tests a little
    higher (demand growth), positivity roughly level -- so the year-over-year
    "same week" comparison renders sensibly.

Determinism: every wiggle is derived from a SHA-256 hash of a seed string, so
re-runs produce identical numbers (no random churn in the committed data file).
"""
from __future__ import annotations

import hashlib
import math

from .base import PanelProvider, SeriesPoint

# How many weeks of the CURRENT season to emit (a partial "season so far"); the
# real this_year series will instead come from the weekly backend feed.
THIS_YEAR_WEEKS = 5

# Positivity curves, per disease: (base %, peak %, peak-week index, gaussian width).
_POSITIVITY = {
    "dengue":      (5.0, 30.0, 19, 5.0),
    "malaria":     (4.0, 16.0, 17, 6.0),
    "chikungunya": (2.0, 11.0, 20, 5.0),
    "typhoid":     (9.0, 22.0, 14, 7.0),
}
_POSITIVITY_DEFAULT = (4.0, 18.0, 18, 6.0)

# Tests-booked curve: (base count, peak count, peak-week index, gaussian width).
_TESTS = (7000.0, 24000.0, 17, 6.5)


def _hash01(*parts) -> float:
    """Deterministic pseudo-random float in [0, 1) from the given parts."""
    seed = "|".join(str(p) for p in parts)
    return (int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16) % 1_000_000) / 1_000_000.0


def _gauss(w: float, center: float, width: float) -> float:
    return math.exp(-((w - center) ** 2) / (2.0 * width * width))


def _total_weeks(season: dict) -> int:
    """Weeks spanned by the season window (mirrors the dashboard's totalWeeks)."""
    sm, em = season.get("start_month", 5), season.get("end_month", 10)
    return max(1, round((em - sm + 1) * 4.345))


class MockPanelProvider(PanelProvider):
    name = "mock"
    attribution = "SAMPLE synthetic data for development -- not real PharmEasy diagnostics"
    is_sample = True

    def _ref_tests(self, w: int) -> float:
        base, peak, c, wd = _TESTS
        return base + (peak - base) * _gauss(w, c, wd)

    def _ref_pos(self, disease: str, w: int) -> float:
        base, peak, c, wd = _POSITIVITY.get(disease, _POSITIVITY_DEFAULT)
        return base + (peak - base) * _gauss(w, c, wd)

    def _weeks(self, year: int, season: dict) -> int:
        full = _total_weeks(season)
        return full if year == season.get("last_year") else min(THIS_YEAR_WEEKS, full)

    def tests_series(self, year, season):
        last_year = season.get("last_year")
        out = []
        for w in range(self._weeks(year, season)):
            ref = self._ref_tests(w)
            if year == last_year:
                val = ref * (1.0 + 0.06 * (_hash01("tests", year, w) - 0.5))      # +/-3% wiggle
            else:
                val = ref * (1.08 + 0.05 * (_hash01("tests", year, w) - 0.5))     # ~+8% YoY, small noise
            out.append(SeriesPoint(week=w, value=round(max(0.0, val) / 50.0) * 50))
        return out

    def positivity_series(self, disease, year, season):
        last_year = season.get("last_year")
        out = []
        for w in range(self._weeks(year, season)):
            ref = self._ref_pos(disease, w)
            if year == last_year:
                val = ref + 1.6 * (_hash01("pos", disease, year, w) - 0.5)        # +/-0.8 abs wiggle
            else:
                val = ref * (1.0 + 0.10 * (_hash01("pos", disease, year, w) - 0.5))  # +/-5% rel
            out.append(SeriesPoint(week=w, value=round(max(0.0, min(100.0, val)), 1)))
        return out
