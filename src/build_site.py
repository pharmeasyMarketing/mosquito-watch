#!/usr/bin/env python3
"""
build_site.py -- build-time pre-render (SSG) for Mosquito Watch.

The dashboard renders everything client-side from data/*.json, so a crawler that does not
run JS sees empty containers. This script bakes the SEO-critical content into index.html at
build time, so crawlers, no-JS visitors and social/LLM scrapers get real HTML. The existing
inline JS still runs on top and re-renders identical content, then wires up interactivity
(map, charts, sorting, toggles, pagination). Map and SVG charts stay JS-only; they get a
visually-hidden text fallback instead.

What it does (all idempotent, safe to re-run):
  - <head> SEO meta             -> between  <!-- build:seo -->   markers (from config/site.json)
  - JSON-LD structured data     -> between  <!-- build:jsonld --> markers (from data/*.json)
  - "At a glance" key stats     -> between  <!-- build:keystats --> markers
  - FAQ (visible Q/A)           -> between  <!-- build:faq --> markers (same source as FAQPage schema)
  - JS-rendered containers      -> inner HTML replaced by element id (mirrors the JS templates)
  - <body class="prerendered">  -> reveals the lazy-sec L2/L3 sections without JS
  - robots.txt and sitemap.xml  -> written to the repo root (lastmod from the freshest generated_at)

Usage:   python src/build_site.py            (SITE_ENV defaults to "staging")
         SITE_ENV=production python src/build_site.py

Stdlib only. The render functions below mirror the inline-JS templates in index.html and note
the line they mirror; keep the two in sync when either changes.
"""

import json
import os
import re
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------- helpers (mirror index.html)

def esc(s):
    """Mirror index.html esc() (line 650): escape & < > " for HTML."""
    s = "" if s is None else str(s)
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def num(v, d=1):
    """Mirror index.html num() (line 651): None -> 'n/a', number -> fixed decimals, else str."""
    if v is None:
        return "n/a"
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        return "%.*f" % (d, v)
    return str(v)


def thousands(n):
    try:
        return "{:,}".format(int(n))
    except (TypeError, ValueError):
        return str(n)


BUCKET_COLORS = {"Low": "#2b9348", "Moderate": "#f4b400", "High": "#f57c00", "Very High": "#d62828"}

# Mirror index.html LEVELS (line 596).
LEVELS = [
    {"name": "Very High", "range": "75-100", "meaning": "About as good as it gets for breeding right now."},
    {"name": "High", "range": "50-74", "meaning": "The weather is working in the mosquitoes' favour."},
    {"name": "Moderate", "range": "25-49", "meaning": "Some of the things mosquitoes need are in place."},
    {"name": "Low", "range": "0-24", "meaning": "The weather is mostly working against breeding."},
]

# Mirror index.html L3 palette (line 624).
L3_COLORS = {"dengue": "#2c6e9b", "chikungunya": "#7d5ba6", "malaria": "#6a8d3b", "fever_rash": "#b5852a", "afi": "#5d6d7e"}
L3_FALLBACK = ["#2c6e9b", "#7d5ba6", "#6a8d3b", "#b5852a", "#5d6d7e", "#9b59b6"]


def l3_color(key, i):
    return L3_COLORS.get(key) or L3_FALLBACK[i % len(L3_FALLBACK)]


def badge(b):
    """Mirror index.html badge() (line 738)."""
    return "<span class='badge' style='background:%s'>%s</span>" % (BUCKET_COLORS.get(b, "#888"), esc(b))


# ---------------------------------------------------------------- HTML injection (idempotent)

def set_inner_by_id(html, el_id, inner, required=True):
    """Replace the inner HTML of the element with the given id, matching nested same-tag children."""
    m = re.search(r'<(\w+)([^>]*\bid="%s"[^>]*)>' % re.escape(el_id), html)
    if not m:
        if required:
            raise SystemExit("build_site: element id=%r not found in index.html" % el_id)
        return html
    tag = m.group(1)
    start = m.end()
    depth = 1
    for mm in re.finditer(r'<(/?)%s\b' % re.escape(tag), html[start:], re.IGNORECASE):
        if mm.group(1):
            depth -= 1
            if depth == 0:
                close = start + mm.start()
                return html[:start] + inner + html[close:]
        else:
            depth += 1
    raise SystemExit("build_site: no closing </%s> for id=%r" % (tag, el_id))


