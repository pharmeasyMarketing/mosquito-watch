# Mosquito Watch — Layer 1: Breeding-favourability (model L1-0.2.0)

A transparent, weather-driven **mosquito breeding-favourability** score (0–100) per
Indian city. Best fit for *Aedes* (dengue, chikungunya); malaria (Anopheles) and
other vectors need dedicated modules (see roadmap). "Mosquito Watch" is the umbrella
product across three layers; this is Layer 1.

> ⚠️ **Framing:** this is an *environmental breeding-favorability index*, **not** a
> case-count prediction and **not** a medical/diagnostic tool. Weather temperature
> is unrelated to body-temperature fever.

## Quick start

```bash
# Default: Open-Meteo (free, no API key — non-commercial use only)
python src/build_layer1.py

# Quick-switch to NASA POWER (public domain; OK for commercial use)
python src/build_layer1.py --provider nasa-power
#   or:  set WEATHER_PROVIDER=nasa-power   (Windows)
#        export WEATHER_PROVIDER=nasa-power (macOS/Linux)
```

No dependencies — standard-library Python 3.9+ only. Output is written to
[`data/data.json`](data/data.json) and a summary table is printed to the console
so you can eyeball scores against intuition.

## View the dashboard

The dashboard is a single static file ([`index.html`](index.html)) — a Leaflet
map + sortable risk table that reads `data/data.json`. Because browsers block
`fetch()` over `file://`, serve the folder over HTTP rather than double-clicking
the file:

```bash
python -m http.server 8123
# then open http://localhost:8123/
```

(Port 8123 rather than the usual 8000 — Windows reserves 8000 in an excluded
port range on this machine.) For hosting, the repo root is the web root: any
static host (GitHub Pages / Vercel / Netlify) serves `index.html` + `data/`.

## Branding

The dashboard is styled as a **PharmEasy** property: brand teal `#10847E`, the
**Inter** typeface (Google Fonts, `display=swap`), and a PharmEasy-style two-tier
sticky header. ⚠️ The header logo is a faithful **inline-SVG recreation** (leaf
mark + wordmark), **not** the official asset — before any public launch, swap in
the official PharmEasy logo and confirm brand usage with the PharmEasy team. The
risk-scale colours (green→amber→orange→red) are kept distinct from the brand teal;
the on-page legend disambiguates them.

## Weather providers (swappable)

Layer 1 reads weather through a `WeatherProvider` interface
([`src/providers/base.py`](src/providers/base.py)); the scoring formula never
knows which source produced the data. Add a provider in
[`src/providers/`](src/providers/) and register it in `providers/__init__.py`.

| Provider | Flag | Cost | Commercial use | History | Forecast |
|---|---|---|---|---|---|
| **Open-Meteo** (default) | `open-meteo` | Free | ❌ Free tier is non-commercial; paid ≈ $29/mo | ✅ from 1940 | ✅ |
| **NASA POWER** | `nasa-power` | Free | ✅ Public domain | ✅ from 1981 | ❌ (≈2–7 day latency) |

**Licensing — read before going live:** the Open-Meteo *free endpoint* is for
non-commercial use; a branded dashboard likely needs their paid tier. NASA POWER
is U.S.-government public domain (free for any use). The plan: demo on Open-Meteo
free now, then either buy the Open-Meteo paid tier or flip to `--provider nasa-power`.

## Methodology (the formula)

```
score = 100 × temperature_suitability × ( w_h·humidity + w_rr·rain_recent + w_rl·rain_lagged )
```

- **Temperature** is a *limiting multiplier*: 0 below ~18 °C and above ~35 °C,
  full across the optimal ~25–30 °C band (Aedes/Anopheles breeding range). If
  it's too cold or too hot, the score is gated toward 0 regardless of moisture.
- **Humidity** favorability ramps from 0 at ≤40 % RH to 1 at ≥70 % RH (>~60 %
  extends mosquito lifespan).
- **Recent rain** = accumulated rainfall over the last 7 days (fresh standing water).
- **Lagged rain** = rainfall 7–14 days ago, weighted highest, because adult
  emergence lags rainfall by ~1–2 weeks. This explicit lag is the core mechanic.
- **Rainfall response (v2, L1-0.2.0)** is concave and *non-monotonic*:
  `S_R(R) = (1 − e^(−R/30)) × heavy-rain penalty`. Moderate rain helps; rain above
  ~150 mm in a window is progressively discounted, since heavy rain can flush out larvae.

