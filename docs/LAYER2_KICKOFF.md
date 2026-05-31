# Layer 2 — Fever Signal: kickoff brief

> Self-contained starting point for building Layer 2 in a fresh session.
> Read `CLAUDE.md` (project brief) and this file first.

## Where the project stands (context)
- **Product: "Mosquito Watch"** — an umbrella over three layers: **Breeding Weather** (live),
  **Fever Signal** (this, planned), **Confirmed Cases** (IDSP weekly PDFs, planned).
- **Public dashboard** = `index.html` at the repo root. PharmEasy-branded (teal `#10847E`, Inter font,
  hotlinked logo, two-tier sticky header). Reads `data/data.json`. Humanized copy voice — **no em dashes,
  en dashes, or middot separators** (SEO requirement); keep that style.
- **Layer 1 (Breeding Weather) is DONE** — model `L1-0.2.0`:
  - `src/scoring.py` (transparent weighted formula; temperature gate × humidity + recent rain + lagged rain;
    v2 rainfall is concave with a heavy-rain flush penalty),
  - `config/scoring.json` (all tunable constants), `config/cities.json` (~32 cities),
  - `src/build_layer1.py` (orchestrator → `data/data.json`, with a fail-loud data-quality guard),
  - `src/providers/` — **swappable weather providers** (Open-Meteo default, NASA POWER alternative)
    behind a `WeatherProvider` interface + registry.
- Dashboard already shows a **"Fever Signal" card marked "Coming soon"**. Layer 2 turns it on.
- Local preview: `python -m http.server 8123` then `http://localhost:8123/` (port 8000 is OS-reserved here).
  A `.claude/launch.json` "dashboard" config exists for the preview tool.
- Also read: `README.md`, the memory files (`mosquito-watch-model`, `pharmeasy-branding`), and
  `mosquito_breeding_favorability_index_recommendations_v2.pdf` (legal/scope framing).

## Goal
**Fever Signal** = population *attention* to fever/symptoms via **Google Trends**, by Indian state and over
time. It is the middle link in the "watch the chain light up" story: weather → searches → cases, each lagged
~1–2 weeks. This is the field of digital epidemiology / infodemiology (Google Flu Trends lineage).

## Architecture (mirror Layer 1)
- Build behind a **swappable `TrendsProvider` interface** (CLAUDE.md mandates this — Trends access is
  unreliable, so we must swap providers without touching the dashboard). Reuse the `src/providers/` pattern.
- Provider options:
  - **PyTrends** — free, unofficial, but **archived / read-only since 2025-04-17** and fragile. Fine for a
    dev/sample provider, not for production.
  - **Managed Trends APIs** (SerpApi, ScrapingBee, Apify, DataForSEO) — reliable, need an API key + budget.
    This is the production path. **(Provider choice + cost is an OPEN DECISION — see CLAUDE.md TODO.)**
  - **Start with a mock/fixture provider** (sample JSON) so the pipeline + dashboard can be built and tested
    without hitting any API, then plug in a real one behind the same interface.
- Config-driven: keep search terms + state list in `config/` (e.g. `config/trends.json`), like `cities.json`.

## Search terms (from CLAUDE.md; refine during build)
- General febrile: "fever", "viral fever", "body ache", "high temperature"
- Dengue: "dengue symptoms", "dengue test", "platelet count"
- Malaria: "malaria symptoms", "malaria test"
- Chikungunya: "chikungunya", "joint pain fever"

Use geo = India (IN) and its states/UTs; Trends values are normalized 0–100 and relative, not absolute counts.

## Output shape (recommended)
- Write a **separate `data/fever_signal.json`** — do not overload Layer 1's `data/data.json`. Keeps the layers
  modular and independently scheduled. The dashboard fetches it for the Fever Signal section.
- Suggested contents: metadata (generated_at, provider, terms, disclaimer, model/version, failed-count) +
  per-state latest values + a short time series per term/group. Mirror Layer 1's metadata conventions.

## Dashboard integration
- Flip the "Fever Signal" chain card from "Coming soon" → "Live".
- Add a Layer 2 view: a by-state sortable table and/or a small time-series chart (and optionally a state
  choropleth — Leaflet is already loaded, but that needs an India-states GeoJSON). **Keep it visually separate
  from Layer 1** (brief requirement — the three layers must stay distinct, never blended into one number).
- Reuse PharmEasy styling and the humanized, no-em-dash copy voice.

## Honest caveats (must surface in the UI)
- Search interest = **attention, not cases** (a news story spikes searches everywhere).
- It is **relative / normalized 0–100**, not absolute counts.
- **Weather temperature ≠ body-temperature fever** — never conflate them (weather temp lives only in Layer 1).
- Frame it as a screening/attention signal, **not** a case predictor (consistent with Layer 1 + the v2 PDF).

## Guardrails / open items
- **Data-quality guard**: same fail-loud philosophy as Layer 1 — abort and write nothing if the provider
  returns empty or unexpected data.
- **Provider + cost/licensing**: pick the managed Trends API and budget for it before production (OPEN).
- **Compliance re-check**: CLAUDE.md says to re-check with compliance once fever data is in scope. The v2 PDF's
  legal framing (no disease-prediction or medical claims; attention is not diagnosis) applies here too.

## Build order for Layer 2
1. `TrendsProvider` interface + a **mock provider** (fixtures) + config (terms, states).
2. Orchestrator `src/build_layer2.py` → `data/fever_signal.json`, with the data-quality guard.
3. Dashboard: light up the Fever Signal section (table/chart, separate from Layer 1), humanized copy + caveats.
4. Swap in a real managed-Trends provider behind the interface (needs the key/budget decision).
5. Later: GitHub Actions schedule (daily/weekly); backtest the weather → search lag against a past season.

## Tech notes
- Python; keep Layer 1's light-dependency style. A managed-API provider may need `requests`; stdlib elsewhere.
- Reuse the providers registry pattern; expose the provider via a `--provider` flag / env var.
- Dev env is Windows / PowerShell.
