"""Layer 3 SEASON orchestrator: pull every IDSP weekly report across a monsoon
window, parse each, and write the week-on-week retrospective to
data/confirmed_season.json -- the dashboard's main Layer 3 view.

This exists because IDSP publishes with a heavy, irregular lag, so a single
"latest week" is noisy and "this week" framing is dishonest. A full past season
(2025 May-Oct by default) shows the real arc -- outbreaks rise through the
monsoon, peak, and fall -- and is the ground truth for the three-layer backtest.

Usage (from the project root):
    python src/build_layer3_season.py                 # uses config season block (2025 May-Oct)
    python src/build_layer3_season.py --insecure      # if a gov TLS cert lapses

PDFs are cached under config.season.cache_dir (gitignored), so the first run
downloads ~27 weekly PDFs and later runs are fast and offline. The build ABORTS
and writes nothing if fewer than season.min_weeks_parsed weeks come back clean
(same fail-loud philosophy as the other layers).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from idsp import season as season_mod  # noqa: E402

ROOT = os.path.dirname(SRC_DIR)
DISCLAIMER = (
    "Officially reported outbreaks from the IDSP weekly reports, shown for a full "
    "past monsoon season. This is real surveillance data, the authoritative ground "
    "truth in this dashboard, but it lags and it undercounts, because not every "
    "illness becomes a reported outbreak. We show a past season rather than this "
    "week on purpose: IDSP publishes with a long, uneven delay, so a season in "
    "review is honest where a live counter would not be. It confirms and validates "
    "what the other two layers hint at, in sequence after the weather and the "
    "searches. It does not predict, and it is not a complete case count."
)


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _skey(s: str) -> str:
    """Space/punctuation-insensitive state key (drops the joining 'and'/'&'), so
    cities.json's 'Jammu & Kashmir' maps to idsp.json's 'Jammu and Kashmir'."""
    toks = [t for t in re.split(r"[^a-z]+", (s or "").lower()) if t and t != "and"]
    return "".join(toks)


def build_cities(config_dir: str, cfg: dict) -> list[dict]:
    """Map Layer 1's city list to state ISO codes, so the dashboard can offer the
    same 'pick a city -> see its state' selector as Layer 2."""
    code_by_key = {_skey(s["name"]): s.get("code", "") for s in cfg.get("states", [])}
    path = os.path.join(config_dir, "cities.json")
    if not os.path.exists(path):
        return []
    out = []
    for c in load_json(path).get("cities", []):
        code = code_by_key.get(_skey(c.get("state", "")), "")
        if code:
            out.append({"name": c["name"], "state": c["state"], "code": code})
    return out


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build Layer 3 season retrospective confirmed_season.json")
    p.add_argument("--config-dir", default=os.path.join(ROOT, "config"))
    p.add_argument("--out", default=os.path.join(ROOT, "data", "confirmed_season.json"))
    p.add_argument("--insecure", action="store_true",
                   help="Disable TLS verification (sets IDSP_INSECURE) for a gov cert lapse.")
    return p.parse_args()


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    args = parse_args()
    if args.insecure:
        os.environ["IDSP_INSECURE"] = "1"
    cfg = load_json(os.path.join(args.config_dir, "idsp.json"))
    sc = cfg["season"]
    insecure = os.environ.get("IDSP_INSECURE", "").strip().lower() in ("1", "true", "yes", "on")

    print(f"Season retrospective: {sc['year']} ({sc['window_start']} to {sc['window_end']})  |  "
          f"diseases: {len(cfg['diseases'])}")
    print("-" * 78)

    try:
        data = season_mod.build_season(cfg, root=ROOT, insecure=insecure, log=print)
    except Exception as err:
        print(f"ABORT: could not build the season ({err}). Writing nothing.", file=sys.stderr)
        return 1

    print("-" * 78)

    # --- season-level data-quality guard --------------------------------------
    st = data["season_totals"]
    min_weeks = int(sc.get("min_weeks_parsed", 12))
    reasons = []
    if st["weeks_parsed"] < min_weeks:
        reasons.append(f"only {st['weeks_parsed']} week(s) parsed cleanly (need >= {min_weeks}); "
                       "discovery, downloads, or the PDF format may have broken")
    if st["all_outbreaks"] == 0:
        reasons.append("zero outbreaks parsed across the entire season")
    if reasons:
        print("ABORT: season data-quality guard failed. Writing nothing.", file=sys.stderr)
        for r in reasons:
            print(f"  - {r}", file=sys.stderr)
        return 1

    payload = {
        "layer": 3,
        "layer_name": "Confirmed outbreaks (IDSP weekly reports, season retrospective)",
        "view": "season",
        "model_version": cfg.get("model_version", "unknown"),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "live",
        "attribution": ("IDSP Weekly Outbreak Reports, Ministry of Health & Family Welfare "
                        "(idsp.mohfw.gov.in)"),
        "is_sample": False,
        "disclaimer": DISCLAIMER,
        "season_year": data["year"],
        "season_label": f"{data['year']} monsoon season",
        "window_start": data["window_start"],
        "window_end": data["window_end"],
        "start_month": data["start_month"],
        "end_month": data["end_month"],
        "listing_url": cfg.get("listing_url", ""),
        "official_home": cfg.get("official_home", ""),
        "diseases": [
            {"key": d["key"], "label": d["label"], "headline": bool(d.get("headline"))}
            for d in cfg["diseases"]
        ],
        "headline_disease": data["headline_disease"],
        "guard": {
            "status": "ok",
            "weeks_parsed": st["weeks_parsed"],
            "weeks_in_window": st["weeks_in_window"],
            "missing_weeks": len(data["missing_weeks"]),
        },
        "season_totals": st,
        "totals_by_disease": data["totals_by_disease"],
        "weeks": data["weeks"],
        "by_state": data["by_state"],
        "regions": data["regions"],
        "cities": build_cities(args.config_dir, cfg),
        "missing_weeks": data["missing_weeks"],
    }

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    # Minified (like fever_signal.json): this is the dashboard's largest data file,
    # and a compact body is friendlier to the single-threaded dev server's load
    # burst (it otherwise drops a concurrent request). The dashboard reads it fine.
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"), ensure_ascii=False)

    print_summary(payload)
    print(f"\nWrote {args.out}  ({st['weeks_parsed']} weeks, "
          f"{st['target_outbreaks']} tracked outbreaks across {st['states']} states, "
          f"{len(data['missing_weeks'])} week(s) missing)")
    return 0


def print_summary(p: dict) -> None:
    print(f"\n{p['season_label']}  |  weeks parsed: {p['season_totals']['weeks_parsed']}"
          f"/{p['season_totals']['weeks_in_window']}")
    print("\nSeason totals by disease (outbreaks / cases / deaths, peak week):")
    for d in p["diseases"]:
        t = p["totals_by_disease"][d["key"]]
        star = "  <- headline" if d["headline"] else ""
        pk = f"peak wk {t['peak_week']}" if t["peak_week"] else "no outbreaks"
        print(f"  {t['label']:<24} {t['outbreaks']:>3} outbreaks  {t['cases']:>6} cases  "
              f"{t['deaths']:>3} deaths   ({pk}){star}")
    hk = p["headline_disease"]
    print(f"\nWeek-by-week {hk} outbreaks (the seasonal curve):")
    for wd in p["weeks"]:
        n = wd["diseases"][hk]["outbreaks"]
        bar = "#" * n
        print(f"  wk {wd['week']:>2}  {wd.get('period_label', '') or '':<34} {n:>2} {bar}")
    if p["missing_weeks"]:
        miss = ", ".join(str(m["week"]) for m in p["missing_weeks"])
        print(f"\nMissing/!parsed weeks: {miss}")


if __name__ == "__main__":
    raise SystemExit(main())