def set_marker(html, key, inner, required=True):
    """Replace content between the build:key markers. Tolerates spaces and a descriptive note
    inside the opening comment, e.g. <!-- build:seo  (note) --> ... <!-- /build:seo -->."""
    pat = re.compile(
        r'(<!--\s*build:%s\b.*?-->)(.*?)(<!--\s*/build:%s\s*-->)' % (re.escape(key), re.escape(key)),
        re.DOTALL,
    )
    if not pat.search(html):
        if required:
            raise SystemExit("build_site: marker %r not found in index.html" % key)
        return html
    return pat.sub(lambda m: m.group(1) + inner + m.group(3), html, count=1)


def set_body_prerendered(html):
    """Ensure <body> carries the 'prerendered' class (reveals lazy-sec sections without JS)."""
    m = re.search(r'<body\b([^>]*)>', html)
    if not m:
        raise SystemExit("build_site: <body> not found")
    attrs = m.group(1)
    if re.search(r'\bclass="[^"]*\bprerendered\b', attrs):
        return html
    if 'class="' in attrs:
        new_attrs = re.sub(r'class="([^"]*)"', lambda c: 'class="%s prerendered"' % c.group(1).strip(), attrs, count=1)
    else:
        new_attrs = attrs + ' class="prerendered"'
    return html[:m.start()] + "<body%s>" % new_attrs + html[m.end():]


# ---------------------------------------------------------------- content blocks (mirror JS)

def render_summary_chips(cities):
    """Mirror renderSummary() (index.html line 761)."""
    counts = {"Very High": 0, "High": 0, "Moderate": 0, "Low": 0}
    for c in cities:
        b = c.get("bucket")
        if b in counts:
            counts[b] += 1
    out = ""
    for b in ["Very High", "High", "Moderate", "Low"]:
        out += ("<span class='chip'><span class='swatch' style='background:%s'></span>%s "
                "<b style='margin-left:2px'>%d</b></span>") % (BUCKET_COLORS[b], b, counts[b])
    return out


def render_level_guide():
    """Mirror renderLevelGuide() (index.html line 772)."""
    out = []
    for l in LEVELS:
        out.append(
            "<div class='lg-item'><span class='lg-dot' style='background:%s'></span>"
            "<div><div class='lg-name'>%s<span class='lg-range'>%s</span></div>"
            "<div class='lg-mean'>%s</div></div></div>"
            % (BUCKET_COLORS[l["name"]], esc(l["name"]), esc(l["range"]), esc(l["meaning"]))
        )
    return "".join(out)


def render_risk_rows(cities):
    """Mirror renderTable() page 1 (index.html line 815). cities are pre-sorted by score desc."""
    out = []
    for idx, c in enumerate(cities[:10]):
        i = c.get("inputs") or {}
        out.append(
            "<tr data-city='%s'>"
            "<td class='num rank'>%d</td>"
            "<td><b>%s</b></td>"
            "<td>%s</td>"
            "<td class='num score-cell' style='color:%s'>%s<span class='out'>/100</span></td>"
            "<td>%s</td>"
            "<td class='num'>%s</td>"
            "<td class='num'>%s</td>"
            "<td class='num'>%s</td>"
            "</tr>"
            % (esc(c["name"]), idx + 1, esc(c["name"]), esc(c["state"]),
               BUCKET_COLORS.get(c["bucket"], "#333"), num(c["score"]), badge(c["bucket"]),
               num(i.get("temp_mean_c")), num(i.get("humidity_pct")), num(i.get("rain_lagged_mm")))
        )
    return "".join(out)


