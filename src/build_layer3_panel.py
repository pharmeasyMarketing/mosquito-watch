"""Layer 3 v1 orchestrator (Fever Panel): build the year-over-year Fever Panel
signal -- tests booked (demand) and positivity by disease (confirmation) -- and
write data/panel_signal.json, the dashboard's new Layer 3 view.

This REPLACES the old IDSP 'Confirmed Cases' layer (build_layer3.py /
build_layer3_season.py), which stays in the repo, commented-out and switchable.

Usage (from the project root):
    python src/build_layer3_panel.py                       # mock/sample source (default; no deps, no network)
    python src/build_layer3_panel.py --provider googlesheet  # real weekly backend feed (stub, not yet wired)
    PANEL_SOURCE=mock python src/build_layer3_panel.py

The current default is the MOCK provider: deterministic, clearly-synthetic data
(is_sample=true, status=coming_soon) so the layer can ship as a labelled preview
until the weekly backend feed is connected.

MANDATORY data-quality guard (same fail-loud philosophy as Layers 1 and 2): the
script ABORTS and writes nothing if the tests series is missing, a tracked
disease has no positivity series, or a series is too short.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import panel_providers  # noqa: E402

ROOT = os.path.dirname(SRC_DIR)
DISCLAIMER = (
    "A preview built on sample data. When it goes live this layer draws on "
    "PharmEasy's own Fever Panel lab diagnostics: how many fever tests people "
    "book (a demand signal) and how often they come back positive for each "
    "disease (a confirmation signal), this monsoon season against last. It is a "
    "lab-testing signal, not a count of all cases and not medical advice. It "
    "stands on its own and is not added to the breeding-weather score or the "
    "search signal above."
)
MONTHS = ["", "January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build Layer 3 v1 (Fever Panel) panel_signal.json")
    p.add_argument("--provider", default=None,
                   help=f"Panel source. One of: {', '.join(panel_providers.available())} "
                        "(default: config.source, then mock)")
    p.add_argument("--config-dir", default=os.path.join(ROOT, "config"))
    p.add_argument("--out", default=os.path.join(ROOT, "data", "panel_signal.json"))
    return p.parse_args()


def _pairs(points) -> list[list]:
    """SeriesPoint list -> [[week, value]] (int weeks; ints for whole values)."""
    out = []
    for p in points:
        v = p.value
        v = int(round(v)) if float(v).is_integer() else round(v, 1)
        out.append([p.week, v])
    return out


def _peak(pairs) -> dict:
    """Highest point of a [[week, value]] series, as {value, week}."""
    if not pairs:
        return {"value": 0, "week": None}
    w, v = max(pairs, key=lambda p: p[1])
    return {"value": v, "week": w}


def _peak_month(week: int | None, start_month: int) -> str:
    if week is None:
        return ""
    m = start_month + int(week // 4.345)
    return MONTHS[m] if 1 <= m <= 12 else ""


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    args = parse_args()
    cfg = load_json(os.path.join(args.config_dir, "panel.json"))
    season = cfg["season"]
    ly, ty = int(season["last_year"]), int(season["this_year"])
    start_month = int(season.get("start_month", 5))

    source = args.provider or os.environ.get("PANEL_SOURCE") or cfg.get("source") or panel_providers.DEFAULT_PROVIDER
    provider = panel_providers.get_provider(source)

    print(f"Source: {provider.name}  |  metrics: {len(cfg['metrics'])}  |  "
          f"diseases: {len(cfg['diseases'])}  |  sample={provider.is_sample}")
    if provider.is_sample:
        print("NOTE: this is SAMPLE data -- synthetic, clearly badged 'coming soon' in the dashboard.")
    print("-" * 78)

    # --- fetch series (a hard failure here aborts; we write nothing) -----------
    try:
        tests_seasons = {str(ly): _pairs(provider.tests_series(ly, season)),
                         str(ty): _pairs(provider.tests_series(ty, season))}
        positivity_by_disease = {}
        for d in cfg["diseases"]:
            positivity_by_disease[d["key"]] = {
                "label": d["label"],
                "seasons": {str(ly): _pairs(provider.positivity_series(d["key"], ly, season)),
                            str(ty): _pairs(provider.positivity_series(d["key"], ty, season))},
            }
    except Exception as err:
        print(f"ABORT: could not build the Fever Panel series ({err}). Writing nothing.", file=sys.stderr)
        return 1

    # --- MANDATORY data-quality guard -----------------------------------------
    min_pts = int(cfg.get("sanity", {}).get("min_points_per_series", 4))
    reasons = []
    if len(tests_seasons[str(ly)]) < min_pts:
        reasons.append(f"tests reference series has < {min_pts} points")
    for key, node in positivity_by_disease.items():
        if len(node["seasons"][str(ly)]) < min_pts:
            reasons.append(f"positivity[{key}] reference series has < {min_pts} points")
    if reasons:
        print("ABORT: data-quality guard failed. Writing nothing.", file=sys.stderr)
        for r in reasons:
            print(f"  - {r}", file=sys.stderr)
        return 1

    headline_metric = next((m["key"] for m in cfg["metrics"] if m.get("headline")), cfg["metrics"][0]["key"])
    headline_disease = next((d["key"] for d in cfg["diseases"] if d.get("headline")), cfg["diseases"][0]["key"])
    tests_meta = next((m for m in cfg["metrics"] if m["key"] == "tests"), {})
    pos_meta = next((m for m in cfg["metrics"] if m["key"] == "positivity"), {})

    # --- summary (drives the cards) -------------------------------------------
    tests_ref = tests_seasons[str(ly)]
    tests_peak = _peak(tests_ref)
    summary = {
        "tests": {
            "last_total": sum(v for _, v in tests_ref),
            "last_peak_value": tests_peak["value"],
            "last_peak_week": tests_peak["week"],
            "last_peak_month": _peak_month(tests_peak["week"], start_month),
            "this_count": len(tests_seasons[str(ty)]),
        },
        "positivity": {},
    }
    for key, node in positivity_by_disease.items():
        pk = _peak(node["seasons"][str(ly)])
        summary["positivity"][key] = {
            "last_peak_value": pk["value"],
            "last_peak_week": pk["week"],
            "last_peak_month": _peak_month(pk["week"], start_month),
        }

    payload = {
        "layer": 3,
        "layer_name": "Fever Panel (PharmEasy lab diagnostics)",
        "view": "panel",
        "model_version": cfg.get("model_version", "unknown"),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": provider.name,
        "provider": provider.name,
        "attribution": provider.attribution,
        "is_sample": bool(provider.is_sample),
        "status": "coming_soon",
        "disclaimer": DISCLAIMER,
        "season": {"this_year": ty, "last_year": ly,
                   "start_month": start_month, "end_month": int(season.get("end_month", 10))},
        "season_label": f"monsoon season ({MONTHS[start_month]} to {MONTHS[int(season.get('end_month', 10))]})",
        "metrics": [
            {"key": m["key"], "label": m["label"], "unit": m.get("unit", ""),
             "kind": m.get("kind", "count"), "headline": bool(m.get("headline")),
             "blurb": m.get("blurb", "")}
            for m in cfg["metrics"]
        ],
        "headline_metric": headline_metric,
        "diseases": [
            {"key": d["key"], "label": d["label"], "headline": bool(d.get("headline"))}
            for d in cfg["diseases"]
        ],
        "headline_disease": headline_disease,
        "tests": {"label": tests_meta.get("label", "Tests booked"),
                  "unit": tests_meta.get("unit", "tests"),
                  "kind": tests_meta.get("kind", "count"),
                  "seasons": tests_seasons},
        "positivity": {"unit": pos_meta.get("unit", "%"),
                       "kind": pos_meta.get("kind", "percent"),
                       "by_disease": positivity_by_disease},
        "summary": summary,
        "guard": {"status": "ok", "min_points_per_series": min_pts},
    }

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)

    print_summary(payload)
    sample_note = ", SAMPLE data" if provider.is_sample else ""
    print(f"\nWrote {args.out}  (tests + positivity for {len(cfg['diseases'])} diseases, "
          f"{ly} vs {ty}, source={provider.name}{sample_note})")
    return 0


def print_summary(p: dict) -> None:
    s = p["summary"]
    ly = p["season"]["last_year"]
    print(f"\n{p['season_label']}  |  {ly} reference vs {p['season']['this_year']} so far "
          f"({s['tests']['this_count']} weeks in)")
    t = s["tests"]
    print(f"\nTests booked ({ly}): {t['last_total']:,} over the season, "
          f"peak {t['last_peak_value']:,}/week around {t['last_peak_month'] or 'n/a'}.")
    print(f"\nPositivity peaks ({ly}):")
    for d in p["diseases"]:
        ps = s["positivity"][d["key"]]
        print(f"  {d['label']:<14} {ps['last_peak_value']:>5}%  around {ps['last_peak_month'] or 'n/a'}")


if __name__ == "__main__":
    raise SystemExit(main())
