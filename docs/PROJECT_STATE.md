# Mosquito Watch - Project State & Handoff

> Consolidated context as of 2026-06-01. Read this plus `CLAUDE.md` at the start of a new session.
> It captures what is built, what is live, what is open, and how to run everything.

---

## 1. What this is

A public, PharmEasy-branded dashboard that scores **mosquito breeding favourability** for **dengue, malaria, chikungunya** across major Indian cities, shown as a three-layer causal chain. It is an **environmental-risk / surveillance** tool, **not** a medical or case-prediction tool. That framing is non-negotiable and shapes the copy and the structured data (no medical schema).

The three layers stay visually and conceptually separate:
1. **Breeding Weather** (Layer 1) - weather conditions favourable for breeding.
2. **Fever Signal** (Layer 2) - population search attention.
3. **Fever Panel** (Layer 3, v1) - PharmEasy lab test demand and positivity (coming-soon mock; replaces the parked IDSP Confirmed Cases layer).

---

## 2. Current status: LIVE on staging

- **Staging / QA URL (works now):** https://pharmeasymarketing.github.io/mosquito-watch/
  (deliberately `noindex` via robots.txt; this is the github.io origin)
- **Production URL (final, not yet wired):** https://pharmeasy.in/research/mosquito-watch-2026/
  This is a **subpath on the apex**, to be served by a reverse-proxy / path rule at PharmEasy's edge (NOT a DNS CNAME, you cannot CNAME a path). Infra has not added this route yet.
- Everything below is committed and deployed except where noted as open.

---

## 3. Architecture & stack

Server-less by design: scheduled scripts write data files, a static page reads them.

```
GitHub Actions (cron: daily / weekly / monthly)
  -> Python builders write data/*.json
  -> src/build_site.py pre-renders meta + JSON-LD + content into index.html (SSG)
  -> commit data back, deploy to GitHub Pages
Static front end: one index.html (inline CSS + JS, Leaflet from CDN) reads data/*.json
Production: PharmEasy edge proxies /research/mosquito-watch-2026/* to the Pages origin
```

- **Repo:** `pharmeasyMarketing/mosquito-watch` (**PUBLIC** - required for free GitHub Pages).
- **Host:** GitHub Pages. **Cron/build engine:** GitHub Actions.
- **Builders:** Python, stdlib-first (only extra dep is `pdfplumber` for Layer 3). See `requirements.txt`.
- **Base URL** lives in one place: `config/site.json` (`base_url`). One-line swap to change it.
- All in-page asset paths are **relative**, so the same build works on the github.io origin and behind the apex proxy.

---

## 4. The three layers (state of each)

| Layer | Data file(s) | Source | Cadence | Status |
|---|---|---|---|---|
| **L1 Breeding Weather** | `data/data.json` | Open-Meteo (no key) | daily | **Working.** 32 cities, transparent weighted score (temp fit x humidity/recent-rain/lagged-rain), buckets Low/Moderate/High/Very High. |
| **L2 Fever Signal** | `data/fever_signal.json` | Google Trends via **SerpApi** | weekly | **Working.** Year-over-year (this season vs last), national + 21 states, headline group "febrile" (Fever). 5 SerpApi keys in Actions secrets with failover. |
| **L3 Fever Panel** (v1) | `data/panel_signal.json` | PharmEasy lab diagnostics (**MOCK** for now) | weekly (when live) | **Coming-soon MOCK, shipped 2026-06-01.** Year-over-year Tests booked + Positivity % (Dengue / Malaria / Chikungunya / Typhoid). Sample data via `src/panel_providers/` (mock default); real feed = a weekly Google Sheet (stub `googlesheet` provider). **Replaces the old IDSP layer, which is parked + switchable** (see section 6.1). |

Disease coverage note: chikungunya has **no dedicated PharmEasy blog yet** (flagged in the blog audit), so it is intentionally not interlinked.

**Layer 3 pivot (2026-06-01):** Layer 3 changed from IDSP "Confirmed Cases" to the PharmEasy "Fever Panel" lab-testing view, per request. The old IDSP code/data is intact but commented-out/parked everywhere (index.html, build_site.py, the workflows); to restore it, follow the `LEGACY` markers. Same session also tightened the mobile first fold and trimmed verbose L1/L2 explainer copy.

---

## 5. What the most recent session delivered (SEO + nav + interlinks)

All committed and deployed:

- **Full SEO / SSG.** `src/build_site.py` (stdlib, idempotent) bakes into `index.html` at build time:
  - meta tags (title, description, canonical, robots, Open Graph, Twitter, theme-color, geo, favicons, manifest);
  - a 7-node JSON-LD `@graph` (Organization, WebSite, WebApplication, **Dataset x3**, FAQPage; deliberately **no medical schema**);
  - an "At a glance" key-stats band, the FAQ, and the JS-rendered tables/cards/chips as real HTML;
  - writes `robots.txt`, `sitemap.xml`, `site.webmanifest`.