Buckets: **Low** `<25` · **Moderate** `25–50` · **High** `50–75` · **Very High** `≥75`.

Every constant (weights, temperature band, humidity thresholds, rainfall
parameters, bucket cutoffs) lives in [`config/scoring.json`](config/scoring.json)
— tune it and re-run; no code changes needed.

## Configuration

- [`config/cities.json`](config/cities.json) — the city list (name, state,
  lat/lon). Add/remove freely.
- [`config/scoring.json`](config/scoring.json) — all formula parameters + the
  data-quality guard thresholds.

## Data-quality guard

The build **aborts and writes nothing** if no city scores or if more than
`sanity.max_fail_fraction` (default 50%) of cities fail — so a provider outage or
schema change can never silently publish bad data to a branded dashboard.

## Layer 2 — Fever Signal (search attention)

Layer 2 tracks **population search attention** to fever/symptom terms via Google
Trends — nationally over time, and **by city** so it lines up with Layer 1. Google
Trends only resolves India at the **state** level for these terms (city-level data
is too sparse — a probe returned ~1 city), so each city shows its state's signal,
clearly labelled, reusing Layer 1's exact `config/cities.json`. It is the middle
link in the "watch the chain light up" story (weather → searches → cases, each
lagged ~1–2 weeks). Build it and write `data/fever_signal.json`:

```bash
# Default: mock/sample provider — deterministic synthetic data, no deps, no key
python src/build_layer2.py

# Real providers, behind the same swappable interface:
python src/build_layer2.py --provider pytrends      # needs: pip install pytrends
python src/build_layer2.py --provider serpapi       # needs: set SERPAPI_KEY=...
#   or:  set TRENDS_PROVIDER=pytrends   (Windows)
```

The dashboard reads `data/fever_signal.json` **independently** of Layer 1's
`data/data.json`, so the two layers stay modular, separately scheduled, and never
blended into one number. A Layer 2 load failure leaves Layer 1 fully working.

### Trends providers (swappable)

Mirroring Layer 1's weather providers, Layer 2 reads Trends through a
`TrendsProvider` interface
([`src/trends_providers/base.py`](src/trends_providers/base.py)); the orchestrator
and dashboard never know which source produced the numbers.

| Provider | Flag | Cost | Notes |
|---|---|---|---|
| **Mock / sample** (default) | `mock` | Free | Synthetic, deterministic. Sets `is_sample` so the dashboard badges it loudly. Build & demo with no API/key. |
| **Apify** | `apify` | ~$0.30/build (~$9/mo daily) | Managed scraper; one ~5-min run returns timeline + state breakdown together (4 runs/build), cached. Multi-token failover. Needs `APIFY_TOKEN`. |
| **SerpApi** | `serpapi` | Free trial (250 searches/key/mo) | Managed JSON API; seconds per call. Timeline + state map are separate calls → 8 searches/build. Multi-key failover. Needs `SERPAPI_KEY`. |
| **PyTrends** | `pytrends` | Free | Unofficial; **archived/read-only since 2025-04-17**, rate-limited & fragile. Dev / light use only. Imported lazily (optional dep). |

> ⚠️ **Honest framing (kept in the UI):** search interest is **attention, not
> cases**; it is **relative/normalized 0–100**, not absolute counts; and **weather
> temperature ≠ body-temperature fever** (weather temp lives only in Layer 1). The
> dashboard surfaces all three caveats and badges the sample data.

> **Open items before a real Trends source goes live:** pick + fund the managed
> provider (SerpApi vs ScrapingBee vs Apify vs DataForSEO), verify the India region
> codes in `config/trends.json` against that provider, and re-check compliance now
> that fever data is in scope. Until then the dashboard runs on the **sample**
> provider and says so.

Search-term groups, the India state/UT list, the lookback window, and the guard
thresholds all live in [`config/trends.json`](config/trends.json) — edit and
re-run; no code changes. The same fail-loud guard applies: `build_layer2.py`
aborts and writes nothing if no national series is produced, if more than
`sanity.max_fail_fraction` of groups fail, or if the provider returns all-zero /
flat data.

### Apify: multi-token failover & cost

Put one or more Apify tokens in a gitignored `.env` / `apify.env` at the project root:

```
APIFY_TOKEN=apify_api_primary
APIFY_TOKEN_2=apify_api_backup        # optional; add as many as you like
# ...or a single list:  APIFY_TOKENS=apify_api_a, apify_api_b
```

