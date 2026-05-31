"""Parse an IDSP weekly outbreak PDF into a normalized WeeklyReport.

Why coordinate-based and not pdfplumber's table grid:
  IDSP weekly reports are the genuinely fiddly part of this whole project. Their
  outbreak table runs across ~25 pages, the header is NOT repeated on every page,
  comment cells wrap over many lines, and pdfplumber's line-detection reports a
  DIFFERENT column count page to page (12 here, 14 there) -- so cell indices drift
  and break naive parsing. Instead we work from word x-positions: the table's
  column x-bands are stable across the document, so we read the header once to fix
  the bands, bin every word into a column by its x-centre, and anchor each outbreak
  on its Unique ID (State/District/Year/Week/number). Wrapped state/disease names
  are stitched back from the immediately-following lines; header/footer/section
  lines are skipped. This is deliberately defensive: when it cannot find the
  expected structure it returns little/nothing, and the orchestrator's mandatory
  data-quality guard then ABORTS rather than publishing garbage.

pdfplumber is imported lazily so importing this module (and the sample source)
never requires it.
"""
from __future__ import annotations

import io
import re

try:
    from .base import Outbreak, WeeklyReport
except ImportError:  # run directly as a script (python src/idsp/parse.py), not as a package
    import os as _os
    import sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    from base import Outbreak, WeeklyReport

# Outbreak Unique ID, e.g. "KL/KOT/2026/15/595" = State/District/Year/Week/number.
# Unanchored + searched (not matched) within the ID cell, because some weeks add a
# leading "S.No." serial column whose number shares the cell ("1 KL/KOT/2026/15/595").
ID_RE = re.compile(r"[A-Z]{2}/[A-Z]{2,5}/(20\d\d)/(\d{1,2})/\d{1,4}")

# Column x-CENTRES read from a real header (page 3 of the 2026-W15 report). Used
# only as a fallback when a header cannot be located on the PDF; normally we read
# the live header and override these. Order matters (ascending x).
DEFAULT_CENTERS = [
    ("id", 80.0), ("state", 178.0), ("district", 252.0), ("disease", 335.0),
    ("cases", 396.0), ("deaths", 432.0), ("date_start", 480.0),
    ("date_report", 534.0), ("status", 597.0), ("comments", 690.0),
]

# Header keyword -> column name. Each header word's x-centre fixes that column.
# Matching is loose (substring) so layout drift between weeks is tolerated: some
# reports write "State-UT", others "State/UT" or just "State"; some add a leading
# "S.No." column (handled by searching the ID within its cell, see ID_RE).
_HEADER_KEYS = [
    ("unique", "id"), ("state", "state"), ("district", "district"),
    ("illness", "disease"), ("disease", "disease"), ("cases", "cases"),
    ("deaths", "deaths"), ("outbreak", "date_start"), ("reporting", "date_report"),
    ("status", "status"), ("comments", "comments"),
]

# Lines we never treat as outbreak data or as name continuation.
_SKIP_SUBSTRINGS = (
    "unique id", "name of", "disease- illness", "disease-illness", "no. of",
    "date of", "current status", "comments- action", "comments-action",
    "disease outbreaks", "weekly outbreak report", "reporting status",
    "integrated disease", "national centre", "www.idsp", "sham nath marg",
)
_PAGE_FOOTER_RE = re.compile(r"^\d{1,3}\s*\|\s*page", re.IGNORECASE)

_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1)}


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace(" ", " ")).strip()


def _state_key(s: str) -> str:
    """Space/punctuation-insensitive key for matching messy PDF state text to the
    config state list. Drops the joining word 'and'/'&' so 'Jammu & Kashmir' and
    'Jammu and Kashmir' collide, but keeps 'Andhra' intact (it is not the token
    'and'). Also fixes mid-word wraps like 'Chhattisg arh' -> 'chhattisgarh'."""
    toks = [t for t in re.split(r"[^a-z]+", s.lower()) if t and t != "and"]
    return "".join(toks)