def render_l3_cards(season):
    """Mirror renderL3Cards() (index.html line 1236)."""
    t = season.get("totals_by_disease") or {}
    diseases = season.get("diseases") or []
    out = []
    for i, d in enumerate(diseases):
        e = t.get(d["key"]) or {"cases": 0, "deaths": 0, "outbreaks": 0}
        color = l3_color(d["key"], i)
        zero = not e.get("cases")
        deaths = e.get("deaths", 0) or 0
        sub = "No cases reported in 2025" if zero else ("%d reported death%s over the season" % (deaths, "" if deaths == 1 else "s"))
        peak = ("Worst week: week %s" % e["peak_week"]) if e.get("peak_week") else ""
        out.append(
            "<div class='l3-card%s' style='border-top-color:%s'>"
            "<div class='l3-card-name'><span class='l3-dot' style='background:%s'></span>%s</div>"
            "<div class='l3-card-cases'>%d<span class='l3-card-unit'>cases</span></div>"
            "<div class='l3-card-sub'>%s</div>%s</div>"
            % (" zero" if zero else "", color, color, esc(d["label"]), e.get("cases", 0) or 0, sub,
               ("<div class='l3-card-peak'>%s</div>" % peak) if peak else "")
        )
    return "".join(out)


def render_l3_thead(season):
    """Mirror renderL3Table() header (index.html line 1289)."""
    diseases = season.get("diseases") or []
    head = "<tr><th class='num' data-key='rank'>#</th><th data-key='state'>State <span class='ind'></span></th>"
    for i, d in enumerate(diseases):
        head += ("<th class='num' data-key='%s'><span class='l3-dot' style='background:%s'></span>%s "
                 "<span class='ind'></span></th>") % (esc(d["key"]), l3_color(d["key"], i), esc(d["label"]))
    head += ("<th class='num' data-key='cases'>Total cases <span class='ind'></span></th>"
             "<th class='num' data-key='deaths'>Deaths <span class='ind'></span></th>"
             "<th class='num' data-key='district_count'>Districts <span class='ind'></span></th></tr>")
    return head


def render_l3_rows(season):
    """Mirror renderL3Table() body (index.html line 1312). Sort by_state by cases desc, page 1."""
    diseases = season.get("diseases") or []
    rows = sorted(season.get("by_state") or [], key=lambda e: e.get("cases") or 0, reverse=True)[:10]
    out = []
    for idx, e in enumerate(rows):
        tds = "<td class='num rank'>%d</td><td><b>%s</b></td>" % (idx + 1, esc(e["state"]))
        for d in diseases:
            dv = (e.get("diseases") or {}).get(d["key"])
            c = dv["cases"] if dv else 0
            tds += "<td class='num%s'>%d</td>" % ("" if c else " l3-zero", c or 0)
        tds += ("<td class='num l3-total'>%d</td><td class='num'>%d</td><td class='num'>%d</td>"
                % (e.get("cases", 0) or 0, e.get("deaths", 0) or 0, e.get("district_count", 0) or 0))
        out.append("<tr>%s</tr>" % tds)
    return "".join(out)


def l2_headline_point(l2):
    """Latest national headline (fever) search interest, with a year-over-year direction.
    Returns {val, label, dir} or None. dir is 'above' / 'below' / 'level with' / None."""
    grp = l2.get("headline_group") or "febrile"
    node = (l2.get("national_yoy") or {}).get(grp) or {}
    seasons = node.get("seasons") or {}
    smeta = l2.get("season") or {}
    cur = seasons.get(str(smeta.get("this_year") or "")) or []
    prev = dict((w, v) for w, v in (seasons.get(str(smeta.get("last_year") or "")) or []))
    if not cur:
        return None
    wk, val = cur[-1][0], cur[-1][1]
    last_year = prev.get(wk)
    if last_year is None:
        direction = None
    elif val - last_year >= 3:
        direction = "above"
    elif last_year - val >= 3:
        direction = "below"
    else:
        direction = "level with"
    return {"val": val, "label": node.get("label") or "Fever", "dir": direction}


