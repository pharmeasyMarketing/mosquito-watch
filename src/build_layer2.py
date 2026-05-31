"""Layer 2 orchestrator (year-over-year): build a 2025-vs-2026 monsoon-season
comparison of search attention, nationally and per state (mapped to Layer 1's
cities), then write data/fever_signal.json.

ONE span query per (geo, group) returns BOTH seasons on a single comparable
Google-Trends normalization; we then slice them into two seasons aligned by
week-of-season. So a full build is:
    national (4 groups) + per-state (city-states x 4 groups)  span queries.

Usage (from the project root):
    python src/build_layer2.py                       # mock/sample (default; no deps, no key, free)
    python src/build_layer2.py --provider serpapi
    python src/build_layer2.py --provider serpapi --states-limit 2   # cheap real test

Data-quality guard: the build ABORTS and writes nothing if no national series is
produced, if more than sanity.max_fail_fraction of national groups fail, or if
the provider returns all-zero / flat data.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timezone

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import trends_providers  # noqa: E402

ROOT = os.path.dirname(SRC_DIR)
DISCLAIMER = (
    "Search attention only. This shows how often people look up fever and symptom "
    "terms, not how many people are ill and not confirmed cases. Values are "
    "relative and normalized from 0 to 100, not absolute counts. A single news "
    "story can lift searches everywhere at once. Weather temperature is not the "
    "same thing as a body-temperature fever. Read this alongside official "
    "surveillance, never as a diagnosis."
)


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build Layer 2 (Fever Signal) year-over-year fever_signal.json")
    p.add_argument(
        "--provider",
        default=os.environ.get("TRENDS_PROVIDER", trends_providers.DEFAULT_PROVIDER),
        help=f"Trends provider. One of: {', '.join(trends_providers.available())} (default: %(default)s)",
    )
    p.add_argument("--config-dir", default=os.path.join(ROOT, "config"))
    p.add_argument("--out", default=os.path.join(ROOT, "data", "fever_signal.json"))
    p.add_argument("--states-limit", type=int, default=0,
                   help="Cap how many city-states get per-state series (0 = all). Use a small N for a cheap real test.")
    p.add_argument("--sleep", type=float, default=0.0, help="Polite delay between provider calls (s)")
    return p.parse_args()


def _norm(name: str) -> str:
    s = str(name).strip().lower()
    for a, b in (("&", "and"), ("nct of ", ""), (".", ""), ("  ", " ")):
        s = s.replace(a, b)
    return s


def season_slice(points: list, year: int, start_month: int, end_month: int) -> list:
    """Weekly points within [start_month/1 .. end_month/31] of `year` as compact
    [week, value] pairs (week 0 = first week of the start month) so the two years
    overlay on a shared x-axis. Compact pairs keep the committed file small enough
    to fetch reliably during the dashboard's initial load burst."""
    anchor = date(year, start_month, 1)
    out = []
    for p in points:
        try:
            d = date.fromisoformat(p.date)
        except (ValueError, TypeError):
            continue
        if d.year == year and start_month <= d.month <= end_month:
            out.append([(d - anchor).days // 7, round(p.value)])
    out.sort(key=lambda r: r[0])
    return out


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    args = parse_args()
    cfg = load_json(os.path.join(args.config_dir, "trends.json"))
    groups = cfg["groups"]
    states = cfg["states"]
    geo = cfg.get("geo", "IN")
    san = cfg.get("sanity", {})
    season = cfg.get("season", {})
    this_year = int(season.get("this_year", 2026))
    last_year = int(season.get("last_year", 2025))
    sm = int(season.get("start_month", 5))
    em = int(season.get("end_month", 10))
    years = [last_year, this_year]
    span = f"{last_year}-{sm:02d}-01 {this_year}-{em:02d}-31"

    cities_path = os.path.join(args.config_dir, "cities.json")
    cities = load_json(cities_path)["cities"] if os.path.exists(cities_path) else []

    provider = trends_providers.get_provider(args.provider)

    # Distinct states the Layer 1 cities sit in (these get per-state series).
    state_by_norm = {_norm(s["name"]): s for s in states}
    city_states, seen = [], set()
    for c in cities:
        s = state_by_norm.get(_norm(c["state"]))
        code = s["code"] if s else ""
        key = code or _norm(c["state"])
        if key not in seen:
            seen.add(key)
            city_states.append({"name": c["state"], "code": code})
    target_states = city_states[:args.states_limit] if args.states_limit else city_states

    headline_key = next((g["key"] for g in groups if g.get("headline")), groups[0]["key"])

    print(f"Provider: {provider.name}  |  Groups: {len(groups)}  |  Span: {span}  |  "
          f"Per-state series: {len(target_states)} of {len(city_states)} city-states")
    if provider.is_sample:
        print("NOTE: this is the SAMPLE provider -- output is synthetic, not real Google Trends.")
    est = len(groups) * (1 + len(target_states))
    print(f"Estimated provider calls this build: {est}")
    print("-" * 78)

    failures: list[dict] = []
    all_values: list[float] = []

    def seasons_for(points):
        return {str(y): season_slice(points, y, sm, em) for y in years}

    # --- national year-over-year ----------------------------------------------
    national_yoy: dict = {}
    for g in groups:
        label = g.get("label", g["key"])
        try:
            pts = provider.interest_over_time(g["terms"], geo=geo, date=span)
            seasons = seasons_for(pts)
            if not seasons[str(last_year)] and not seasons[str(this_year)]:
                raise RuntimeError("no season data in span")
            all_values.extend(p.value for p in pts)
            national_yoy[g["key"]] = {
                "label": label, "disease": g.get("disease", label),
                "headline": bool(g.get("headline")), "seasons": seasons,
            }
            cur = seasons[str(this_year)]
            ref = seasons[str(last_year)]
            cur_v = cur[-1][1] if cur else None
            print(f"  [nat ] {label:<14} {this_year} latest={cur_v if cur_v is not None else '-':>5}  "
                  f"({len(ref)} wk {last_year} ref, {len(cur)} wk {this_year})")
        except Exception as err:
            failures.append({"group": g["key"], "stage": "national", "reason": str(err)})
            print(f"  [nat ] {label:<14} FAIL ({err})")
        if args.sleep:
            time.sleep(args.sleep)

    # --- per-state year-over-year ---------------------------------------------
    state_yoy: dict = {}
    for st in target_states:
        if not st["code"]:
            failures.append({"group": "*", "stage": "state", "state": st["name"], "reason": "no geo code in config"})
            continue
        entry = {"name": st["name"], "code": st["code"], "groups": {}}
        ok_groups = 0
        for g in groups:
            try:
                pts = provider.interest_over_time(g["terms"], geo=st["code"], date=span)
                seasons = seasons_for(pts)
                if not seasons[str(last_year)] and not seasons[str(this_year)]:
                    raise RuntimeError("no season data")
                all_values.extend(p.value for p in pts)
                entry["groups"][g["key"]] = {"seasons": seasons}
                ok_groups += 1
            except Exception as err:
                failures.append({"group": g["key"], "stage": "state", "state": st["name"], "reason": str(err)})
            if args.sleep:
                time.sleep(args.sleep)
        if entry["groups"]:
            state_yoy[st["code"]] = entry
        print(f"  [geo ] {st['name']:<26} {st['code']:<7} {ok_groups}/{len(groups)} groups")

    print("-" * 78)

    # --- data-quality guard ----------------------------------------------------
    group_fail = len({f["group"] for f in failures if f["stage"] == "national"})
    fail_fraction = group_fail / len(groups) if groups else 1.0
    nonzero_fraction = (sum(1 for v in all_values if v) / len(all_values)) if all_values else 0.0

    if not national_yoy:
        print("ABORT: no national year-over-year series produced. Writing nothing.", file=sys.stderr)
        return 1
    if fail_fraction > san.get("max_fail_fraction", 0.5):
        print(f"ABORT: {group_fail}/{len(groups)} national groups failed "
              f"({fail_fraction:.0%} > {san.get('max_fail_fraction', 0.5):.0%}). Writing nothing.", file=sys.stderr)
        return 1
    if nonzero_fraction < san.get("min_nonzero_fraction", 0.05):
        print(f"ABORT: data looks empty/flat ({nonzero_fraction:.0%} non-zero). Writing nothing.", file=sys.stderr)
        return 1

    cities_map = []
    for c in cities:
        s = state_by_norm.get(_norm(c["state"]))
        cities_map.append({
            "name": c["name"], "state": c["state"],
            "code": s["code"] if s else "",
            "lat": c.get("lat"), "lon": c.get("lon"),
        })

    payload = {
        "layer": 2,
        "layer_name": "Fever Signal (search attention)",
        "model_version": cfg.get("model_version", "unknown"),
        "view": "year_over_year",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provider": provider.name,
        "attribution": provider.attribution,
        "is_sample": bool(provider.is_sample),
        "disclaimer": DISCLAIMER,
        "geo": geo,
        "span": span,
        "season": {"this_year": this_year, "last_year": last_year, "start_month": sm, "end_month": em},
        "headline_group": headline_key,
        "groups": [
            {"key": g["key"], "label": g.get("label", g["key"]), "disease": g.get("disease"),
             "terms": g["terms"], "headline": bool(g.get("headline"))}
            for g in groups
        ],
        "group_count": len(national_yoy),
        "state_count": len(state_yoy),
        "city_count": len(cities_map),
        "failed_count": len(failures),
        "failures": failures,
        "national_yoy": national_yoy,
        "state_yoy": state_yoy,
        "cities": cities_map,
    }

    if hasattr(provider, "meta"):
        try:
            payload["provider_meta"] = provider.meta()
        except Exception:
            pass

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        # Minified (no indent): the year-over-year arrays are large, and this file
        # is machine-read by the dashboard. Compact keeps it small enough to fetch
        # reliably during the page's initial load burst.
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))

    print_summary(national_yoy, state_yoy, this_year, last_year)
    if failures:
        print(f"\nNote: {len(failures)} provider call(s) failed but stayed under the abort threshold.")

    pm = payload.get("provider_meta") or {}
    if pm.get("cost_usd_total") is not None:
        print(f"\nApify cost this build: ${pm['cost_usd_total']:.4f} across {len(pm.get('tokens_used') or [])} token(s).")
    if pm.get("searches_total") is not None:
        print(f"\nSerpApi searches this build: {pm['searches_total']} across {len(pm.get('keys_used') or [])} key(s).")
        for k, v in (pm.get("searches_by_key") or {}).items():
            print(f"   {k}: {v} searches")
    for sw in pm.get("switches", []):
        print(f"   key/token switch: {sw.get('reason')}")

    sample_note = ", SAMPLE data" if provider.is_sample else ""
    print(f"\nWrote {args.out}  ({len(state_yoy)} states, {len(cities_map)} cities, "
          f"{len(national_yoy)} groups, {last_year} vs {this_year}, provider={provider.name}{sample_note})")
    return 0


def print_summary(national_yoy: dict, state_yoy: dict, this_year: int, last_year: int) -> None:
    print(f"\nYear-over-year season ({last_year} reference vs {this_year} so far):")
    for key, n in national_yoy.items():
        ref = n["seasons"][str(last_year)]
        cur = n["seasons"][str(this_year)]
        ref_peak = max((r[1] for r in ref), default=0)
        cur_latest = cur[-1][1] if cur else 0
        star = "  <- headline" if n["headline"] else ""
        print(f"  {n['label']:<14} {last_year} peak {ref_peak:>5}   {this_year} latest {cur_latest:>5}{star}")
    print(f"\nPer-state series built for {len(state_yoy)} states.")


if __name__ == "__main__":
    raise SystemExit(main())