def build_state_normalizer(config: dict):
    states = config.get("states", [])
    by_key = {}
    by_idsp = {}
    for s in states:
        by_key[_state_key(s["name"])] = s["name"]
        if s.get("idsp"):
            by_idsp[s["idsp"].upper()] = s["name"]

    def normalize(text: str, idsp_prefix: str = "") -> str:
        k = _state_key(text)
        if k in by_key:
            return by_key[k]
        # Loose containment (handles a trailing stray word the parser tacked on).
        for key, name in by_key.items():
            if k and (k.startswith(key) or key.startswith(k)) and abs(len(k) - len(key)) <= 3:
                return name
        # Last resort: the 2-letter IDSP prefix from the outbreak ID (low trust;
        # IDSP's own prefixes are occasionally inconsistent, so text wins above).
        if idsp_prefix and idsp_prefix.upper() in by_idsp:
            return by_idsp[idsp_prefix.upper()]
        return _clean(text)

    return normalize


def build_disease_classifier(config: dict):
    targets = config.get("diseases", [])

    def classify(text: str):
        t = _clean(text).lower()
        for d in targets:
            if any(m.lower() in t for m in d.get("match", [])):
                return d["key"], d["label"]
            # match_all: any group whose every token is present (order-free).
            for group in d.get("match_all", []):
                if all(tok.lower() in t for tok in group):
                    return d["key"], d["label"]
        return "other", _clean(text)

    return classify


def _columns_from_header(words):
    """Find header words and return ordered [(name, center)] column bands, or
    None if this page has no recognizable header band."""
    found: dict[str, float] = {}
    for w in words:
        low = w["text"].strip().lower()
        for kw, col in _HEADER_KEYS:
            if kw in low and col not in found:
                found[col] = (w["x0"] + w["x1"]) / 2.0
    # Need enough anchors to trust it (id + the numeric columns at least).
    if not ({"id", "cases", "deaths"} <= set(found)):
        return None
    cols = sorted(found.items(), key=lambda kv: kv[1])
    return cols


def _col_of(xc: float, bounds):
    for name, lo, hi in bounds:
        if lo <= xc < hi:
            return name
    return bounds[-1][0]


def _bounds(centers):
    """Turn ordered [(name, center)] into [(name, lo, hi)] bands at midpoints."""
    out = []
    for i, (name, c) in enumerate(centers):
        lo = 0.0 if i == 0 else (centers[i - 1][1] + c) / 2.0
        hi = 1e9 if i == len(centers) - 1 else (centers[i + 1][1] + c) / 2.0
        out.append((name, lo, hi))
    return out


def _visual_lines(words, tol: float = 4.0):
    """Group words into visual lines by their `top` y-coordinate."""
    out = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if out and abs(w["top"] - out[-1]["top"]) <= tol:
            out[-1]["words"].append(w)
        else:
            out.append({"top": w["top"], "words": [w]})
    return out


def _row_cells(line_words, bounds):
    cells: dict[str, list] = {name: [] for name, _, _ in bounds}
    for w in sorted(line_words, key=lambda w: w["x0"]):
        xc = (w["x0"] + w["x1"]) / 2.0
        cells[_col_of(xc, bounds)].append(w["text"])
    return {k: _clean(" ".join(v)) for k, v in cells.items()}


def _is_skip_line(text: str) -> bool:
    low = text.lower()
    if _PAGE_FOOTER_RE.match(low):
        return True
    return any(s in low for s in _SKIP_SUBSTRINGS)


def _first_int(s: str):
    m = re.search(r"\d+", s or "")
    return int(m.group()) if m else None


def _norm_status(s: str) -> str:
    """Map the parsed status cell to IDSP's small fixed vocabulary. The 'reported
    late' section on later pages has a slightly offset column layout, so a stray
    comment word can land in the status band; anything that is not a recognizable
    status becomes blank rather than showing garbage."""
    low = (s or "").lower()
    if "control" in low:
        return "Under Control"
    if "surveillance" in low:
        return "Under Surveillance"
    if low.startswith("under"):
        return _clean(s).title()
    return ""


