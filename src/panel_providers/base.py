"""Panel-provider interface for Layer 3 v1 (Fever Panel).

Mirrors the Layer 2 trends-provider pattern (src/trends_providers/): every
provider returns the SAME normalized shape (a list of SeriesPoint per metric and
year) so the Layer 3 orchestrator and the dashboard never know or care which
source produced the numbers. Swapping the synthetic `mock` for the real weekly
backend feed (`googlesheet`) is a one-line change in build_layer3_panel.py / the
PANEL_SOURCE env var.

Two metrics, both shown year-over-year (last_year reference vs this_year so far):
  - tests       : overall Fever Panel test volume (a count; one series per year).
  - positivity  : share of panels positive for a disease (a percent, 0-100;
                  one series per disease per year).

Each series is a list of SeriesPoint, oldest first, indexed by a 0-based
season-relative WEEK (week 0 = the first week of start_month), which is exactly
how Layer 2's year-over-year chart positions its points.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SeriesPoint:
    """One weekly point. `week` is a 0-based season-relative week index; `value`
    is a test count (kind='count') or a positivity percent 0-100 (kind='percent')."""
    week: int
    value: float


class PanelProvider(ABC):
    """Base class. Implementations supply the Fever Panel series for a given year."""

    name: str = "base"
    #: Human-readable attribution, surfaced in panel_signal.json.
    attribution: str = ""
    #: True only for synthetic/sample sources, so the dashboard can badge them.
    is_sample: bool = False

    @abstractmethod
    def tests_series(self, year: int, season: dict) -> list[SeriesPoint]:
        """Overall Fever Panel tests booked, week by week, for `year`. Oldest
        first. `this_year` is typically a partial season (season so far). Raise on
        a hard failure so the orchestrator aborts rather than publishing garbage."""
        raise NotImplementedError

    @abstractmethod
    def positivity_series(self, disease: str, year: int, season: dict) -> list[SeriesPoint]:
        """Positivity percent (0-100) for one `disease` key, week by week, for
        `year`. Oldest first. Raise on a hard failure."""
        raise NotImplementedError
