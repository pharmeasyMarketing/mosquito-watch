"""Fixture IDSP source: parse a saved real weekly PDF offline.

This is the "local sample PDF" source from the brief -- it runs the REAL parser
(parse.py) against a known, committed weekly report (config.fixture_pdf) with no
network, so the parser and dashboard can be developed and regression-tested
offline against ground truth. The data is genuine IDSP data (is_sample=False),
just from a fixed/older week rather than freshly fetched (is_live=False), so the
dashboard surfaces the report week + lag honestly.

Needs pdfplumber (imported lazily inside parse.py); no network.
"""
from __future__ import annotations

import os

from .base import IdspSource, WeeklyReport

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FixtureIdspSource(IdspSource):
    name = "fixture"
    attribution = "IDSP Weekly Outbreak Report (saved sample PDF, parsed offline)"
    is_sample = False
    is_live = False

    def __init__(self, config: dict):
        self.config = config

    def fetch_report(self) -> WeeklyReport:
        from . import parse  # lazy: pulls pdfplumber only when actually parsing

        rel = (self.config.get("fixture_pdf") or "").strip()
        if not rel:
            raise RuntimeError("config.fixture_pdf is not set; cannot use the fixture source.")
        path = rel if os.path.isabs(rel) else os.path.join(_ROOT, rel)
        if not os.path.exists(path):
            raise RuntimeError(
                f"Fixture PDF not found: {path}. Save a real IDSP weekly PDF there, "
                "or use --source live to download the newest one."
            )
        report = parse.parse_pdf(path, self.config)
        report.source_pdf_url = "file://" + path.replace(os.sep, "/")
        report.listing_url = self.config.get("listing_url", "")
        report.notes.append(f"parsed from saved fixture: {os.path.basename(path)}")
        return report
