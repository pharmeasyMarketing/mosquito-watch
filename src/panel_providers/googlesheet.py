"""Google-Sheet Fever Panel provider (STUB -- not yet wired).

This is where the real weekly backend feed plugs in. The plan:
  1. The backend publishes the this_year Fever Panel numbers to a Google Sheet.
  2. In that sheet: File -> Share -> Publish to web -> CSV, and copy the link.
  3. Put that link in config/panel.json -> google_sheet.csv_url, and set
     config/panel.json -> source to "googlesheet" (or run with --provider googlesheet).
  4. Implement the CSV parse below (one row per week; columns named per
     google_sheet.columns), then return SeriesPoint lists.

last_year stays the committed historical reference (it does not change weekly),
so this provider only needs to supply the this_year series; for last_year it can
defer to the bundled reference. Until all of that exists, every method raises so
the build fails loud rather than publishing empty/garbage data.

Stdlib only when implemented (urllib.request + csv); no new dependency.
"""
from __future__ import annotations

from .base import PanelProvider, SeriesPoint  # noqa: F401  (SeriesPoint used once wired)


class GoogleSheetPanelProvider(PanelProvider):
    name = "googlesheet"
    attribution = "PharmEasy Diagnostics (weekly Fever Panel export)"
    is_sample = False

    def _not_ready(self):
        raise NotImplementedError(
            "The 'googlesheet' panel provider is not wired yet. Set "
            "config/panel.json -> google_sheet.csv_url to the published-to-web CSV, "
            "implement the CSV parse in src/panel_providers/googlesheet.py, then run "
            "with --provider googlesheet. Until then use --provider mock (the default)."
        )

    def tests_series(self, year, season):
        # TODO: fetch csv_url, parse rows, return [SeriesPoint(week=row.week,
        #       value=row[columns.tests_booked]) ...] for this_year; reference for last_year.
        self._not_ready()

    def positivity_series(self, disease, year, season):
        # TODO: column = columns.positivity_prefix + disease (e.g. "positivity_dengue").
        self._not_ready()