def render_keystats(l1, l2):
    """Pre-rendered quick-points strip for the current signals: breeding weather (Layer 1) and
    search attention (Layer 2). Deliberately no confirmed-case figures (those live in Layer 3)."""
    cities = l1.get("cities") or []
    total = len(cities)
    high = sum(1 for c in cities if c.get("bucket") in ("High", "Very High"))
    top = cities[0] if cities else None

    tiles = [
        ("%d of %d" % (high, total), "Cities at High or Very High breeding weather this week", ""),
        (esc(top["name"]) if top else "n/a",
         ("Top breeding-favourability (%s/100)" % num(top["score"])) if top else "Top breeding-favourability", ""),
    ]
    # Layer 2 search-attention tile: a plain-language read of the year-over-year trend, NOT a raw
    # 0-100 figure (which reads like a score). The wording flips automatically with each weekly
    # Layer 2 build as the trend direction changes.
    sp = l2_headline_point(l2)
    if sp:
        term = esc(sp["label"])
        if sp["dir"] == "below":
            head, sub = "%s searches yet to pick up!" % term, "Trending lower than last year"
        elif sp["dir"] == "above":
            head, sub = "%s searches climbing" % term, "Trending higher than last year"
        elif sp["dir"] == "level with":
            head, sub = "%s searches holding steady" % term, "About the same as last year"
        else:
            head, sub = "%s searches" % term, "Tracking search attention this season"
        tiles.append((head, sub, "ks-msg"))

    return "<div class='ks-grid'>" + "".join(
        "<div class='ks-tile%s'><div class='ks-num'>%s</div><div class='ks-label'>%s</div></div>"
        % ((" " + cls) if cls else "", n, lbl)
        for n, lbl, cls in tiles
    ) + "</div>"


# ---------------------------------------------------------------- FAQ (visible + FAQPage schema)

FAQ_ITEMS = [
    ("Is dengue, malaria or chikungunya risk high in my city right now?",
     "Mosquito Watch shows a breeding-favourability score from 0 to 100 for major Indian cities, based "
     "only on this week's weather (temperature, humidity and recent rain). A high score means the weather "
     "suits mosquito breeding. It is a screening and comparison guide, not a count of cases and not a "
     "measure of your personal chance of illness."),
    ("Where does the data come from?",
     "Three independent sources, kept separate. Breeding weather comes from Open-Meteo. The fever signal "
     "comes from Google Trends search interest. Confirmed cases come from the official IDSP weekly outbreak "
     "reports published by India's Ministry of Health and Family Welfare."),
    ("Is this medical advice or a case forecast?",
     "No. Mosquito Watch is an environmental risk and surveillance dashboard, not a diagnostic or "
     "predictive tool. It never predicts individual illness or forecasts case counts. For diagnosis or "
     "treatment consult a doctor, and for official alerts follow your state health department and IDSP."),
    ("How often is it updated?",
     "Breeding weather updates daily. The fever signal updates weekly. Confirmed cases follow the IDSP "
     "weekly reports, which lag by a week or two, so Layer 3 reviews a finished season rather than counting "
     "live."),
    ("What do the risk levels mean?",
     "Scores are grouped into four bands: Low (0 to 24), Moderate (25 to 49), High (50 to 74) and Very High "
     "(75 to 100). The bands compare cities against each other by weather only. They are not the chance of "
     "mosquitoes being present, of disease spreading, or of anyone falling ill."),
    ("Why keep the three layers separate instead of a single score?",
     "Because they measure different things on different timelines. Weather conditions tend to lead, fever "
     "searches follow, and confirmed cases come last. Keeping them apart is more honest and easier to check "
     "than blending them into one number."),
]


def render_faq_html():
    out = []
    for q, a in FAQ_ITEMS:
        out.append("<div class='qa'><h3>%s</h3><p>%s</p></div>" % (esc(q), esc(a)))
    return "".join(out)


def faqpage_schema():
    return {
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": q,
             "acceptedAnswer": {"@type": "Answer", "text": a}}
            for q, a in FAQ_ITEMS
        ],
    }


# ---------------------------------------------------------------- JSON-LD graph