def _iso_date(daytext: str) -> str:
    """'6th April 2026' -> '2026-04-06' (best effort; '' if unparseable)."""
    m = re.search(r"(\d{1,2})\w*\s+([A-Za-z]+)\s+(20\d\d)", daytext or "")
    if not m:
        return ""
    day, mon, year = int(m.group(1)), m.group(2).lower(), int(m.group(3))
    if mon not in _MONTHS:
        return ""
    return f"{year:04d}-{_MONTHS[mon]:02d}-{day:02d}"


def _extract_report_week(first_pages_text: str):
    """Return (week:int|None, year:int|None, week_label, period_label, start, end)."""
    txt = _clean(first_pages_text)
    week = None
    wm = re.search(r"(\d{1,2})(?:st|nd|rd|th)\s+Week", txt, re.IGNORECASE)
    if wm:
        week = int(wm.group(1))
    period_label, start, end = "", "", ""
    pm = re.search(r"\(\s*(\d{1,2}\w*\s+[A-Za-z]+\s+20\d\d)\s+to\s+(\d{1,2}\w*\s+[A-Za-z]+\s+20\d\d)\s*\)", txt)
    if pm:
        period_label = f"{_clean(pm.group(1))} to {_clean(pm.group(2))}"
        start, end = _iso_date(pm.group(1)), _iso_date(pm.group(2))
    year = None
    ym = re.search(r"Week\s+(20\d\d)|20\d\d", end or txt)
    if end[:4].isdigit():
        year = int(end[:4])
    elif ym:
        year = int(re.search(r"20\d\d", ym.group()).group())
    label = ""
    if week is not None:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(week if week < 20 else week % 10, "th")
        label = f"{week}{suffix} Week" + (f", {year}" if year else "")
    return week, year, label, period_label, start, end