Before each actor run the provider checks the active token's remaining monthly
budget (`GET /v2/users/me/limits`); if it falls below a reserve (or a self-imposed
per-token cap), it **rotates to the next token**. A billing/auth error mid-run also
triggers failover, and the build fails loudly only when every token is spent. Each
run's `usageTotalUsd` is tracked and written to `fever_signal.json` under
`provider_meta` (with a console cost summary). Optional knobs sit beside the tokens:
`APIFY_MIN_RESERVE_USD`, `APIFY_MAX_SPEND_PER_TOKEN_USD`, `APIFY_EST_RUN_COST_USD`.
Check balances any time:

```bash
python src/apify_balances.py
```

> ⚠️ **Cost reality (measured):** one run takes ~5 minutes and cost **~$0.07–0.10**
> in testing (it scrapes cities/metros/related queries we don't use, with no flag to
> disable that), so a 4-group build is **~$0.30** and ~$9/month run daily. Apify's $5
> free tier per account covers roughly a month of daily builds — tight, hence the
> multi-token failover. For daily use, SerpApi is cheaper (below).

### SerpApi: multi-key failover & search budget

The `serpapi` provider calls SerpApi's `google_trends` engine — a clean JSON API
that returns in **seconds** (not minutes) and, on the trial caps, **free**. Keys go
in a gitignored `.env` / `serpapi.env`, with the same failover as Apify:

```
SERPAPI_KEY=primary_key
SERPAPI_KEY_2=backup_key               # optional; ...or SERPAPI_KEYS=a,b
```

Before each search it checks the active key's remaining monthly searches
(`GET /account.json` — free, not counted against quota) and rotates when one runs
low. Knobs: `SERPAPI_MIN_RESERVE`, `SERPAPI_MAX_SEARCHES_PER_KEY`. Check balances:

```bash
python src/serpapi_balances.py
```

**Search budget.** SerpApi needs *two* calls per group (one `TIMESERIES` for the
trend line + one `GEO_MAP_0` for the state map), so a 4-group build = **8 searches**.

| Cadence | Searches/month | Trial caps (250/key) |
|---|---|---|
| Daily | ~240 | fits 1 key; 2 keys = safe with failover |
| **Weekly** (recommended) | ~35 | trivial; one key lasts months |

Trends data is weekly-granular and we resample to weekly anyway, so **weekly L2 builds**
are the sweet spot: a few dozen searches a month, effectively free.

### Apify vs SerpApi

| | Apify | SerpApi |
|---|---|---|
| Speed | ~5 min/run (~20 min/build) | seconds/call (<1 min/build) |
| Cost | ~$0.30/build, ~$9/mo daily | free within trial caps (250/key/mo) |
| Calls/build | 4 runs (timeline+regions together) | 8 searches (timeline & regions separate) |
| Shape | one actor run, poll to finish | clean JSON, instant |

Both sit behind the same `TrendsProvider` interface, so switching is one flag
(`--provider serpapi`) or `TRENDS_PROVIDER=serpapi` in `.env`.

## Project layout

```
index.html     the static dashboard (Leaflet map + sortable table + Layer 2 chart/table)
config/        cities.json, scoring.json, trends.json   (editable, no logic)
src/
  providers/         base.py, open_meteo.py, nasa_power.py, __init__.py   (Layer 1 weather)
  trends_providers/  base.py, _util.py, mock.py, apify.py, serpapi.py, pytrends_provider.py, __init__.py   (Layer 2 trends)
  scoring.py         the transparent weighted formula (Layer 1)
  httputil.py        stdlib JSON HTTP helper (shared)
  build_layer1.py    orchestrator → data/data.json          (weather)
  build_layer2.py    orchestrator → data/fever_signal.json  (fever signal)
  apify_balances.py / serpapi_balances.py   utilities: print remaining provider budget
data/          data.json + fever_signal.json (generated; committed for the dashboard)
```

## Roadmap

✅ Layer 1 (breeding weather) → ✅ static Leaflet dashboard → ✅ Layer 2 (Fever
Signal: city-level view backed by state data, **live via SerpApi** with multi-key
failover — 8 searches/build, seconds, free within trial caps; Apify also available)
→ Layer 3 (IDSP weekly PDFs) → GitHub Actions cron (daily L1, **weekly L2**, weekly
L3) → polish + launch.
