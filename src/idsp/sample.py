"""Sample / synthetic IDSP source (DEFAULT for development).

Generates DETERMINISTIC, clearly-synthetic confirmed-outbreak rows so the Layer 3
pipeline and dashboard can be built and demoed with ZERO dependencies and no
network -- the exact analogue of Layer 2's mock Trends provider. The numbers are
NOT real: is_sample=True flows all the way into confirmed_cases.json and the
dashboard badges the section as sample data so nobody mistakes it for a live
IDSP feed.

Determinism: every count is derived from a SHA-256 hash of a seed string, so
re-runs produce identical numbers (no churn in the committed data file). The
report is pinned to a fixed past monsoon week (peak dengue season) to make the
"confirmed cases light up after the rains" story render sensibly in the demo.

Real reported data comes from the `fixture` (saved PDF, offline) and `live`
(freshly downloaded newest PDF) sources -- see fetch.py / live.py.
"""
from __future__ import annotations

import hashlib

from .base import IdspSource, Outbreak, WeeklyReport

# Fixed sample week: 38th week of 2024 = mid-September, peak monsoon/dengue season.
_WEEK = 38
_YEAR = 2024
_WEEK_LABEL = "38th Week, 2024"
_PERIOD_LABEL = "16th September 2024 to 22nd September 2024"
_PERIOD_START = "2024-09-16"
_PERIOD_END = "2024-09-22"

# (state, district, IDSP-prefix, district-code) seeds. Real places, synthetic
# counts. Spread across the country so the map/table look representative.
_PLACES = [
    ("Maharashtra", "Pune", "MH", "PUN"), ("Maharashtra", "Mumbai", "MH", "MUM"),
    ("Kerala", "Ernakulam", "KL", "ERN"), ("Kerala", "Kozhikode", "KL", "KOZ"),
    ("Tamil Nadu", "Chennai", "TN", "CHE"), ("Tamil Nadu", "Coimbatore", "TN", "COI"),
    ("West Bengal", "Kolkata", "WB", "KOL"), ("West Bengal", "Howrah", "WB", "HOW"),
    ("Delhi", "South Delhi", "DL", "SDL"), ("Karnataka", "Bengaluru Urban", "KN", "BEN"),
    ("Rajasthan", "Jaipur", "RJ", "JAI"), ("Uttar Pradesh", "Lucknow", "UP", "LKO"),
    ("Gujarat", "Surat", "GJ", "SUR"), ("Madhya Pradesh", "Bhopal", "MP", "BHO"),
    ("Odisha", "Khordha", "OR", "KHO"), ("Punjab", "Ludhiana", "PB", "LDH"),
    ("Bihar", "Patna", "BH", "PAT"), ("Telangana", "Hyderabad", "TL", "HYD"),
    ("Assam", "Kamrup Metropolitan", "AS", "KAM"), ("Jharkhand", "Ranchi", "JH", "RAN"),
    ("Chhattisgarh", "Raipur", "CT", "RAI"), ("Haryana", "Gurugram", "HR", "GUR"),
]

# Disease mix, weighted toward dengue (the monsoon headline), then the other
# targets, plus a couple of non-target "other" rows so the all-disease total is
# a realistic denominator. (key, label, weight, deadly?)
_DISEASE_MIX = [
    ("dengue", "Dengue", 5, True),
    ("chikungunya", "Chikungunya", 2, False),
    ("malaria", "Malaria", 2, True),
    ("fever_rash", "Fever with Rash", 2, False),
    ("afi", "Acute Febrile Illness", 1, True),
    ("other", "Acute Diarrhoeal Disease", 2, True),
    ("other", "Cholera", 1, True),
]


def _h(*parts) -> int:
    seed = "|".join(str(p) for p in parts)
    return int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16)


def _pick_disease(seed: int):
    bag = []
    for key, label, weight, deadly in _DISEASE_MIX:
        bag.extend([(key, label, deadly)] * weight)
    return bag[seed % len(bag)]


class SampleIdspSource(IdspSource):
    name = "sample"
    attribution = "SAMPLE synthetic outbreak data for development -- not real IDSP reports"
    is_sample = True
    is_live = False

    def __init__(self, config: dict | None = None):
        # Accepted for a uniform get_source(name, config) constructor; the sample
        # source is self-contained and ignores it.
        self.config = config or {}

    def fetch_report(self) -> WeeklyReport:
        outbreaks: list[Outbreak] = []
        n = 0
        for state, district, prefix, dcode in _PLACES:
            # 1-2 outbreaks per place, deterministically.
            count = 1 + (_h("count", state, district) % 2)
            for j in range(count):
                key, label, deadly = _pick_disease(_h("disease", state, district, j))
                cases = 5 + _h("cases", state, district, j) % 180
                deaths = (_h("deaths", state, district, j) % 4) if deadly and cases > 40 else 0
                n += 1
                oid = f"{prefix}/{dcode}/{_YEAR}/{_WEEK}/{500 + n}"
                outbreaks.append(Outbreak(
                    disease_key=key, disease=label, state=state, district=district,
                    cases=cases, deaths=deaths, status="Under Surveillance",
                    outbreak_id=oid, week=_WEEK, year=_YEAR,
                    raw_disease=label, raw_state=state,
                ))
        return WeeklyReport(
            outbreaks=outbreaks, report_week=_WEEK, report_year=_YEAR,
            week_label=_WEEK_LABEL, period_label=_PERIOD_LABEL,
            period_start=_PERIOD_START, period_end=_PERIOD_END,
            source_pdf_url="", listing_url="", page_count=0,
            notes=["synthetic sample data -- not a real IDSP weekly report"],
        )