def iso_date(ts):
    """Return the YYYY-MM-DD portion of an ISO timestamp."""
    if not ts:
        return None
    return str(ts)[:10]


def pretty_date(ts):
    """Format an ISO timestamp as 'May 31, 2026' (mirrors the JS 'Last updated' stamp)."""
    if not ts:
        return "n/a"
    try:
        dt = datetime.strptime(str(ts)[:10], "%Y-%m-%d")
        return "%s %d, %d" % (dt.strftime("%b"), dt.day, dt.year)
    except ValueError:
        return str(ts)


def freshest(*datasets):
    stamps = [d.get("generated_at") for d in datasets if d and d.get("generated_at")]
    return max(stamps) if stamps else None


def build_jsonld(cfg, l1, l2, season, latest):
    base = cfg["base_url"]
    pub = cfg["publisher"]
    org_id = base + "#organization"
    site_id = base + "#website"
    app_id = base + "#webapplication"
    org = {
        "@type": "Organization", "@id": org_id,
        "name": pub["name"], "url": pub["url"], "logo": pub["logo"],
        "sameAs": list(pub.get("sameAs", [])),
    }
    if pub.get("legal_name"):
        org["legalName"] = pub["legal_name"]
    website = {
        "@type": "WebSite", "@id": site_id,
        "name": cfg["site_name"], "url": base,
        "inLanguage": cfg.get("language", "en-IN"),
        "publisher": {"@id": org_id},
    }
    webapp = {
        "@type": "WebApplication", "@id": app_id,
        "name": cfg["site_name"], "url": base,
        "applicationCategory": "HealthApplication",
        "operatingSystem": "Web",
        "browserRequirements": "The core data is available without JavaScript; the interactive map and charts require it.",
        "isAccessibleForFree": True,
        "inLanguage": cfg.get("language", "en-IN"),
        "description": cfg["description"],
        "about": ["Dengue", "Malaria", "Chikungunya", "Mosquito-borne disease surveillance in India"],
        "image": base + cfg["og_image"],
        "dateModified": freshest(l1, l2, season, latest),
        "isPartOf": {"@id": site_id},
        "creator": {"@id": org_id},
        "publisher": {"@id": org_id},
    }

    india_place = {
        "@type": "Place", "name": "India",
        "geo": {"@type": "GeoShape", "box": "6.7 68.1 35.7 97.4"},
    }

    asof = None
    if (l1.get("cities") or []):
        asof = ((l1["cities"][0].get("inputs")) or {}).get("as_of_date")

    ds_breeding = {
        "@type": "Dataset", "@id": base + "#dataset-breeding",
        "name": "Mosquito breeding-favourability index for Indian cities",
        "description": ("A weather-based 0 to 100 breeding-favourability score for major Indian cities, combining "
                        "temperature suitability, humidity and lagged rainfall. For screening and comparison only, "
                        "not a case count or forecast. Weather inputs are from Open-Meteo (CC BY 4.0); confirm "
                        "commercial-use terms before relying on this for a branded product."),
        "url": base, "inLanguage": cfg.get("language", "en-IN"),
        "isAccessibleForFree": True,
        "creator": {"@id": org_id}, "publisher": {"@id": org_id},
        "creditText": l1.get("attribution", "Weather data by Open-Meteo.com"),
        "license": "https://creativecommons.org/licenses/by/4.0/",
        "keywords": ["dengue", "malaria", "chikungunya", "mosquito breeding", "weather", "India", "vector surveillance"],
        "spatialCoverage": india_place,
        "temporalCoverage": asof,
        "variableMeasured": [
            {"@type": "PropertyValue", "name": "breeding_favourability_score", "minValue": 0, "maxValue": 100},
            "mean temperature", "relative humidity", "lagged rainfall",
        ],
        "distribution": {"@type": "DataDownload", "encodingFormat": "application/json",
                         "contentUrl": base + "data/data.json"},
        "dateModified": l1.get("generated_at"),
    }

    span = (l2.get("span") or "").strip().replace(" ", "/")
    ds_fever = {
        "@type": "Dataset", "@id": base + "#dataset-fever-signal",
        "name": "Fever Signal: search attention for fever and mosquito-borne disease terms in India",
        "description": ("Google-Trends-derived relative search interest (0 to 100, normalised) for fever and "
                        "dengue, malaria and chikungunya symptom terms across India, this season against last. "
                        "It reflects attention, not confirmed cases or counts of ill people."),
        "url": base, "inLanguage": cfg.get("language", "en-IN"),
        "isAccessibleForFree": True,
        "creator": {"@id": org_id}, "publisher": {"@id": org_id},
        "creditText": l2.get("attribution", "Google Trends via SerpApi"),
        "keywords": ["fever", "dengue symptoms", "malaria symptoms", "chikungunya", "Google Trends", "infodemiology", "India"],
        "spatialCoverage": india_place,
        "temporalCoverage": span or None,
        "variableMeasured": [
            {"@type": "PropertyValue", "name": "relative_search_interest", "minValue": 0, "maxValue": 100},
        ],
        "distribution": {"@type": "DataDownload", "encodingFormat": "application/json",
                         "contentUrl": base + "data/fever_signal.json"},
        "dateModified": l2.get("generated_at"),
    }

    ws, we = season.get("window_start"), season.get("window_end")
    ds_confirmed = {
        "@type": "Dataset", "@id": base + "#dataset-confirmed-cases",
        "name": "Confirmed mosquito-borne disease outbreaks in India, 2025 monsoon (IDSP)",
        "description": ("Officially reported outbreaks, cases and deaths for dengue, malaria, chikungunya and fever "
                        "with rash, by state and week, across the 2025 monsoon. Extracted from the IDSP weekly "
                        "outbreak reports. Authoritative but lagging surveillance data that undercounts, because not "
                        "every illness becomes a reported outbreak."),
        "url": base, "inLanguage": cfg.get("language", "en-IN"),
        "isAccessibleForFree": True,
        "creator": {"@id": org_id}, "publisher": {"@id": org_id},
        "creditText": season.get("attribution", "IDSP Weekly Outbreak Reports, Ministry of Health and Family Welfare"),
        "isBasedOn": season.get("listing_url"),
        "keywords": ["dengue", "malaria", "chikungunya", "fever with rash", "IDSP", "outbreak surveillance", "India", "2025 monsoon"],
        "spatialCoverage": india_place,
        "temporalCoverage": ("%s/%s" % (ws, we)) if (ws and we) else None,
        "variableMeasured": ["reported outbreaks", "confirmed cases", "deaths"],
        "distribution": {"@type": "DataDownload", "encodingFormat": "application/json",
                         "contentUrl": base + "data/confirmed_season.json"},
        "dateModified": season.get("generated_at"),
    }

    graph = [org, website, webapp, ds_breeding, ds_fever, ds_confirmed, faqpage_schema()]
    doc = {"@context": "https://schema.org", "@graph": graph}
    return doc


