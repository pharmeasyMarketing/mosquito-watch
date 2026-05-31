# SEO + SSR Optimization — kickoff brief

> Self-contained starting point for the end-to-end SEO work in a fresh session.
> Read **`CLAUDE.md`** (project brief) and this file first. Also skim the memory
> files (`mosquito-watch-model`, `pharmeasy-branding`) and `README.md`.
> Work happens in this same project folder. Dev preview: `python -m http.server 8123`
> then `http://localhost:8123/`.

## Goal

Complete, end-to-end SEO optimization of the public dashboard:
1. **Meta tags** — title, description, canonical, robots, Open Graph, Twitter Card, theme-color, favicons/manifest, locale.
2. **JSON-LD structured data** — the schemas that actually fit a public health-data product (Organization, WebSite, WebApplication, **Dataset** ×3, FAQPage, BreadcrumbList).
3. **"Server-side rendering"** — for a *static* site this means **build-time pre-rendering** so crawlers receive real content + data in the HTML, not empty JS-filled containers. (See the big section below; true per-request SSR is the wrong tool here and would fight the architecture.)
4. Supporting infra: `robots.txt`, `sitemap.xml`, an OG share image, a semantic/heading/alt audit, and a Core-Web-Vitals performance pass (Core Web Vitals is a ranking signal).

## Where the project stands (context you need)

- **Product: "Mosquito Watch"** — one public dashboard, three layers, **all built and live**:
  Layer 1 Breeding Weather (`data/data.json`), Layer 2 Fever Signal (`data/fever_signal.json`,
  year-over-year), Layer 3 Confirmed Cases (`data/confirmed_season.json` = 2025 monsoon
  retrospective + `data/confirmed_cases.json` = latest-report strip).
- **The whole front end is ONE self-contained file: `index.html`** (~1300 lines, inline `<style>`
  and inline `<script>`, Leaflet from a CDN). **All content is rendered CLIENT-SIDE in JS** by
  fetching the `data/*.json` files on load. This is the core SEO problem: a crawler that does not
  run JS sees empty containers (`<tbody id="risk-body">`, `<div id="l3-chart">`, the L3 cards/table, etc.).
- **Architecture is deliberately server-less**: scheduled Python scripts write `data/*.json`; the
  static `index.html` reads them; a GitHub Actions cron (planned) regenerates the data; hosting is a
  free static host. Keep this. "SSR" must stay compatible with static hosting (so: pre-render at build time).
- **Branding**: PharmEasy property — brand teal `#10847E`, Inter font, a hotlinked logo + an inline-SVG
  recreation fallback. Confirm brand usage and get a proper branded image asset before launch
  (see `pharmeasy-branding` memory).
- **Copy voice**: humanized, and **no em dashes, en dashes, or middot separators** (already an
  SEO/style requirement). Keep that everywhere you touch copy.
