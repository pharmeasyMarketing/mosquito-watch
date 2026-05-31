"""Season retrospective: pull every weekly IDSP report across a monsoon window,
parse each, and aggregate a week-on-week outbreak/case series per disease.

Why a retrospective and not "this week": IDSP publishes with a heavy, irregular
lag (often several weeks), so a single "latest week" is noisy and the "this week"
framing is dishonest. A full past season (e.g. 2025 May-Oct) is the real story --
outbreaks rise through the monsoon, peak, and fall -- and it is the ground-truth
substrate for the three-layer backtest (weather -> searches -> cases).

Downloads are cached under a (gitignored) cache dir so re-runs are fast and polite
to the government server. Each week passes the same structural guard as the live
parser; weeks that fail are recorded in `missing_weeks`, never silently dropped.
"""
from __future__ import annotations

import os
import time
from datetime import date

from . import fetch, parse


def _iso_monday(year: int, week: int):
    try:
        return date.fromisocalendar(year, week, 1)
    except ValueError:
        return None


def _iso_week_from(iso_date: str):
    """ISO week number from a 'YYYY-MM-DD' string (None if unparseable). The PDF
    header's '<N>th Week' text is occasionally mis-OCR'd (e.g. 18 -> 8), but the
    covered period dates parse reliably, so the week label is derived from them."""
    try:
        return date.fromisoformat(iso_date).isocalendar()[1]
    except (ValueError, TypeError):
        return None


def _week_overlaps_window(year: int, week: int, win_start: date, win_end: date) -> bool:
    """Keep a week if its ISO span overlaps the window. Unknown -> keep (the
    PDF's own period and the structural guard sort it out after download)."""
    mon = _iso_monday(year, week)
    if mon is None:
        return True
    sun = date.fromordinal(mon.toordinal() + 6)
    return mon <= win_end and sun >= win_start


def _cache_path(cache_dir: str, year: int, week: int) -> str:
    return os.path.join(cache_dir, str(year), f"week-{week:02d}.pdf")


def _download_cached(url: str, cache_path: str, insecure: bool) -> tuple[bytes, bool]:
    """Return (pdf_bytes, was_cached). A non-trivial file on disk is reused."""
    if cache_path and os.path.exists(cache_path) and os.path.getsize(cache_path) > 1000:
        with open(cache_path, "rb") as fh:
            return fh.read(), True
    data = fetch.download_pdf(url, insecure=insecure)
    if cache_path:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "wb") as fh:
            fh.write(data)
    return data, False