def parse_pdf(pdf, config: dict) -> WeeklyReport:
    """Parse an IDSP weekly PDF (a path str or raw bytes) into a WeeklyReport.

    Caller is responsible for setting source_pdf_url / listing_url afterward.
    Raises RuntimeError if the PDF cannot be opened at all (a hard failure the
    orchestrator surfaces); a structurally-empty parse returns a report with no
    outbreaks, which the guard then rejects.
    """
    try:
        import pdfplumber  # lazy: only the live/fixture path needs it
    except ImportError as err:  # pragma: no cover
        raise RuntimeError(
            "pdfplumber is required to parse IDSP PDFs (pip install pdfplumber), "
            "or use --source sample for the dependency-free synthetic source."
        ) from err

    opener = io.BytesIO(pdf) if isinstance(pdf, (bytes, bytearray)) else pdf
    normalize_state = build_state_normalizer(config)
    classify = build_disease_classifier(config)

    outbreaks: list[Outbreak] = []
    notes: list[str] = []
    centers = DEFAULT_CENTERS
    have_header = False
    header_text_parts: list[str] = []

    with pdfplumber.open(opener) as doc:
        page_count = len(doc.pages)
        for pi, page in enumerate(doc.pages):
            words = page.extract_words(use_text_flow=False)
            if pi < 2:
                header_text_parts.append(page.extract_text() or "")
            # Lock the column bands from the first real header we see, then reuse
            # them for every page (the table's x-layout is stable document-wide,
            # even though pdfplumber's per-page cell grid is not).
            if not have_header:
                hc = _columns_from_header(words)
                if hc:
                    centers, have_header = hc, True
            bounds = _bounds(centers)

            cur: Outbreak | None = None    # outbreak currently accreting wrapped lines
            lines_since_id = 0
            for line in _visual_lines(words):
                cells = _row_cells(line["words"], bounds)
                joined = _clean(" ".join(cells.values()))
                if not joined:
                    continue
                if _is_skip_line(joined):
                    cur = None  # a header / section-title / footer ends continuation
                    continue
                idcell = cells.get("id", "")
                m = ID_RE.search(idcell)
                if m:
                    cur = Outbreak(
                        disease_key="", disease="", state="",
                        district=cells.get("district", ""),
                        cases=_first_int(cells.get("cases", "")),
                        deaths=_first_int(cells.get("deaths", "")),
                        status=cells.get("status", ""),
                        outbreak_id=m.group(0), week=int(m.group(2)), year=int(m.group(1)),
                        raw_disease=cells.get("disease", ""),
                        raw_state=cells.get("state", ""),
                    )
                    outbreaks.append(cur)
                    lines_since_id = 0
                elif cur is not None:
                    lines_since_id += 1
                    # Stitch wrapped state/district/disease names from the next
                    # line or two. Government PDFs wrap a long name mid-word onto
                    # the following line ("Fever with" / "Rash", "Chhattisg" /
                    # "arh"). Those fragments land in the name columns (x < ~360),
                    # while the row's comment prose lives far right (x >= ~640), so
                    # reading only the name columns never pulls comment text in. We
                    # still cap to 2 lines and short, non-numeric fragments as a
                    # belt-and-braces guard against format drift.
                    if lines_since_id <= 2:
                        for col, attr in (("state", "raw_state"), ("district", "district"), ("disease", "raw_disease")):
                            frag = cells.get(col, "")
                            if frag and len(frag.split()) <= 3 and not any(c.isdigit() for c in frag):
                                setattr(cur, attr, _clean(getattr(cur, attr) + " " + frag))
                    # Complete a wrapped status: the ID line often holds just
                    # "Under" with "Surveillance"/"Control" spilling to the next.
                    if lines_since_id == 1 and cur.status.strip().lower() == "under":
                        sfrag = cells.get("status", "")
                        if sfrag and sfrag.isalpha():
                            cur.status = _clean(cur.status + " " + sfrag)

    # Normalize once, now that wrapped fragments are fully stitched.
    for ob in outbreaks:
        ob.state = normalize_state(ob.raw_state, _id_prefix(ob.outbreak_id))
        ob.district = _clean(ob.district)
        ob.disease_key, ob.disease = classify(ob.raw_disease)
        ob.status = _norm_status(ob.status)

    week, year, week_label, period_label, start, end = _extract_report_week("\n".join(header_text_parts))
    if (week is None or year is None) and outbreaks:
        from collections import Counter
        if week is None:
            wk = Counter(o.week for o in outbreaks if o.week)
            if wk:
                week = wk.most_common(1)[0][0]
                notes.append("report week inferred from outbreak IDs (page header not matched)")
        if year is None:
            yc = Counter(o.year for o in outbreaks if o.year)
            if yc:
                year = yc.most_common(1)[0][0]

    return WeeklyReport(
        outbreaks=outbreaks, report_week=week, report_year=year,
        week_label=week_label, period_label=period_label,
        period_start=start, period_end=end, page_count=page_count, notes=notes,
    )


def _id_prefix(outbreak_id: str) -> str:
    return outbreak_id.split("/", 1)[0] if outbreak_id else ""


if __name__ == "__main__":
    # Self-test / regression check against the saved fixture. Run:
    #   python -m idsp.parse        (from src/, with src on sys.path)
    #   python src/idsp/parse.py
    import json
    import os
    import sys

    HERE = os.path.dirname(os.path.abspath(__file__))
    ROOT = os.path.dirname(os.path.dirname(HERE))
    if os.path.join(ROOT, "src") not in sys.path:
        sys.path.insert(0, os.path.join(ROOT, "src"))

    cfg = json.load(open(os.path.join(ROOT, "config", "idsp.json"), encoding="utf-8"))
    fx = os.path.join(ROOT, cfg["fixture_pdf"])
    print(f"Parsing fixture: {fx}")
    rep = parse_pdf(fx, cfg)
    print(f"pages={rep.page_count}  week={rep.week_label!r}  period={rep.period_label!r}")
    print(f"outbreaks={len(rep.outbreaks)}  id_anchors={rep.id_anchor_count}")
    from collections import Counter
    dist = Counter(o.disease for o in rep.outbreaks)
    print("disease distribution:")
    for d, n in dist.most_common():
        print(f"  {n:>2}  {d}")
    print("target outbreaks:")
    for o in rep.outbreaks:
        if o.disease_key != "other":
            print(f"  {o.outbreak_id:<20} {o.state:<20} {o.district:<16} {o.disease:<20} C={o.cases} D={o.deaths}")
