# Layer 3 — Confirmed Cases (IDSP): kickoff brief

> Self-contained starting point for building Layer 3 in a fresh session.
> Read `CLAUDE.md` (project brief) and this file first. This is the **hardest** layer.

## Where the project stands (context)
- **Product: "Mosquito Watch"** — umbrella over three layers: **Breeding Weather** (live, `L1-0.2.0`),
  **Fever Signal** (live, `L2-0.1.0`), **Confirmed Cases** (this — planned).
- **Public dashboard** = `index.html` at the repo root. PharmEasy-branded (teal `#10847E`, Inter, hotlinked
  logo, two-tier sticky header). Humanized copy voice — **no em dashes, en dashes, or middot separators**
  (SEO requirement); keep that style. Local preview: `python -m http.server 8123` → `http://localhost:8123/`.
- **Patterns to mirror** (read these as your templates):
  - Layer 1: `src/providers/` (swappable weather providers), `src/scoring.py`, `config/scoring.json`,
    `src/build_layer1.py` → `data/data.json`.
  - Layer 2: `src/trends_providers/` (`base.py`, `mock.py`, `pytrends_provider.py`, `serpapi.py`, `apify.py`),
    `config/trends.json`, `src/build_layer2.py` → `data/fever_signal.json`. **Mock provider is the default**
    so the pipeline runs offline; real providers swap in behind the interface.
  - Shared HTTP helper: `src/httputil.py`.
- The dashboard already shows a **"Confirmed Cases" card marked "Coming soon"**. Layer 3 turns it on.
- Also read: `README.md`, memory files, `mosquito_breeding_favorability_index_recommendations_v2.pdf`.

## Goal
**Confirmed Cases** = officially reported outbreaks/cases from **IDSP Weekly Outbreak Reports**, by state/district.
This is the authoritative, ground-truth layer and the last link in the chain (weather → searches → cases). It
**lags ~1–2 weeks** — that is fine; it is a weekly *validation* layer, not real-time. The dashboard disclaimers
already tell users to read the other layers "alongside official surveillance" — Layer 3 *is* that official source.

## Source (IDSP, Ministry of Health & Family Welfare)
- **Weekly Outbreaks listing** (year-by-year table of weekly PDFs, 2013–present) — the entry point:
  `https://idsp.mohfw.gov.in/index4.php?lang=1&level=0&linkid=406&lid=3689`
- Outbreaks overview + methodology (outbreak-ID coding = State/District/Year/Week/number):
  `https://idsp.mohfw.gov.in/index4.php?lang=1&level=0&linkid=403&lid=3685`
- Disease Alerts by year: `https://idsp.mohfw.gov.in/index4.php?lang=1&level=0&linkid=427&lid=3780`
- IHIP section: `https://idsp.mohfw.gov.in/index4.php?lang=1&level=0&linkid=454&lid=3977`
- Diseases under Surveillance (full condition list): `https://idsp.mohfw.gov.in/index1.php?lang=1&level=1&sublinkid=5985&lid=3925`

## What to extract
From each weekly PDF, pull rows for: **Dengue, Malaria, Chikungunya**, plus **"Fever with Rash"** and
**Acute Febrile Illness** categories, broken down by **state/district** where available. Capture the
**reporting week** the PDF covers.

## The hard realities (the genuinely fiddly part)
1. **Data is locked in PDFs, not an API.** Need a PDF table-parsing step. Recommend **`pdfplumber`** first
   (pure-Python, no system deps); `camelot` is an alternative but needs Ghostscript/Tk. Government PDF table
   formatting is **inconsistent week to week** — this is the hardest part of the whole project. Parse defensively.
2. **File URLs are non-predictable hashes** (e.g. `.../l892s/70309395281777439071.pdf`) — you **cannot** guess
   the latest week's URL. The scraper must: fetch the listing page → parse the HTML table to find the **newest
   week's link** → download that PDF → parse it.
3. **Mixed hosts:** some weeks link to the IDSP server, others to **Google Drive**. Handle both download paths.
4. **Lag:** reports lag a week or two. Fine — weekly cadence.

## MANDATORY data-quality guard (non-negotiable)
Because we parse government PDFs whose format can change, build a sanity check: **flag/abort (write nothing) if
the parser returns zero outbreaks or an unexpected structure.** A format change must NEVER silently feed bad data
to a branded dashboard. This is the single most important requirement of Layer 3.

## Architecture (mirror Layer 1 / Layer 2)
- Two stages, kept separate:
  1. **Discovery + fetch**: load the listing page, parse the HTML table for the newest week's link, download the
     PDF (handle IDSP-server and Google-Drive hosts). Reuse `src/httputil.py`.
  2. **Parse**: extract the target rows from the PDF into structured data.
- **Swappable source, mock-first** (like Layer 2): provide a **"live IDSP" source** and a **"local sample PDF"
  fixture source**, so you can build the parser + dashboard offline and run regression tests against a known
  report. Default to the sample for dev; switch to live via a `--source` flag / env var.
- Config: `config/idsp.json` (listing URL, target diseases/categories, state list, optional manual PDF-URL override).
- Orchestrator: `src/build_layer3.py` → `data/confirmed_cases.json`, applying the data-quality guard before writing.
- Suggested package: `src/idsp/` (e.g. `fetch.py`, `parse.py`) mirroring the `trends_providers/` package style.

## Output shape (recommended)
- Write a **separate `data/confirmed_cases.json`** (alongside `data/data.json` and `data/fever_signal.json`).
- Contents: metadata (generated_at, source, **report week covered**, source PDF URL, listing URL, disclaimer,
  version, guard status / parsed-row count) + rows per disease per state/district. Mirror the metadata
  conventions of Layers 1 and 2.

## Dashboard integration
- Flip the "Confirmed Cases" chain card from "Coming soon" → "Live".
- Add a Layer 3 view: a by-state/district sortable table (and optionally reuse the Leaflet map). **Show the
  report week and the lag**, and **link to the official IDSP source**. Keep it **visually separate** from
  Layers 1 and 2 (brief requirement — three layers stay distinct, never blended into one number).
- Reuse PharmEasy styling and the humanized, no-em-dash copy voice.

## The payoff: validation
With all three layers, **overlay a past monsoon season** (weather → searches → cases) and check the ~1–2 week
lag actually plays out, **before** any public "early warning" claim (brief + v2 PDF both require this). Layer 3
provides the ground truth for that backtest.

## Guardrails / framing
- Layer 3 is **actual reported data** — authoritative, but lags and is under-reported. It **validates**, it does
  not predict. Heavy disclaimers + prominent link to official IDSP.
- Same legal posture as the rest of the product (no disease-prediction / medical claims; screening + comparison).
- Re-check with compliance/counsel before public launch (open item).

## Build order
1. Discovery: fetch listing page, parse HTML table, find newest week's PDF link (handle IDSP + Google Drive hosts).
2. Download the PDF (`httputil`; both hosts).
3. Parse target rows with `pdfplumber` — **test against a saved sample PDF first** (fixture source).
4. Data-quality guard: abort if zero rows / unexpected structure.
5. Write `data/confirmed_cases.json`.
6. Dashboard: light up Confirmed Cases (separate section) + copy, caveats, IDSP link, report week.
7. Later: GitHub Actions weekly schedule; then the 3-layer backtest.

## Tech notes
- New dependency likely: `pdfplumber` (and `requests` if not reusing `httputil`). Keep it light otherwise.
- Test the parser on **2–3 real recent weekly reports** plus the saved sample — formats drift.
- Dev env is Windows / PowerShell; preview server on port 8123.
