"""Layer 1 orchestrator: fetch weather per city, compute breeding-favorability,
write data/data.json, and print a summary you can eyeball against intuition.

Usage (from the project root):
    python src/build_layer1.py                      # Open-Meteo (default, free/non-commercial)
    python src/build_layer1.py --provider nasa-power
    WEATHER_PROVIDER=nasa-power python src/build_layer1.py

Data-quality guard: if no city scores, or more than `sanity.max_fail_fraction`
of cities fail, the script ABORTS and writes nothing -- a branded dashboard must
never silently publish garbage.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

# Make src/ importable whether run as `python src/build_layer1.py` or `-m`.
SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import providers  # noqa: E402
from scoring import score_location  # noqa: E402

ROOT = os.path.dirname(SRC_DIR)
DISCLAIMER = (
    "Weather-only mosquito breeding-favourability score for city-level screening "
    "and comparison. Not a disease forecast, case prediction, official alert, or "
    "individual health-risk estimate. Best read alongside official surveillance "
    "and local field observations."
)


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build Layer 1 (breeding favorability) data.json")
    p.add_argument(
        "--provider",
        default=os.environ.get("WEATHER_PROVIDER", providers.DEFAULT_PROVIDER),
        help=f"Weather provider. One of: {', '.join(providers.available())} (default: %(default)s)",
    )
    p.add_argument("--config-dir", default=os.path.join(ROOT, "config"))
    p.add_argument("--out", default=os.path.join(ROOT, "data", "data.json"))
    p.add_argument("--past-days", type=int, default=16, help="Days of history to request per city")
    p.add_argument("--sleep", type=float, default=0.25, help="Polite delay between city requests (s)")
    return p.parse_args()


def main() -> int:
    # Windows consoles often default to cp1252; force UTF-8 so the summary's
    # degree symbol (and any non-ASCII city names) render correctly.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    args = parse_args()
    cities = load_json(os.path.join(args.config_dir, "cities.json"))["cities"]
    cfg = load_json(os.path.join(args.config_dir, "scoring.json"))
    provider = providers.get_provider(args.provider)

    print(f"Provider: {provider.name}  |  Cities: {len(cities)}  |  past_days={args.past_days}")
    print("-" * 78)

    scored: list[dict] = []
    failures: list[dict] = []
    warnings: list[str] = []
    san = cfg["sanity"]

    for i, city in enumerate(cities, 1):
        label = f"{city['name']}, {city['state']}"
        try:
            records = provider.fetch_daily(city["lat"], city["lon"], past_days=args.past_days)
            result = score_location(records, cfg)
            if not result.get("ok"):
                failures.append({"city": label, "reason": result.get("reason", "unknown")})
                print(f"[{i:>2}/{len(cities)}] SKIP  {label:<32} ({result.get('reason')})")
            else:
                t = result["inputs"]["temp_mean_c"]
                if not (san["plausible_temp_min_c"] <= t <= san["plausible_temp_max_c"]):
                    warnings.append(f"{label}: implausible mean temp {t}C")
                entry = {**city, **{k: result[k] for k in ("score", "bucket", "components", "inputs")}}
                scored.append(entry)
                print(
                    f"[{i:>2}/{len(cities)}] OK    {label:<32} "
                    f"score={result['score']:>5}  {result['bucket']}"
                )
        except Exception as err:  # network/parse hard failure
            failures.append({"city": label, "reason": str(err)})
            print(f"[{i:>2}/{len(cities)}] FAIL  {label:<32} ({err})")
        if args.sleep:
            time.sleep(args.sleep)

    # --- data-quality guard -------------------------------------------------
    total = len(cities)
    fail_fraction = len(failures) / total if total else 1.0
    print("-" * 78)
    if not scored:
        print("ABORT: no cities scored. Writing nothing.", file=sys.stderr)
        return 1
    if fail_fraction > san["max_fail_fraction"]:
        print(
            f"ABORT: {len(failures)}/{total} cities failed "
            f"({fail_fraction:.0%} > {san['max_fail_fraction']:.0%} threshold). Writing nothing.",
            file=sys.stderr,
        )
        for f in failures:
            print(f"   - {f['city']}: {f['reason']}", file=sys.stderr)
        return 1

    scored.sort(key=lambda c: c["score"], reverse=True)
    payload = {
        "layer": 1,
        "layer_name": "Breeding Risk (weather-driven)",
        "model_version": cfg.get("model_version", "unknown"),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provider": provider.name,
        "attribution": provider.attribution,
        "disclaimer": DISCLAIMER,
        "scoring_config": cfg,
        "city_count": len(scored),
        "failed_count": len(failures),
        "failures": failures,
        "cities": scored,
    }

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)

    print_summary(scored)
    if failures:
        print(f"\nNote: {len(failures)} city(ies) failed but stayed under the abort threshold.")
    for w in warnings:
        print(f"WARN: {w}")
    print(f"\nWrote {args.out}  ({len(scored)} cities, provider={provider.name})")
    return 0


def print_summary(scored: list[dict]) -> None:
    print("\nBreeding-favorability summary (highest first):")
    print(f"  {'City':<26}{'State':<18}{'Score':>6}  {'Bucket':<10}{'T°C':>6}{'RH%':>6}{'Lag mm':>8}")
    for c in scored:
        inp = c["inputs"]
        print(
            f"  {c['name']:<26}{c['state']:<18}{c['score']:>6}  {c['bucket']:<10}"
            f"{inp['temp_mean_c']:>6}{(inp['humidity_pct'] if inp['humidity_pct'] is not None else '-'):>6}"
            f"{inp['rain_lagged_mm']:>8}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