def build_season(config: dict, *, root: str, insecure: bool = False, log=print) -> dict:
    """Pull + parse + aggregate the season. Returns a dict the orchestrator wraps
    with layer metadata, guards, and writes to data/confirmed_season.json."""
    sc = config["season"]
    year = int(sc["year"])
    win_start = date.fromisoformat(sc["window_start"])
    win_end = date.fromisoformat(sc["window_end"])
    cache_dir = os.path.join(root, sc.get("cache_dir", "data/cache/idsp"))
    sleep = float(sc.get("polite_delay_s", 0.4))
    listing = config["listing_url"]
    disease_meta = config["diseases"]
    target_keys = [d["key"] for d in disease_meta]
    code_by_name = {s["name"]: s.get("code", "") for s in config.get("states", [])}
    min_anchors = config.get("sanity", {}).get("min_id_anchors", 5)

    all_weeks = fetch.discover_year(listing, year, insecure=insecure)
    candidates = [w for w in all_weeks if _week_overlaps_window(year, w["week"], win_start, win_end)]
    log(f"{year}: {len(all_weeks)} weekly reports on the listing, "
        f"{len(candidates)} in window {win_start} to {win_end}")

    weeks_out: list[dict] = []
    missing: list[dict] = []
    seen: set[int] = set()
    # Season-wide by-state accumulator (summed across every week in the window).
    state_map: dict[str, dict] = {}
    # Per-state WEEKLY accumulator: code -> week -> disease_key -> counts. Powers the
    # dashboard's region selector (swap the all-India curve for one state's).
    state_week: dict[str, dict] = {}

    for w in candidates:
        wk = w["week"]
        cache_path = _cache_path(cache_dir, year, wk)
        try:
            data, was_cached = _download_cached(w["pdf_url"], cache_path, insecure)
            rep = parse.parse_pdf(data, config)
        except Exception as err:
            missing.append({"week": wk, "reason": str(err)[:140]})
            log(f"  week {wk:>2}: FAIL ({str(err)[:80]})")
            continue

        # Refine the window using the PDF's own covered period when available.
        if rep.period_start and rep.period_end:
            try:
                ps, pe = date.fromisoformat(rep.period_start), date.fromisoformat(rep.period_end)
                if ps > win_end or pe < win_start:
                    log(f"  week {wk:>2}: outside window by period ({rep.period_label}), skipped")
                    continue
            except ValueError:
                pass

        if rep.id_anchor_count < min_anchors:
            missing.append({"week": wk, "reason": f"weak parse, {rep.id_anchor_count} ID anchors"})
            log(f"  week {wk:>2}: weak parse ({rep.id_anchor_count} anchors), skipped")
            continue

        # Derive the week number from the (reliable) covered period, not the
        # (sometimes mis-OCR'd) header text or the listing position.
        rweek = _iso_week_from(rep.period_start) or rep.report_week or wk
        if rweek in seen:
            log(f"  week {wk:>2}: duplicate report week {rweek}, skipped")
            continue
        seen.add(rweek)

        targets = [o for o in rep.outbreaks if o.disease_key in target_keys]
        per_disease = {}
        for d in disease_meta:
            rows = [o for o in targets if o.disease_key == d["key"]]
            per_disease[d["key"]] = {
                "outbreaks": len(rows),
                "cases": sum(o.cases or 0 for o in rows),
                "deaths": sum(o.deaths or 0 for o in rows),
            }
        # Accumulate the season-wide by-state table.
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
            code = code_by_name.get(o.state, "")
            if code:
                sde = state_week.setdefault(code, {}).setdefault(rweek, {}).setdefault(
                    o.disease_key, {"outbreaks": 0, "cases": 0, "deaths": 0})
                sde["outbreaks"] += 1
                sde["cases"] += o.cases or 0
                sde["deaths"] += o.deaths or 0

        weeks_out.append({
            "week": rweek,
            "year": rep.report_year or year,
            "week_label": rep.week_label or w["week_label"],
            "period_label": rep.period_label,
            "period_start": rep.period_start,
            "period_end": rep.period_end,
            "total_outbreaks": len(rep.outbreaks),
            "target_outbreaks": len(targets),
            "diseases": per_disease,
            "source_pdf_url": rep.source_pdf_url or w["pdf_url"],
        })
        log(f"  week {wk:>2}: {len(rep.outbreaks):>2} outbreaks, {len(targets):>2} tracked   {rep.period_label}")
        if sleep and not was_cached:
            time.sleep(sleep)

    weeks_out.sort(key=lambda x: x["week"])

    headline_key = next((d["key"] for d in disease_meta if d.get("headline")), target_keys[0])

    # Season totals + peak week per disease (peak by outbreak count, the headline metric).
    totals_by_disease = {}
    for d in disease_meta:
        k = d["key"]
        outs = sum(wd["diseases"][k]["outbreaks"] for wd in weeks_out)
        cas = sum(wd["diseases"][k]["cases"] for wd in weeks_out)
        dth = sum(wd["diseases"][k]["deaths"] for wd in weeks_out)
        # Peak = the week of highest reported CASES (the worst week), which is more
        # meaningful than the count of outbreak events.
        peak = max(weeks_out, key=lambda wd: wd["diseases"][k]["cases"], default=None)
        totals_by_disease[k] = {
            "label": d["label"],
            "outbreaks": outs,
            "cases": cas,
            "deaths": dth,
            "peak_week": peak["week"] if peak and peak["diseases"][k]["cases"] else None,
            "peak_week_cases": peak["diseases"][k]["cases"] if peak else 0,
        }

    by_state = []
    for e in state_map.values():
        e["district_count"] = len(e.pop("_districts"))
        e["headline"] = e["diseases"].get(headline_key, {}).get("cases", 0)
        by_state.append(e)
    by_state.sort(key=lambda x: (x["cases"], x["headline"]), reverse=True)

    # Per-state weekly series (sparse: only weeks where the state had an outbreak;
    # the dashboard fills zeros against the national week axis). Keyed by ISO code.
    name_by_code = {e["code"]: e["state"] for e in by_state if e.get("code")}
    regions = {}
    for code, weekmap in state_week.items():
        regions[code] = {
            "state": name_by_code.get(code, code),
            "weeks": [{"week": wk, "diseases": weekmap[wk]} for wk in sorted(weekmap)],
        }

    season_totals = {
        "target_outbreaks": sum(wd["target_outbreaks"] for wd in weeks_out),
        "target_cases": sum(t["cases"] for t in totals_by_disease.values()),
        "target_deaths": sum(t["deaths"] for t in totals_by_disease.values()),
        "all_outbreaks": sum(wd["total_outbreaks"] for wd in weeks_out),
        "weeks_parsed": len(weeks_out),
        "weeks_in_window": len(candidates),
        "states": len(by_state),
    }

    return {
        "year": year,
        "window_start": sc["window_start"],
        "window_end": sc["window_end"],
        "start_month": sc.get("start_month"),
        "end_month": sc.get("end_month"),
        "headline_disease": headline_key,
        "weeks": weeks_out,
        "missing_weeks": missing,
        "totals_by_disease": totals_by_disease,
        "by_state": by_state,
        "regions": regions,
        "season_totals": season_totals,
    }