def jsonld_script(doc):
    body = json.dumps(doc, ensure_ascii=False, indent=2)
    body = body.replace("</", "<\\/")  # never let a data string close the <script> early
    return '<script type="application/ld+json">\n%s\n</script>' % body


# ---------------------------------------------------------------- head meta (from config)

def head_meta(cfg):
    base = cfg["base_url"]
    img = base + cfg["og_image"]
    title = esc(cfg["title"])
    desc = esc(cfg["description"])
    og_title = esc(cfg.get("og_title", cfg["title"].split(" | ")[0] + " | " + "Dengue & Malaria Risk in India"))
    og_desc = esc(cfg.get("og_description",
                          "Breeding weather, fever searches and officially confirmed cases for dengue, malaria and "
                          "chikungunya across India. A screening guide, not medical advice."))
    img_alt = esc(cfg.get("og_image_alt", cfg["site_name"]))
    lines = [
        "<title>%s</title>" % title,
        '<meta name="description" content="%s" />' % desc,
        '<link rel="canonical" href="%s" />' % base,
        '<meta name="robots" content="index,follow,max-image-preview:large" />',
        '<meta name="theme-color" content="%s" />' % cfg.get("theme_color", "#10847E"),
        '<meta name="color-scheme" content="light" />',
        '<meta name="geo.region" content="IN" />',
        '<meta name="geo.placename" content="India" />',
        '<meta property="og:type" content="website" />',
        '<meta property="og:site_name" content="%s" />' % esc(cfg["site_name"]),
        '<meta property="og:title" content="%s" />' % og_title,
        '<meta property="og:description" content="%s" />' % og_desc,
        '<meta property="og:url" content="%s" />' % base,
        '<meta property="og:image" content="%s" />' % img,
        '<meta property="og:image:width" content="%s" />' % cfg.get("og_image_width", 1200),
        '<meta property="og:image:height" content="%s" />' % cfg.get("og_image_height", 630),
        '<meta property="og:image:alt" content="%s" />' % img_alt,
        '<meta property="og:locale" content="%s" />' % cfg.get("locale", "en_IN"),
        '<meta name="twitter:card" content="summary_large_image" />',
        '<meta name="twitter:title" content="%s" />' % og_title,
        '<meta name="twitter:description" content="%s" />' % og_desc,
        '<meta name="twitter:image" content="%s" />' % img,
    ]
    if cfg.get("twitter_handle"):
        lines.append('<meta name="twitter:site" content="%s" />' % esc(cfg["twitter_handle"]))
    lines += [
        '<link rel="icon" href="assets/img/favicon.ico" sizes="any" />',
        '<link rel="icon" type="image/svg+xml" href="assets/img/favicon.svg" />',
        '<link rel="apple-touch-icon" href="assets/img/apple-touch-icon.png" />',
        '<link rel="manifest" href="site.webmanifest" />',
    ]
    return "\n" + "\n".join(lines) + "\n"


