"""Layer 2 orchestrator: pull search-attention (Fever Signal) per disease group --
nationally over time and split by state -- then write data/fever_signal.json plus
a console summary you can eyeball against intuition.

Usage (from the project root):
    python src/build_layer2.py                    # mock/sample provider (default; no deps, no key)
    python src/build_layer2.py --provider pytrends
    python src/build_layer2.py --provider serpapi      # needs SERPAPI_KEY
    TRENDS_PROVIDER=pytrends python src/build_layer2.py

Data-quality guard: the script ABORTS and writes nothing if no group produces a
national series, if more than sanity.max_fail_fraction of groups fail nationally,
or if the provider returns all-zero / flat data -- a branded dashboard must never
silently publish garbage (same fail-loud philosophy as Layer 1).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

# Make src/ importable whether run as `python src/build_layer2.py` or `-m`.
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
    p = argparse.ArgumentParser(description="Build Layer 2 (Fever Signal) fever_signal.json")
    p.add_argument(
        "--provider",
        default=os.environ.get("TRENDS_PROVIDER", trends_providers.DEFAULT_PROVIDER),
        help=f"Trends provider. One of: {', '.join(trends_providers.available())} (default: %(default)s)",
    )
    p.add_argument("--config-dir", default=os.path.join(ROOT, "config"))
    p.add_argument("--out", default=os.path.join(ROOT, "data", "fever_signal.json"))
    p.add_argument("--weeks", type=int, default=None, help="Weeks of history (default: config lookback_weeks)")
    p.add_argument("--sleep", type=float, default=0.0, help="Polite delay between provider calls (s)")
    return p.parse_args()


def _norm(name: str) -> str:
    """Loose key for matching provider region names to config state names."""
    s = str(name).strip().lower()
    for a, b in (("&", "and"), ("nct of ", ""), (".", ""), ("  ", " ")):
        s = s.replace(a, b)
    return s


def main() -> int:
    # Windows consoles often default to cp1252; force UTF-8 so the summary's
    # arrows and any non-ASCII state names render correctly.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    args = parse_args()
    cfg = load_json(os.path.join(args.config_dir, "trends.json"))
    groups = cfg["groups"]
    states = cfg["states"]
    # Reuse Layer 1's city list so both layers show the SAME cities. Google Trends
    # has no reliable city-level data for India, so Layer 2 attributes each city
    # its state's signal (a city VIEW over state-resolution data; the UI says so).
    cities_path = os.path.join(args.config_dir, "cities.json")
    cities = load_json(cities_path)["cities"] if os.path.exists(cities_path) else []
    geo = cfg.get("geo", "IN")
    weeks = args.weeks or cfg.get("lookback_weeks", 12)
    san = cfg.get("sanity", {})
    provider = trends_providers.get_provider(args.provider)

    print(f"Provider: {provider.name}  |  Groups: {len(groups)}  |  States: {len(states)}  |  weeks={weeks}")
    if provider.is_sample:
        print("NOTE: this is the SAMPLE provider -- output is synthetic, not real Google Trends.")
    print("-" * 78)

    national: list[dict] = []
    failures: list[dict] = []
    warnings: list[str] = []
    all_values: list[float] = []

    # --- national interest over time, per group --------------------------------
    for g in groups:
        label = g.get("label", g["key"])
        try:
            pts = provider.interest_over_time(g["terms"], geo=geo, weeks=weeks)
            if len(pts) < san.get("min_points_per_series", 4):
                raise RuntimeError(f"only {len(pts)} point(s) returned")
            vals = [p.value for p in pts]
            all_values.extend(vals)
            latest = vals[-1]
            prev = vals[-5] if len(vals) >= 5 else vals[0]
            delta = round(latest - prev, 1)
            if len(set(vals)) == 1:
                warnings.append(f"{label}: national series is perfectly flat ({vals[0]})")
            national.append({
                "key": g["key"],
                "label": label,
                "disease": g.get("disease", label),
                "terms": g["terms"],
                "headline": bool(g.get("headline")),
                "points": [{"date": p.date, "value": p.value} for p in pts],
                "latest": latest,
                "delta_4w": delta,
            })
            tail = "flat" if delta == 0 else (f"up {delta}" if delta > 0 else f"down {abs(delta)}")
            print(f"  [nat ] {label:<14} latest={latest:>5}  4-week {tail}")
        except Exception as err:
            failures.append({"group": g["key"], "stage": "national", "reason": str(err)})
            print(f"  [nat ] {label:<14} FAIL ({err})")
        if args.sleep:
            time.sleep(args.sleep)

    # --- interest by state, per group ------------------------------------------
    state_index: dict[str, dict] = {}
    code_index: dict[str, str] = {}
    order: list[str] = []
    for s in states:
        key = _norm(s["name"])
        state_index[key] = {"state": s["name"], "code": s.get("code", ""), "groups": {}}
        order.append(key)
        if s.get("code"):
            code_index[s["code"].upper()] = key

    for g in groups:
        label = g.get("label", g["key"])
        try:
            regions = provider.interest_by_region(g["terms"], geo=geo, weeks=weeks, regions=states)
            if not regions:
                raise RuntimeError("no regions returned")
            for r in regions:
                all_values.append(r.value)
                # Prefer matching on ISO code (reliable); fall back to name.
                vk = code_index.get((r.geo_code or "").upper()) or _norm(r.geo_name)
                if vk in state_index:
                    state_index[vk]["groups"][g["key"]] = r.value
                    if not state_index[vk]["code"] and r.geo_code:
                        state_index[vk]["code"] = r.geo_code
                else:
                    state_index[vk] = {"state": r.geo_name, "code": r.geo_code, "groups": {g["key"]: r.value}}
                    order.append(vk)
            print(f"  [geo ] {label:<14} {len(regions)} regions")
        except Exception as err:
            failures.append({"group": g["key"], "stage": "region", "reason": str(err)})
            print(f"  [geo ] {label:<14} FAIL ({err})")
        if args.sleep:
            time.sleep(args.sleep)

    print("-" * 78)

    # --- data-quality guard ----------------------------------------------------
    group_fail = len({f["group"] for f in failures if f["stage"] == "national"})
    fail_fraction = group_fail / len(groups) if groups else 1.0
    nonzero_fraction = (sum(1 for v in all_values if v) / len(all_values)) if all_values else 0.0

    if not national:
        print("ABORT: no national series produced. Writing nothing.", file=sys.stderr)
        return 1
    if fail_fraction > san.get("max_fail_fraction", 0.5):
        print(
            f"ABORT: {group_fail}/{len(groups)} groups failed nationally "
            f"({fail_fraction:.0%} > {san.get('max_fail_fraction', 0.5):.0%} threshold). Writing nothing.",
            file=sys.stderr,
        )
        return 1
    if nonzero_fraction < san.get("min_nonzero_fraction", 0.05):
        print(
            f"ABORT: data looks empty/flat ({nonzero_fraction:.0%} of values non-zero). "
            "Likely a broken query or a provider change. Writing nothing.",
            file=sys.stderr,
        )
        return 1

    headline_key = next((g["key"] for g in groups if g.get("headline")), groups[0]["key"])

    by_state: list[dict] = []
    for key in order:
        e = state_index[key]
        gv = e["groups"]
        if not gv:
            continue
        by_state.append({
            "state": e["state"],
            "code": e["code"],
            "groups": gv,
            "headline": gv.get(headline_key),
            "max_value": max(gv.values()),
            "top_group": max(gv, key=gv.get),
        })
    by_state.sort(key=lambda x: (x["headline"] if x["headline"] is not None else x["max_value"]), reverse=True)

    # City-level VIEW: each Layer 1 city inherits its state's group values.
    by_city: list[dict] = []
    for c in cities:
        gv = (state_index.get(_norm(c["state"])) or {}).get("groups", {})
        by_city.append({
            "name": c["name"],
            "state": c["state"],
            "lat": c.get("lat"),
            "lon": c.get("lon"),
            "groups": gv,
            "headline": gv.get(headline_key) if gv else None,
            "max_value": max(gv.values()) if gv else None,
            "top_group": max(gv, key=gv.get) if gv else None,
        })
    by_city.sort(
        key=lambda x: x["headline"] if x["headline"] is not None else (x["max_value"] if x["max_value"] is not None else -1.0),
        reverse=True,
    )

    payload = {
        "layer": 2,
        "layer_name": "Fever Signal (search attention)",
        "model_version": cfg.get("model_version", "unknown"),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provider": provider.name,
        "attribution": provider.attribution,
        "is_sample": bool(provider.is_sample),
        "disclaimer": DISCLAIMER,
        "geo": geo,
        "lookback_weeks": weeks,
        "headline_group": headline_key,
        "groups": [
            {
                "key": g["key"],
                "label": g.get("label", g["key"]),
                "disease": g.get("disease"),
                "terms": g["terms"],
                "headline": bool(g.get("headline")),
            }
            for g in groups
        ],
        "group_count": len(national),
        "state_count": len(by_state),
        "city_count": len(by_city),
        "failed_count": len(failures),
        "failures": failures,
        "national_trend": national,
        "by_state": by_state,
        "by_city": by_city,
    }

    # Provider-specific telemetry (e.g. Apify per-run cost + token failover).
    if hasattr(provider, "meta"):
        try:
            payload["provider_meta"] = provider.meta()
        except Exception:
            pass

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)

    print_summary(national, by_city, headline_key)
    if failures:
        print(f"\nNote: {len(failures)} provider call(s) failed but stayed under the abort threshold.")
    for w in warnings:
        print(f"WARN: {w}")

    pm = payload.get("provider_meta") or {}
    if pm.get("cost_usd_total") is not None:  # Apify: USD per run
        print(f"\nApify cost this build: ${pm['cost_usd_total']:.4f} across {len(pm.get('tokens_used') or [])} token(s).")
        for rc in pm.get("run_costs", []):
            c = rc.get("usd")
            cost = "  n/a" if c is None else f"${c:.4f}"
            print(f"   {rc['query'][:46]:<46} {cost:>9}  ({rc['token']})")
    if pm.get("searches_total") is not None:  # SerpApi: searches per build
        print(f"\nSerpApi searches this build: {pm['searches_total']} across {len(pm.get('keys_used') or [])} key(s).")
        for k, v in (pm.get("searches_by_key") or {}).items():
            print(f"   {k}: {v} searches")
    for sw in pm.get("switches", []):
        print(f"   key/token switch: {sw.get('reason')}")

    sample_note = ", SAMPLE data" if provider.is_sample else ""
    print(f"\nWrote {args.out}  ({len(by_city)} cities via {len(by_state)} states, "
          f"{len(national)} groups, provider={provider.name}{sample_note})")
    return 0


def print_summary(national: list[dict], by_city: list[dict], headline_key: str) -> None:
    print("\nNational search attention (latest value, 0-100 relative):")
    for n in national:
        d = n["delta_4w"]
        tail = "flat" if d == 0 else (f"up {d} over 4wk" if d > 0 else f"down {abs(d)} over 4wk")
        star = "  <- headline" if n["headline"] else ""
        print(f"  {n['label']:<14}{n['latest']:>6}   ({tail}){star}")
    print(f"\nTop cities by headline group ({headline_key}, via their state):")
    for e in by_city[:8]:
        hv = "-" if e["headline"] is None else e["headline"]
        print(f"  {e['name'] + ', ' + e['state']:<34}{hv:>6}")


if __name__ == "__main__":
    raise SystemExit(main())