- **Brand assets** via `src/build_assets.py` (Pillow, one-off, committed outputs): favicon set, app icons, 1200x630 OG image. Placeholder-grade, brand sign-off pending.
- **"This week at a glance" band:** 3 dynamic tiles (cities at High/Very High, top city, and a plain-language Fever search-trend read that flips with the year-over-year direction). No confirmed-case figures here on purpose.
- **PharmEasy header nav:** logo links to pharmeasy.in; desktop dropdowns (Healthcare, Health Hub, Editorial Policy, Research & Insights) and a mobile hamburger panel (accessible: aria-expanded, outside-click and Escape to close).
- **Blog interlinks:** a "Further reading from PharmEasy" section (Dengue / Malaria / Mosquito-bite & monsoon, 11 links) plus 2 inline links in the methodology, sourced from `Pharmeasy Blog - Monsoon & Related Topics (May 2026 audit).xlsx` (kept local, gitignored, internal doc).
- **Accessibility + performance:** single `<h1>`, clean heading outline, labeled map/charts, deferred Leaflet JS, non-blocking Leaflet CSS.
- **GitHub Actions:** `daily.yml` (L1), `weekly.yml` (L2 SerpApi x5-key + L3 latest), `monthly.yml` (L3 season), `deploy.yml` (push + manual). Cron commits data back and deploys.
- **Mobile fixes:** key-stats overflow on long city names, header made non-sticky on phones, chain card 1 made clickable to its section.
- **Verified the Daily workflow end to end** by triggering it live: Open-Meteo pulled 32/32 cities, committed `data/data.json`, redeployed. Works.

---

## 6. Open items / next up (prioritized)

1. **Wire the real Fever Panel feed (Layer 3 v1, when ready).** Layer 3 is now the Fever Panel, shipped as a coming-soon **MOCK** (deterministic sample data, badged "coming soon"). To go live: the backend publishes the weekly this-year numbers to a Google Sheet; set `config/panel.json` -> `google_sheet.csv_url` to its published-to-web CSV, implement the CSV parse in `src/panel_providers/googlesheet.py` (stdlib `urllib` + `csv`, no new dep), then switch `source` to `googlesheet` and enable the commented panel step in `weekly.yml`. The mock stays the default until then.
   - *(Parked)* The old IDSP "Confirmed Cases" layer had a known parser data-quality bug (implausible CFRs, Manipur mis-ranked, spiky/zero weeks). It is **no longer a launch blocker** because the layer is parked. If you ever switch IDSP back on, that bug must be fixed first: verify vs the cached PDFs (`data/cache/idsp/2025/week-*.pdf`), fix column mapping in `src/idsp/parse.py`, add a semantic guard (implausible CFR / outlier cases-per-outbreak / mid-season zeros).
2. **Conditions nav URL** is a best guess (`https://pharmeasy.in/conditions`); the original input was garbled. Confirm the correct URL (one-line fix in `index.html`).
3. **Open-Meteo commercial licensing** (launch blocker): free tier is non-commercial; confirm terms or budget the paid tier.
4. **Infra for production:** add the `/research/mosquito-watch-2026/*` reverse-proxy route, and allow that path + the sitemap reference in the `pharmeasy.in` apex robots.txt.
5. **Brand sign-off** on the placeholder OG image and favicons.
6. **External validation** on the live URL: Lighthouse, Google Rich Results Test (use code/paste mode on staging since robots disallows crawling), mobile-friendly, OG unfurl.
7. **Three-layer backtest** before any public "early warning" claim (overlay a past season to show weather -> searches -> cases with the lag).
8. **Hosting choice (optional):** can move serving to Hostinger (keep Actions as the builder). If you do that, you can then make the **repo private** (Pages was the only reason it is public). See chat for the Option A steps.
9. **Monitoring (recommended):** today, L1 build failures turn the Actions run red and email you, but L2/L3 are `continue-on-error` so their failures are silent-green. Add a final "fail the run if any source failed" step (and optionally a Slack/issue ping) so API/IDSP failures are loud on staging and prod.

---

## 7. How to run / build / test / deploy

**Local dev preview:**
```
python -m http.server 8123      # then open http://localhost:8123/
```
(There is also a `.claude/launch.json` "dashboard" server config for the preview tooling.)

