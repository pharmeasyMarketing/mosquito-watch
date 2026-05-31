# Vector Risk Index — Project Brief

> This file is standing context for Claude Code. Read it at the start of every session.
> It defines what we're building, the architecture, the verified data sources, and the build order.

## What we're building

A public-facing dashboard that scores **mosquito breeding favorability** for dengue, malaria, and chikungunya across major Indian cities/districts, updated regularly. It combines weather-driven environmental risk with population fever signals and official outbreak data.

**Critical framing (non-negotiable):** This is an *environmental risk / breeding-favorability index*, NOT a case-count predictor and NOT a medical diagnostic tool. All copy, labels, and outputs must reflect this. We never say "you will get dengue" or imply clinical/diagnostic authority. This framing keeps it scientifically honest and avoids regulatory/liability problems (the sponsoring org is a health company, so this matters).

## The three-layer model (keep these SEPARATE — never blend into one number)

The dashboard shows a causal chain, each layer measured independently:

| Layer | What it measures | Source | Update freq |
|---|---|---|---|
| **1. Breeding Risk** | Weather conditions favorable for mosquitoes | Open-Meteo API | Daily |
| **2. Fever Signal** | Population attention / symptoms | Google Trends | Daily/weekly |
| **3. Confirmed Activity** | Officially reported cases | IDSP weekly reports | Weekly |

The "watch the chain light up in sequence" narrative (conditions → fever searches → confirmed cases, each lagged ~1–2 weeks) is the core story and is more credible than a single combined index. Keeping the layers separate is what makes it trustworthy to journalists and public-health readers.

## Layer 1 — Breeding Risk (build this FIRST; it's the easiest and fully self-contained)

### Science (transparent weighted formula — NOT machine learning)
A transparent formula is more credible to journalists and far easier to maintain than a black box. Breeding favorability depends on:
- **Temperature** — Aedes (dengue/chikungunya) and Anopheles (malaria) breed fastest ~25–30°C; activity drops below ~18°C and above ~35°C.
- **Rainfall** — creates standing water for breeding sites.
- **Lagged rainfall** — the last 7–14 days of rain matters more than today's (there's a ~1–2 week lag between rain and mosquito emergence). This lag is important — model it explicitly.
- **Humidity** — relative humidity above ~60% extends mosquito lifespan and biting activity.

Combine into a 0–100 score per location, bucketed into Low / Moderate / High / Very High.

### Data source: Open-Meteo
- Free JSON API, **no API key required**.
- Provides historical + forecast temperature, humidity, rainfall by lat/long.
- ⚠️ **Licensing caveat:** Open-Meteo is free for *non-commercial* use. A branded dashboard is arguably commercial — check their current terms and budget for their (inexpensive) paid/commercial tier if needed before going live. Flag this; don't silently assume the free tier covers us.
- Backup option: OpenWeather (free tier, requires key).

### City list
Start with the ~20–50 largest Indian cities (name + lat/long hardcoded in a config file). Expand to districts later. Keep the city list in a separate, easily-editable config (JSON or YAML) so it can grow without touching logic.

## Layer 2 — Fever Signal

### Approach
Use Google Trends for fever-related terms, mapped by state and over time. This is the established field of **infodemiology / digital epidemiology** (Google Flu Trends pioneered it; later academic work validated search data as a real signal for febrile/dengue surveillance).

### Search terms (per disease — refine during build)
General febrile: "fever", "viral fever", "body ache", "high temperature"
Dengue: "dengue symptoms", "dengue test", "platelet count"
Malaria: "malaria symptoms", "malaria test"
Chikungunya: "chikungunya", "joint pain fever"

### Honest caveats to build into the UI
- Search interest reflects *attention*, not confirmed cases (a news story spikes searches everywhere).
- It's relative/normalized (0–100), not absolute counts.
- DO NOT conflate weather temperature with body-temperature fever — they're unrelated. Weather temp belongs ONLY in Layer 1.

### Access reality (important)
- **PyTrends is archived (read-only since April 17, 2025)** and unmaintained — fine for light/personal use, fragile for production.
- For reliability, use a **managed Google Trends API** (e.g. SerpApi, ScrapingBee, Apify). There is no official public Trends API at production scale.
- Build this layer behind an interface so we can swap the Trends provider without rewriting the dashboard.

## Layer 3 — Confirmed Activity (IDSP)

### Source: IDSP Weekly Outbreak Reports
Main listing page (year-by-year table of weekly PDFs, 2013–present):
`https://idsp.mohfw.gov.in/index4.php?lang=1&level=0&linkid=406&lid=3689`

