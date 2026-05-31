"""IDSP source interface for Layer 3 (Confirmed Cases).

Mirrors the Layer 1 weather-provider and Layer 2 trends-provider patterns: every
source returns the SAME normalized shape (a WeeklyReport of Outbreak rows), so the
Layer 3 orchestrator and the dashboard never know or care whether the data came
from a freshly downloaded IDSP PDF, a saved fixture PDF, or the synthetic sample.
Swapping is a one-line change in build_layer3.py / the IDSP_SOURCE env var.

This is OFFICIAL reported-outbreak data: authoritative ground truth, but it lags
~1-2 weeks and is under-reported. It validates the chain (weather -> searches ->
cases); it never predicts.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Outbreak:
    """One outbreak row pulled from a weekly report.

    `cases`/`deaths` are None when the PDF cell was blank or unparseable (the
    aggregator treats None as "not reported", not as zero). `disease_key` is the
    normalized target bucket (dengue/malaria/chikungunya/fever_rash/afi) or
    "other"; `disease` is the cleaned display label and `raw_disease` keeps the
    original PDF text for auditing.
    """
    disease_key: str
    disease: str
    state: str                 # normalized to the canonical state/UT name where matched
    district: str
    cases: int | None
    deaths: int | None
    status: str = ""           # "Under Surveillance" / "Under Control" etc.
    outbreak_id: str = ""      # IDSP unique ID: State/District/Year/Week/number
    week: int | None = None    # reporting week parsed from the outbreak ID
    year: int | None = None
    raw_disease: str = ""
    raw_state: str = ""


@dataclass
class WeeklyReport:
    """A parsed (or synthesized) IDSP weekly outbreak report.

    `outbreaks` holds EVERY outbreak recovered (all diseases), so totals stay
    honest; the orchestrator tags which are target diseases. `report_week` /
    `report_year` and the period strings describe the week the PDF covers --
    surfaced prominently in the UI so the ~1-2 week lag is always visible.
    """
    outbreaks: list[Outbreak]
    report_week: int | None = None
    report_year: int | None = None
    week_label: str = ""           # e.g. "15th Week, 2026"
    period_label: str = ""         # e.g. "6th April 2026 to 12th April 2026"
    period_start: str = ""         # ISO "YYYY-MM-DD" when derivable, else ""
    period_end: str = ""
    source_pdf_url: str = ""       # where the PDF came from ("" for synthetic sample)
    listing_url: str = ""
    page_count: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def id_anchor_count(self) -> int:
        """How many rows carried a real IDSP unique ID -- a structure signal the
        data-quality guard checks (a broken parse finds none)."""
        return sum(1 for o in self.outbreaks if o.outbreak_id)


class IdspSource(ABC):
    """Base class. Implementations return a normalized WeeklyReport."""

    name: str = "base"
    #: Human-readable attribution string, surfaced in confirmed_cases.json.
    attribution: str = ""
    #: True only for the synthetic sample source, so the dashboard badges it.
    is_sample: bool = False
    #: True when the data is freshly fetched live (vs a saved/old fixture).
    is_live: bool = False

    @abstractmethod
    def fetch_report(self) -> WeeklyReport:
        """Return the latest weekly report as a normalized WeeklyReport.

        Implementations should raise on a hard failure (network / download /
        parse) so the orchestrator's data-quality guard can abort loudly rather
        than publishing garbage to a branded dashboard.
        """
        raise NotImplementedError