# ---------------------------------------------------------------- robots + sitemap + manifest

def write_robots(cfg, env):
    base = cfg["base_url"]
    if env == "production":
        body = ("# Mosquito Watch\n"
                "User-agent: *\n"
                "Allow: /\n\n"
                "Sitemap: %ssitemap.xml\n" % base)
    else:
        body = ("# Mosquito Watch -- STAGING origin (e.g. github.io).\n"
                "# Disallow keeps the staging origin out of search; the canonical tag points every page at the\n"
                "# production URL. In production, indexing is governed by the pharmeasy.in apex robots.txt, which\n"
                "# must allow /research/mosquito-watch-2026/ and reference the sitemap below.\n"
                "User-agent: *\n"
                "Disallow: /\n\n"
                "Sitemap: %ssitemap.xml\n" % base)
    with open(os.path.join(ROOT, "robots.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(body)


def write_sitemap(cfg, lastmod):
    base = cfg["base_url"]
    body = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            "  <url>\n"
            "    <loc>%s</loc>\n"
            "    <lastmod>%s</lastmod>\n"
            "    <changefreq>daily</changefreq>\n"
            "    <priority>1.0</priority>\n"
            "  </url>\n"
            "</urlset>\n" % (base, lastmod or ""))
    with open(os.path.join(ROOT, "sitemap.xml"), "w", encoding="utf-8", newline="\n") as f:
        f.write(body)


def write_manifest(cfg):
    manifest = {
        "name": cfg["site_name"] + " by " + cfg["brand"],
        "short_name": cfg["site_name"],
        "description": cfg["description"],
        "start_url": ".",
        "scope": ".",
        "display": "standalone",
        "background_color": "#f4f6f8",
        "theme_color": cfg.get("theme_color", "#10847E"),
        "lang": cfg.get("language", "en-IN"),
        "icons": [
            {"src": "assets/img/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "assets/img/icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "assets/img/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }
    with open(os.path.join(ROOT, "site.webmanifest"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")


# ---------------------------------------------------------------- main

def load(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return json.load(f)


def main():
    env = (os.environ.get("SITE_ENV") or "staging").strip().lower()
    cfg = load("config/site.json")
    l1 = load("data/data.json")
    l2 = load("data/fever_signal.json")
    season = load("data/confirmed_season.json")
    try:
        latest = load("data/confirmed_cases.json")
    except FileNotFoundError:
        latest = {}

    cities = l1.get("cities") or []

    index_path = os.path.join(ROOT, "index.html")
    with open(index_path, encoding="utf-8") as f:
        html = f.read()

    # --- head: meta + JSON-LD
    html = set_marker(html, "seo", head_meta(cfg))
    html = set_marker(html, "jsonld", "\n" + jsonld_script(build_jsonld(cfg, l1, l2, season, latest)) + "\n")

    # --- pre-rendered content blocks (mirror the JS templates)
    html = set_marker(html, "keystats", render_keystats(l1, l2))
    html = set_marker(html, "faq", render_faq_html())
    html = set_inner_by_id(html, "summary-chips", render_summary_chips(cities))
    html = set_inner_by_id(html, "level-guide", render_level_guide())
    html = set_inner_by_id(html, "risk-body", render_risk_rows(cities))
    html = set_inner_by_id(html, "l3-cards", render_l3_cards(season))
    html = set_inner_by_id(html, "l3-thead", render_l3_thead(season))
    html = set_inner_by_id(html, "l3-body", render_l3_rows(season))

    # --- small text containers (freshness / attribution)
    last_iso = freshest(l1, l2, season, latest)
    html = set_inner_by_id(html, "meta", "<div><b>Last updated:</b> %s</div>" % esc(pretty_date(last_iso)))
    asof = (cities[0].get("inputs") or {}).get("as_of_date") if cities else None
    html = set_inner_by_id(html, "asof-tag", ("weather as of %s" % esc(asof)) if asof else "", required=False)
    weeks_parsed = (season.get("season_totals") or {}).get("weeks_parsed") or len(season.get("weeks") or [])
    html = set_inner_by_id(
        html, "l3-asof",
        "%s, %d weekly reports, built %s" % (esc(season.get("season_label", "season")), weeks_parsed, esc(pretty_date(season.get("generated_at")))),
        required=False,
    )
    total_cases = sum((season.get("totals_by_disease") or {}).get(d["key"], {}).get("cases", 0) or 0
                      for d in (season.get("diseases") or []))
    html = set_inner_by_id(
        html, "l3-denominator",
        "Drawn from %d weekly IDSP reports; the diseases we follow saw %s confirmed cases across the 2025 monsoon."
        % (weeks_parsed, thousands(total_cases)),
        required=False,
    )
    html = set_inner_by_id(
        html, "footer-attr",
        "Weather for Layer 1 comes from %s. Map tiles &copy; OpenStreetMap contributors and &copy; CARTO."
        % esc(l1.get("attribution", "Open-Meteo")),
        required=False,
    )
    # JS-only chart: a visually-hidden text fallback for no-JS / screen readers
    headline = next((d["label"] for d in (season.get("diseases") or []) if d.get("key") == season.get("headline_disease")), "dengue")
    html = set_inner_by_id(
        html, "l3-chart",
        "<p class='vh'>A weekly chart of confirmed %s cases across India through the %s monsoon season. "
        "The full weekly data is in data/confirmed_season.json.</p>" % (esc(headline), esc(season.get("season_year", "2025"))),
        required=False,
    )

    # --- reveal the lazy-sec sections without JS
    html = set_body_prerendered(html)

    with open(index_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)

    write_robots(cfg, env)
    write_sitemap(cfg, iso_date(last_iso) or iso_date(l1.get("generated_at")))
    write_manifest(cfg)

    print("build_site: ok (env=%s)" % env)
    print("  index.html pre-rendered: %d cities, %d L3 states, FAQ x%d, JSON-LD graph x%d"
          % (len(cities), len(season.get("by_state") or []), len(FAQ_ITEMS), 7))
    print("  wrote robots.txt, sitemap.xml (lastmod %s), site.webmanifest" % (iso_date(last_iso) or "n/a"))


if __name__ == "__main__":
    sys.exit(main())
