"""Layer 3 orchestrator: pull the latest IDSP weekly outbreak report (Confirmed
Cases), aggregate the target diseases by state/district, and write
data/confirmed_cases.json plus a console summary you can eyeball.

Usage (from the project root):
    python src/build_layer3.py                    # sample/synthetic source (default; no deps, no network)
    python src/build_layer3.py --source fixture   # REAL parser on the saved weekly PDF (offline)
    python src/build_layer3.py --source live      # discover + download + parse the newest PDF (network)
    IDSP_SOURCE=live python src/build_layer3.py
    python src/build_layer3.py --source live --insecure   # if a gov TLS cert lapses

MANDATORY data-quality guard (the single most important Layer 3 requirement):
the script ABORTS and writes nothing if the parse looks broken -- too few
outbreak rows, no Unique-ID anchors, or no reporting week. Because we parse
government PDFs whose format drifts week to week, a format change must NEVER
silently feed bad data to a branded dashboard (same fail-loud philosophy as
Layers 1 and 2).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone

# Make src/ importable whether run as `python src/build_layer3.py` or `-m`.
SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import idsp  # noqa: E402

ROOT = os.path.dirname(SRC_DIR)
DISCLAIMER = (
    "Officially reported outbreaks from the IDSP weekly reports. This is real "
    "surveillance data, the authoritative ground truth in this dashboard, but it "
    "lags by a week or two and it undercounts, because not every illness becomes a "
    "reported outbreak. It confirms and validates what the other two layers hint "
    "at, in sequence after the weather and the searches. It does not predict, it is "
    "not a complete case count, and it is not medical advice. Always defer to your "
    "state health department and the official IDSP reports."
)


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build Layer 3 (Confirmed Cases) confirmed_cases.json")
    p.add_argument(
        "--source",
        default=os.environ.get("IDSP_SOURCE", idsp.DEFAULT_SOURCE),
        help=f"IDSP source. One of: {', '.join(idsp.available())} (default: %(default)s)",
    )
    p.add_argument("--config-dir", default=os.path.join(ROOT, "config"))
    p.add_argument("--out", default=os.path.join(ROOT, "data", "confirmed_cases.json"))
    p.add_argument("--insecure", action="store_true",
                   help="Disable TLS verification for the live source (sets IDSP_INSECURE).")
    return p.parse_args()


def _lag_days(period_end: str) -> int | None:
    """Whole days between the report's last covered day and today (UTC)."""
    try:
        end = datetime.strptime(period_end, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
    return (datetime.now(timezone.utc).date() - end).days


def aggregate(report, cfg: dict) -> dict:
    """Roll up the target outbreaks into totals-by-disease and by-state tables."""
    disease_meta = cfg["diseases"]
    target_keys = [d["key"] for d in disease_meta]
    code_by_name = {s["name"]: s.get("code", "") for s in cfg.get("states", [])}
    headline_key = next((d["key"] for d in disease_meta if d.get("headline")), target_keys[0])

    targets = [o for o in report.outbreaks if o.disease_key in target_keys]

    totals_by_disease = {}
    for d in disease_meta:
        rows = [o for o in targets if o.disease_key == d["key"]]
        totals_by_disease[d["key"]] = {
            "label": d["label"],
            "outbreaks": len(rows),
            "cases": sum(o.cases or 0 for o in rows),
            "deaths": sum(o.deaths or 0 for o in rows),
            "states": sorted({o.state for o in rows}),
        }

    state_map: dict[str, dict] = {}
    for o in targets:
        e = state_map.setdefault(o.state, {
            "state": o.state, "code": code_by_name.get(o.state, ""),
            "diseases": {}, "outbreaks": 0, "cases": 0, "deaths": 0, "_districts": set(),
        })
        de = e["diseases"].setdefault(o.disease_key, {"outbreaks": 0, "cases": 0, "deaths": 0})
        de["outbreaks"] += 1
        de["cases"] += o.cases or 0
        de["deaths"] += o.deaths or 0
        e["outbreaks"] += 1
        e["cases"] += o.cases or 0
        e["deaths"] += o.deaths or 0
        if o.district:
            e["_districts"].add(o.district)
    by_state = []
    for e in state_map.values():
        e["district_count"] = len(e.pop("_districts"))
        e["headline"] = e["diseases"].get(headline_key, {}).get("cases", 0)
        by_state.append(e)
    # Default order: most reported cases (across tracked diseases) first, with the
    # headline disease as the tiebreaker. The dashboard table is re-sortable.
    by_state.sort(key=lambda x: (x["cases"], x["headline"]), reverse=True)

    outbreaks = [{
        "disease_key": o.disease_key, "disease": o.disease, "state": o.state,
        "district": o.district, "cases": o.cases, "deaths": o.deaths,
        "status": o.status, "outbreak_id": o.outbreak_id, "week": o.week,
    } for o in targets]
    outbreaks.sort(key=lambda r: (r["cases"] or 0), reverse=True)

    return {
        "headline_disease": headline_key,
        "target_outbreak_count": len(targets),
        "total_outbreak_count": len(report.outbreaks),
        "totals_by_disease": totals_by_disease,
        "by_state": by_state,
        "outbreaks": outbreaks,
    }


def guard(report, cfg: dict, target_count: int) -> list[str]:
    """Return a list of abort reasons (empty == passed). Fail loud, never silent."""
    san = cfg.get("sanity", {})
    reasons = []
    n = len(report.outbreaks)
    if n < san.get("min_outbreaks", 5):
        reasons.append(f"only {n} outbreak row(s) parsed (need >= {san.get('min_outbreaks', 5)}); "
                       "the PDF format may have changed or the download is wrong")
    if report.id_anchor_count < san.get("min_id_anchors", 5):
        reasons.append(f"only {report.id_anchor_count} Unique-ID anchor(s) found "
                       f"(need >= {san.get('min_id_anchors', 5)}); the table structure was not recognized")
    if san.get("require_report_week", True) and report.report_week is None:
        reasons.append("could not determine the reporting week from the PDF")
    if target_count < san.get("min_target_outbreaks", 0):
        reasons.append(f"only {target_count} target-disease outbreak(s) "
                       f"(need >= {san.get('min_target_outbreaks', 0)})")
    return reasons


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    args = parse_args()
    if args.insecure:
        os.environ["IDSP_INSECURE"] = "1"
    cfg = load_json(os.path.join(args.config_dir, "idsp.json"))
    source = idsp.get_source(args.source, cfg)

    print(f"Source: {source.name}  |  diseases: {len(cfg['diseases'])}  |  "
          f"sample={source.is_sample} live={source.is_live}")
    if source.is_sample:
        print("NOTE: this is the SAMPLE source -- output is synthetic, not a real IDSP report.")
    print("-" * 78)

    # --- fetch + parse (a hard failure here aborts; we write nothing) ----------
    try:
        report = source.fetch_report()
    except Exception as err:
        print(f"ABORT: could not fetch/parse the report ({err}). Writing nothing.", file=sys.stderr)
        return 1

    agg = aggregate(report, cfg)
    target_count = agg["target_outbreak_count"]

    # --- MANDATORY data-quality guard -----------------------------------------
    reasons = guard(report, cfg, target_count)
    if reasons:
        print("ABORT: data-quality guard failed. Writing nothing.", file=sys.stderr)
        for r in reasons:
            print(f"  - {r}", file=sys.stderr)
        return 1

    lag = _lag_days(report.period_end)
    payload = {
        "layer": 3,
        "layer_name": "Confirmed Cases (IDSP weekly outbreaks)",
        "model_version": cfg.get("model_version", "unknown"),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": source.name,
        "attribution": source.attribution,
        "is_sample": bool(source.is_sample),
        "is_live": bool(source.is_live),
        "disclaimer": DISCLAIMER,
        "report_week": report.report_week,
        "report_year": report.report_year,
        "week_label": report.week_label,
        "period_label": report.period_label,
        "period_start": report.period_start,
        "period_end": report.period_end,
        "report_lag_days": lag,
        "source_pdf_url": report.source_pdf_url,
        "listing_url": report.listing_url or cfg.get("listing_url", ""),
        "official_home": cfg.get("official_home", ""),
        "diseases": [
            {"key": d["key"], "label": d["label"], "headline": bool(d.get("headline"))}
            for d in cfg["diseases"]
        ],
        "headline_disease": agg["headline_disease"],
        "guard": {
            "status": "ok",
            "total_outbreaks": agg["total_outbreak_count"],
            "id_anchors": report.id_anchor_count,
            "target_outbreaks": target_count,
        },
        "target_outbreak_count": target_count,
        "total_outbreak_count": agg["total_outbreak_count"],
        "state_count": len(agg["by_state"]),
        "totals_by_disease": agg["totals_by_disease"],
        "by_state": agg["by_state"],
        "outbreaks": agg["outbreaks"],
        "notes": report.notes,
        "page_count": report.page_count,
    }

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)

    print_summary(payload)
    sample_note = ", SAMPLE data" if source.is_sample else ""
    print(f"\nWrote {args.out}  ({target_count} target outbreaks across "
          f"{len(agg['by_state'])} states, {agg['total_outbreak_count']} total reported, "
          f"source={source.name}{sample_note})")
    return 0


def print_summary(p: dict) -> None:
    lag = p.get("report_lag_days")
    lag_txt = f"  (about {lag} days ago)" if isinstance(lag, int) else ""
    print(f"\nReport: {p['week_label'] or '(week n/a)'}  |  {p['period_label'] or 'period n/a'}{lag_txt}")
    print(f"Reported outbreaks in this report: {p['total_outbreak_count']} total, "
          f"{p['target_outbreak_count']} in the diseases we track.")
    print("\nBy disease (cases / deaths / outbreaks):")
    for d in p["diseases"]:
        t = p["totals_by_disease"][d["key"]]
        star = "  <- headline" if d["headline"] else ""
        print(f"  {t['label']:<24} {t['cases']:>6} cases  {t['deaths']:>3} deaths  "
              f"{t['outbreaks']:>2} outbreaks{star}")
    print("\nTop states by reported cases (tracked diseases):")
    for e in p["by_state"][:8]:
        print(f"  {e['state']:<26} {e['cases']:>6} cases  {e['deaths']:>3} deaths  "
              f"across {e['outbreaks']} outbreak(s) in {e['district_count']} district(s)")


if __name__ == "__main__":
    raise SystemExit(main())