Other relevant pages:
- Outbreaks overview + methodology (outbreak-ID coding = State/District/Year/Week/number): `https://idsp.mohfw.gov.in/index4.php?lang=1&level=0&linkid=403&lid=3685`
- Disease Alerts by year: `https://idsp.mohfw.gov.in/index4.php?lang=1&level=0&linkid=427&lid=3780`
- IHIP section: `https://idsp.mohfw.gov.in/index4.php?lang=1&level=0&linkid=454&lid=3977`
- Diseases under Surveillance (full condition list): `https://idsp.mohfw.gov.in/index1.php?lang=1&level=1&sublinkid=5985&lid=3925`

### What to extract
From each weekly PDF, pull the rows for: **Dengue, Malaria, Chikungunya**, plus **"Fever with Rash"** and **Acute Febrile Illness** categories, broken down by state/district where available.

### Hard realities of this source (the fiddly part)
1. **Data is locked in PDFs, not an API.** Need a PDF-parsing step (`pdfplumber` or `camelot` for tables). Government PDF table formatting is inconsistent week to week — this is the genuinely hard part of the whole project.
2. **File URLs are non-predictable hashes** (e.g. `.../l892s/70309395281777439071.pdf`) — you CANNOT guess the latest week's URL. The scraper must:
   - fetch the Weekly Outbreaks listing page,
   - parse the HTML table to find the newest week's link,
   - download that PDF, then parse it.
3. **Mixed hosts:** some weeks link to the IDSP server, others to Google Drive. The scraper must handle both.
4. **Lag:** reports lag by a week or two. That's fine — this is a weekly *validation* layer, not real-time.

### Mandatory data-quality guard
Because we're parsing government PDFs whose format can change, build a sanity check: flag/abort (don't silently publish) if the parser returns zero outbreaks or an unexpected structure. A format change must never silently feed bad data to a branded dashboard.

## Architecture (no server, no database)

The whole thing is a **scheduled script that writes a data file + a static dashboard that reads it.**

```
[Scheduled job]
  └─ Python scripts
       ├─ Layer 1: pull Open-Meteo per city, compute breeding score   (daily)
       ├─ Layer 2: pull Google Trends per state                       (daily/weekly)
       ├─ Layer 3: scrape latest IDSP weekly PDF, extract rows        (weekly)
       └─ write data.json
             │
             ▼
[Static dashboard — HTML/JS]
  └─ reads data.json → renders India map + tables + "last updated"
```

### Stack
- **GitHub** — stores code + data; **GitHub Actions runs the scripts on a schedule for free** (this is our "server" — just a cloud cron job).
- **Dashboard** — static HTML/JS, map via **Leaflet.js** (free). Color-coded city markers, sortable risk table, "last updated" timestamp.
- **Hosting** — GitHub Pages / Vercel / Netlify (all free, auto-deploy on push).
- Must be **screenshot-friendly and mobile-friendly** (journalists screenshot these).
- Include a visible **methodology section** and the "environmental risk, not case prediction" disclaimer.

## Build order (do it in this sequence)

1. **Scaffold** the project structure (folders, config, skeleton files).
2. **Layer 1 script** — Open-Meteo fetch + scoring + `data.json` output. Run locally, eyeball scores against intuition (high during monsoon in humid cities; low in dry winter). Iterate on formula weights until sensible. ← *first working artifact*
3. **Dashboard** — Leaflet map + table reading `data.json`. Get it looking clean and screenshot-ready.
4. **Layer 3 scraper** — find latest IDSP weekly report, download, parse vector/fever rows to JSON, with the data-quality guard. (Hardest piece — test against a real live report.)
5. **Layer 2** — Google Trends via a managed API, behind a swappable interface.
6. **GitHub Actions** — schedule the scripts (daily for L1/L2, weekly for L3), commit updated `data.json`, trigger redeploy.
7. **Polish + go live** — methodology copy, disclaimers, mobile check, public URL.

## Validation before any public "early warning" claim

Before publicly claiming the leading-indicator chain works, overlay all three layers for a *past* monsoon season and show the lag actually plays out (weather → searches → cases). Don't assert the early-warning narrative until it's been backtested against real history.

## Guardrails summary
- Environmental risk framing only — never diagnostic/predictive of individual illness.
- Three layers stay visually and conceptually separate.
- Weather temp ≠ fever temp.
- Open-Meteo commercial licensing must be checked before launch.
- IDSP parser must fail loudly, never publish garbage.
- Heavy disclaimers + link to official IDSP sources; re-check with compliance once fever data is in scope.

## Open decisions / TODO
- [ ] Confirm Open-Meteo commercial licensing terms (or budget paid tier).
- [ ] Pick the Google Trends managed API provider.
- [ ] Finalize the initial city list + lat/longs.
- [ ] Decide hosting target (GitHub Pages vs Vercel vs Netlify).
- [ ] Resolve final domain (free subdomain first; a branded subdomain later needs one DNS CNAME record added by whoever manages the org's DNS — do this AFTER there's a working demo to show).