- **Current `<head>` has only**: `charset`, `viewport`, `<title>` ("Mosquito Watch | PharmEasy Health
  Insights"), one `<meta name="description">`, font preconnect + Inter, Leaflet CSS. **Missing:**
  canonical, OG, Twitter, JSON-LD, theme-color, favicon, manifest, robots, sitemap, OG image.
- **Headings today**: one `<h1>` ("Mosquito Watch" in the header) + `<h2>` per section (Layer 1 map,
  City risk table, methodology, Layer 2, Layer 3) + `<h3>` sub-heads. Hierarchy is basically sound;
  audit it rather than rebuild it.
- `assets/img/` exists (brand bits). No `robots.txt`, `sitemap.xml`, `favicon`, `manifest`, or OG image yet.

## CRITICAL constraints (carry over — non-negotiable)

- **This is health-adjacent / YMYL content.** Google holds "Your Money or Your Life" pages to a high
  E-E-A-T bar (expertise, authority, trust). Lean into it: keep the heavy disclaimers, cite + link the
  official IDSP source, name the methodology and research, surface "last updated". Do **not** add anything
  that reads as clinical/diagnostic authority.
- **Environmental-risk framing, NOT medical/diagnostic.** This shapes the structured data: **be very
  careful with medical schema** (`MedicalWebPage`, `MedicalCondition`, `MedicalRiskScore`, …). Using it
  can imply clinical authority the product explicitly disclaims, and it can trip Google's medical-content
  scrutiny. **Recommendation: avoid medical schema**; model the page as a `WebApplication` / `Dataset`
  product, and refer to diseases as plain text or `about` keywords, not `MedicalCondition` entities.
  Treat "use medical schema or not" as an explicit decision (default: no).
- **Never imply prediction of individual illness or case forecasts.** Titles/descriptions/snippets must
  match the on-page framing ("screening / comparison / breeding-favourability", "officially reported
  cases", "search attention"), or you create a snippet-vs-content mismatch (bad for SEO and for honesty).
- **No em/en dashes or middots** in any copy you add (meta descriptions, OG text, FAQ answers, JSON-LD strings).
- Re-check with compliance/counsel before public launch (open project item).

## Scope 1 — Meta tags (in `index.html` `<head>`)

Add/optimize:
- `<title>` — keep ~50-60 chars, lead with the value + "India" + brand. The current one is fine; consider
  testing a more query-shaped variant (e.g. dengue / malaria / chikungunya + "India" + "tracker/risk").
- `<meta name="description">` — ~150-160 chars, compelling, matches on-page framing. Current copy is good;
  consider folding in a freshness hook.
- `<link rel="canonical">` — **needs the final URL** (see Open decisions). Make the base URL a single
  configurable value, don't hardcode it in 10 places.
- `<meta name="robots" content="index,follow,max-image-preview:large">`.
- **Open Graph**: `og:type` (website), `og:site_name`, `og:title`, `og:description`, `og:url`, `og:image`
  (+ `og:image:width/height/alt`), `og:locale` (`en_IN`).
- **Twitter Card**: `summary_large_image`, `twitter:title/description/image`, `twitter:site` (if a handle exists).
- `<meta name="theme-color" content="#10847E">`, `<meta name="color-scheme" content="light">`.
- Favicons + `apple-touch-icon` + a small `site.webmanifest` (name, icons, theme/background color).
- `lang`/locale: page is `lang="en"`; consider `en-IN` for India targeting. Optional `geo.region=IN` meta.
- Journalists screenshot this — the OG image matters. **Create a branded static OG image (1200×630)**
  (PharmEasy-branded; could be a styled snapshot). Auto-generating it from a headless screenshot at build
  time is an option but a static asset is simplest for v1.

## Scope 2 — JSON-LD structured data (`<script type="application/ld+json">`)

Recommended graph (validate every block in Google's Rich Results Test + schema.org validator):
- **Organization** — PharmEasy as publisher/sponsor: `name`, `url`, `logo`, `sameAs` (socials). Reusable `@id`.
- **WebSite** — `name`, `url`, `publisher` → Organization. (Skip `SearchAction`; there's no site search.)
- **WebApplication** (or `WebPage` that `isPartOf` the WebSite) — the dashboard is an interactive tool:
  `applicationCategory: HealthApplication`/`"Health & surveillance"`, `operatingSystem: Web`, `isAccessibleForFree: true`,
  `browserRequirements`, `about` (dengue/malaria/chikungunya as keywords), `dateModified` (from the data),
  `creator/publisher` → Organization.
- **Dataset ×3 — the highest-value, most differentiated markup** (Google Dataset Search indexes these).
  One per layer:
  - *Breeding-favourability index* — `distribution` → `data/data.json` (encodingFormat `application/json`),
    `temporalCoverage`, `spatialCoverage` (India / the city list), `variableMeasured`, `creator`, `license`,
    `isAccessibleForFree`, `dateModified`.
  - *Fever Signal (search attention)* — distribution → `fever_signal.json`; note it is Google-Trends-derived,
    relative 0-100.
  - *Confirmed Cases (IDSP 2025 season)* — distribution → `confirmed_season.json`; `creditText`/`isBasedOn`
    → the official IDSP reports; `temporalCoverage: 2025-05-01/2025-10-31`.
  Be honest in `description`/`license` (non-commercial Open-Meteo caveat; IDSP attribution).
- **FAQPage** — only if you add a real FAQ section (recommended; see Scope content below). Q/A must mirror
  visible on-page text (Google requires the answer to be present on the page).
- **BreadcrumbList** — low priority for a single page; add if/when there are sub-pages.
- **Avoid**: `MedicalWebPage`/`MedicalCondition`/`Dataset`-as-medical-claims (see constraints). `Article`/`NewsArticle`
  also doesn't fit (this is a tool, not an article).

Generate JSON-LD from the data at build time (see SSR) so `dateModified`, the headline numbers, and
`temporalCoverage` are always accurate, not stale hardcoded strings.

## Scope 3 — "Server-side rendering" (read this carefully — it's the big architectural call)

**The honest framing:** this is a static, server-less site by design (no Node/Next runtime, just static
files on a CDN). "Server-side rendering" in the per-request sense would require a server runtime + a
hosting pivot and contradicts the whole architecture. For a site whose data changes daily/weekly, the
correct equivalent is **build-time pre-rendering (a.k.a. static site generation / SSG)**: bake the
content + data into the served HTML during the build, so crawlers (and no-JS clients, and social/LLM
scrapers) get real content. **Recommend pre-rendering; flag true SSR as a separate, bigger decision** the
owner must opt into (it would mean moving off pure static hosting).

Two viable pre-render strategies — pick one early:

- **(A) Python template injection** — a new build step (`src/prerender.py` / `src/build_site.py`) reads
  `data/*.json` + `index.html` as a template and writes the populated HTML: meta tags, JSON-LD, and the
  **key content as real HTML** (city risk table rows, summary chips, the L3 season cards + by-state table,
  headline stats, the methodology text which is already static). Pros: pure static output, no browser dep,
  total control. Cons: re-implements some of the JS render logic in Python (keep the two in sync).
- **(B) Headless-browser snapshot** — at build time, Playwright/Puppeteer loads the page, lets the existing
  JS render, and saves the resulting DOM to `index.html`. Pros: zero logic duplication. Cons: adds a
  headless browser to the build (heavier CI), and you must stop the client JS from double-rendering on top
  of the snapshot.

**Whichever you choose, make the client JS hydration-aware / idempotent:** if pre-rendered content is
present, wire up interactivity (sort handlers, the disease/region toggles, the Leaflet map, pagination)
*without* wiping or duplicating it; if absent (plain `python -m http.server` dev with no pre-render),
render from scratch as it does today. This dual mode keeps local dev working and production pre-rendered.

**Pragmatic MVP path (recommended order):** start light, then deepen.
1. Pre-render only the **meta tags + JSON-LD** (pure data→HTML, easy, big win, no hydration needed).
2. Add a server-rendered **textual summary / key-stats block + plain data tables** (the numbers and the
   methodology) so crawlers index real content. The interactive **map and SVG charts can stay JS-only** —
   crawlers don't need an interactive map; give them descriptive text + `alt`/`aria-label` instead.
3. Only if needed, go full-DOM pre-render with hydration.

The pre-render step runs as the **last stage of the build** (after the layer data builds) and in the
GitHub Actions cron, so every data refresh re-bakes the HTML.

## Supporting infra + audit

- **`robots.txt`** (allow all, link the sitemap) and **`sitemap.xml`** (even one URL; include `lastmod`
  from the freshest `generated_at`). Generate the sitemap in the build so `lastmod` stays current.
- **Semantic/heading/alt audit**: confirm exactly one `<h1>`, logical `h2`/`h3` nesting (the three Layer
  headings are now visually prominent — keep them as real `<h2>`s), descriptive `alt` on the logo and any
  images, `aria-label`s on the SVG charts/map, and that the "skip the data, here's the gist" content is
  reachable without JS after pre-render.
- **Performance / Core Web Vitals** (ranking signal + the page already has a load-burst quirk on the
  single-threaded dev server): defer/`async` Leaflet, `preload` the critical font, lazy-load below-the-fold
  (the map/charts), keep `font-display:swap` (already set), minify the inline CSS/JS for production
  (a build step), and minimize render-blocking. Measure with Lighthouse.
- **Content for SEO**: consider a concise **FAQ section** (captures long-tail queries like "is dengue
  risk high in <city>", "where does the data come from", "is this medical advice") — doubles as FAQPage
  schema. Keep answers in the honest framing.

## Open decisions (resolve these EARLY — most of the above depends on them)

1. **Final domain / canonical URL.** Almost every tag (canonical, `og:url`, sitemap, JSON-LD `@id`/`url`)
   needs it. Project plan: free subdomain first, branded subdomain later (needs one DNS CNAME). **Until
   decided, put the base URL in ONE config value** (e.g. `config/site.json` read by the pre-render) and use
   a placeholder, so it's a one-line swap later.
2. **Hosting target** (GitHub Pages vs Vercel vs Netlify — still open in `CLAUDE.md`). Affects pre-render
   mechanics: GitHub Pages is pure static (pre-render must happen in the Actions build); Vercel/Netlify can
   run a build step natively. Does **not** require true SSR either way.
3. **OG image**: static branded asset (simplest) vs build-time generated screenshot.
4. **Medical schema**: default **no** (framing). Confirm.
5. **FAQ section**: add one? (Recommended.)
6. **Pre-render strategy A vs B** (Python injection vs headless snapshot).

## Suggested build order

1. Lock the **base URL config** + hosting/pre-render strategy (decisions 1, 2, 6).
2. **Meta tags** + favicons/manifest + theme-color + OG/Twitter (with the OG image).
3. **JSON-LD** (Organization, WebSite, WebApplication, Dataset ×3, FAQ if added) — generated from data.
4. **`robots.txt` + `sitemap.xml`** (build-generated `lastmod`).
5. **Pre-render MVP**: meta + JSON-LD baked in (step 1 of the SSR path).
6. **Pre-render content**: key stats + data tables into HTML; make JS hydration-aware.
7. **Semantic/heading/alt + accessibility audit**; add the FAQ section if chosen.
8. **Performance pass** (defer/preload/lazy-load/minify) + Lighthouse.
9. **Validate everything** (see checklist) and re-check compliance copy before any public push.

## File map (where things live)

```
index.html                     the entire front end (inline CSS + JS); all SEO meta/JSON-LD/pre-render lands here
assets/img/                    brand assets (add OG image, favicons here)
config/                        cities.json, scoring.json, trends.json, idsp.json   (+ add config/site.json for base URL?)
data/                          data.json, fever_signal.json, confirmed_season.json, confirmed_cases.json  (the datasets to expose)
src/
  build_layer1.py / build_layer2.py / build_layer3.py / build_layer3_season.py   (data builders → data/*.json)
  httputil.py                  shared stdlib HTTP helper
  (NEW) build_site.py / prerender.py   <- the build-time pre-render + sitemap + JSON-LD generator goes here
docs/                          LAYER2_KICKOFF.md, LAYER3_KICKOFF.md, (this) SEO_KICKOFF.md
README.md, CLAUDE.md           project docs / standing brief
```

## Validation checklist (definition of done)

- Google **Rich Results Test** passes for every JSON-LD block (no errors; warnings reviewed).
- **schema.org validator** clean.
- **View-source** (JS disabled) shows the title, description, canonical, OG/Twitter, JSON-LD, and the key
  textual content + numbers + a data table (i.e. pre-render works).
- OG/Twitter preview renders correctly (Facebook Sharing Debugger / Twitter Card Validator / a link unfurl).
- **Lighthouse**: SEO 100, solid Performance + Best Practices + Accessibility; Core Web Vitals in the green.
- **Mobile-Friendly** test passes (page is already responsive — keep it).
- `robots.txt` + `sitemap.xml` reachable and valid; `lastmod` reflects the latest data build.
- Snippets/structured data **match the on-page framing** (no medical/predictive over-claim).
- Disclaimers + official IDSP link still prominent; copy still free of em/en dashes and middots.
```
