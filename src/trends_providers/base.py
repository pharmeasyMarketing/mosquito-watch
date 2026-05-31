"""Trends-provider interface for Layer 2 (Fever Signal).

Mirrors the Layer 1 weather-provider pattern (src/providers/): every provider
returns the SAME normalized shapes (TrendPoint / RegionInterest) so the Layer 2
orchestrator and the dashboard never know or care which source produced the
numbers. Swapping the mock for PyTrends or a managed API (SerpApi, ...) is a
one-line change in build_layer2.py / the TRENDS_PROVIDER env var.

Google Trends values are RELATIVE and normalized 0-100, not absolute counts:
  - interest_over_time : the series peaks at 100 within its own time window.
  - interest_by_region : the busiest region scores 100 for that query + window.
That relativity is a core caveat surfaced in the dashboard.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class TrendPoint:
    """One weekly point of normalized search interest (0-100, relative)."""
    date: str       # ISO date of the week, "YYYY-MM-DD"
    value: float


@dataclass
class RegionInterest:
    """Normalized search interest for one sub-region (state/UT), 0-100, relative."""
    geo_name: str          # state/UT name, e.g. "Kerala"
    value: float
    geo_code: str = ""     # ISO-3166-2 code if the provider supplies one


class TrendsProvider(ABC):
    """Base class. Implementations fetch raw Trends data and normalize it."""

    name: str = "base"
    #: Human-readable attribution string, surfaced in fever_signal.json.
    attribution: str = ""
    #: True only for synthetic/sample sources, so the dashboard can badge them.
    is_sample: bool = False

    @abstractmethod
    def interest_over_time(self, terms: list[str], geo: str = "IN", weeks: int = 12) -> list[TrendPoint]:
        """Weekly interest-over-time for the combined `terms`, oldest first.

        `terms` is a group's term list; providers OR them into one query
        (Google Trends treats " + " as OR). Raise on a hard failure
        (network/parse) so the orchestrator counts it as a failed group rather
        than publishing garbage.
        """
        raise NotImplementedError

    @abstractmethod
    def interest_by_region(
        self, terms: list[str], geo: str = "IN", weeks: int = 12, regions: list | None = None
    ) -> list[RegionInterest]:
        """Latest interest split by sub-region (India states/UTs) for `terms`.

        `regions` is an OPTIONAL hint (list of {"name","code"} dicts) of the
        sub-regions to report. Providers that auto-discover regions (PyTrends,
        SerpApi) may ignore it; the mock uses it to know which synthetic regions
        to emit. Raise on a hard failure.
        """
        raise NotImplementedError