**Rebuild data (each writes data/*.json):**
```
python src/build_layer1.py --provider open-meteo          # L1 weather
python src/build_layer2.py --provider serpapi             # L2 (needs SERPAPI_KEY in env / serpapi.env)
python src/build_layer3_panel.py                          # L3 v1 Fever Panel (mock -> data/panel_signal.json)
# python src/build_layer3.py --source live                # L3 IDSP latest report   (PARKED/switchable)
# python src/build_layer3_season.py                       # L3 IDSP season          (PARKED/switchable)
```

**Pre-render the site (run after any data build):**
```
python src/build_site.py        # SITE_ENV=staging default; SITE_ENV=production for prod robots
```

**Regenerate brand assets (one-off, needs Pillow):**
```
python src/build_assets.py
```

**Deploy:** push to `main` triggers `deploy.yml`. Cron workflows (daily/weekly/monthly) self-deploy. To run one manually: GitHub Actions tab -> pick the workflow -> Run workflow.

**Note on manual pushes:** the cron commits data back to `main` as `github-actions[bot]`, so before pushing from your machine run `git pull --rebase origin main` first.

---

## 8. Pending user/account actions (status)

- [x] GitHub Pages enabled; Source = GitHub Actions.
- [x] SerpApi keys added as Actions secrets (SERPAPI_KEY .. SERPAPI_KEY_5; all 5 wired into weekly.yml).
- [ ] Open-Meteo commercial licensing confirmed.
- [ ] Infra reverse-proxy route + apex robots.txt for the production subpath.
- [ ] Brand sign-off on OG image + favicons.
- [ ] Confirm the Conditions nav URL.

---

## 9. File map

```
index.html                 entire front end (inline CSS + JS); all SEO/nav/interlinks/pre-render land here
config/
  site.json                base URL + SEO identity (single source)
  cities.json              32 cities (name/state/lat/lon)
  scoring.json             L1 scoring parameters
  trends.json              L2 trends config
  panel.json               L3 v1 Fever Panel config (metrics, diseases, Google-Sheet feed)
  idsp.json                L3 IDSP config (PARKED -- legacy Confirmed Cases)
data/
  data.json                L1 output      | fever_signal.json  L2 output
  panel_signal.json        L3 v1 Fever Panel output (mock sample data)
  confirmed_season.json / confirmed_cases.json   L3 IDSP outputs (PARKED)
  cache/idsp/2025/*.pdf    cached IDSP weekly PDFs (gitignored; legacy parser)
src/
  build_layer1/2/3.py, build_layer3_season.py   data builders (build_layer3*.py = PARKED IDSP)
  build_layer3_panel.py    L3 v1 Fever Panel builder (active)
  build_site.py            SSG pre-render + JSON-LD + robots + sitemap + manifest
  build_assets.py          brand raster assets (one-off)
  scoring.py, httputil.py  shared
  providers/               L1 weather providers (open_meteo, nasa_power)
  trends_providers/        L2 providers (serpapi, apify, pytrends, mock) + _util (multi-key loader)
  panel_providers/         L3 v1 Fever Panel providers (mock default + googlesheet stub)
  idsp/                    L3 IDSP (PARKED): fetch.py, parse.py, season.py, live/fixture/sample
.github/workflows/         daily.yml, weekly.yml, monthly.yml, deploy.yml
assets/img/                favicons, app icons, og-mosquito-watch.png
robots.txt, sitemap.xml, site.webmanifest   build outputs (committed)
docs/                      LAYER2_KICKOFF, LAYER3_KICKOFF, SEO_KICKOFF, this PROJECT_STATE
CLAUDE.md, README.md       standing brief + readme
```

---

## 10. Guardrails & conventions (carry into every session)

- **Environmental-risk framing only.** Never diagnostic/predictive of individual illness. No medical JSON-LD.
- **Three layers stay separate.** Weather temperature is not body-temperature fever.
- **No em dashes, en dashes, or middot separators** in any copy (meta, FAQ, JSON-LD strings, UI text).
- **IDSP parser must fail loudly**, never publish garbage (currently under-enforced, see section 6.1).
- **Base URL lives only in `config/site.json`.** Keep all in-page asset paths relative.
- Internal docs/spreadsheets (`*.xlsx`) are gitignored; never commit them to the public repo.
- Re-check copy with compliance/counsel before any public launch.

---

## 11. Commit history (this work)

```
498d02e  Add PharmEasy header nav and blog interlinks
7b31164  chore(data): daily Layer 1 weather refresh [skip ci]   (bot, from the live workflow test)
285f2e2  Make chain card 1 (Breeding Weather) clickable to its section
25a0293  Make the header non-sticky on mobile
41d0885  Fix at-a-glance band overflow on mobile
76a10b5  Add end-to-end SEO, SSG pre-render, and GitHub Actions deploy/cron
be5b43a  Initial commit: Mosquito Watch dashboard + Layers 1 and 2
```
