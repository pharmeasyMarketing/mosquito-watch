"""Live IDSP source: discover -> download -> parse the newest weekly report.

Wires stage 1 (fetch.py: listing-page discovery + download, both hosts) to stage
2 (parse.py: coordinate-based table parse). This is the production path; it needs
network access and pdfplumber. Everything raises loudly on failure so the
orchestrator's data-quality guard aborts rather than publishing garbage.

Knobs (env):
  IDSP_INSECURE=1   disable TLS verification (escape hatch for a gov cert lapse).
Config:
  manual_pdf_url    if set, skip discovery and download exactly this URL (pin a
                    week, or route around a listing-page redesign).
"""
from __future__ import annotations

import os

from .base import IdspSource, WeeklyReport


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


class LiveIdspSource(IdspSource):
    name = "live"
    attribution = ("IDSP Weekly Outbreak Reports, Ministry of Health & Family Welfare "
                   "(idsp.mohfw.gov.in)")
    is_sample = False
    is_live = True

    def __init__(self, config: dict):
        self.config = config
        self.insecure = _truthy("IDSP_INSECURE")

    def fetch_report(self) -> WeeklyReport:
        from . import fetch, parse  # lazy: network + pdfplumber only on this path

        cfg = self.config
        listing = cfg.get("listing_url", "")
        manual = (cfg.get("manual_pdf_url") or "").strip()

        if manual:
            disc = {"pdf_url": manual, "week": None, "year": None, "week_label": "", "host": "manual"}
        else:
            if not listing:
                raise RuntimeError("config.listing_url is not set; cannot discover the latest report.")
            disc = fetch.discover_latest(listing, insecure=self.insecure)

        data = fetch.download_pdf(disc["pdf_url"], insecure=self.insecure)
        report = parse.parse_pdf(data, cfg)
        report.source_pdf_url = disc["pdf_url"]
        report.listing_url = listing

        # The listing page is an authoritative source of the week number; prefer
        # the PDF's own header text, but fall back to discovery when the parser
        # could not read it.
        if report.report_week is None and disc.get("week"):
            report.report_week = disc["week"]
        if report.report_year is None and disc.get("year"):
            report.report_year = disc["year"]
        if not report.week_label and disc.get("week_label"):
            report.week_label = disc["week_label"]
        if disc["host"] != "manual":
            report.notes.append(f"downloaded from {disc['host']}")
        if self.insecure:
            report.notes.append("TLS verification disabled (IDSP_INSECURE)")
        return report
