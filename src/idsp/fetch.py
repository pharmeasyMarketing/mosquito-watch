"""IDSP discovery + download (stage 1 of the live source).

You CANNOT guess the newest week's PDF URL -- IDSP file names are opaque hashes
(e.g. .../l892s/97194154481779188517.pdf). So we:
  1. fetch the Weekly Outbreaks listing page,
  2. parse its YEAR | WEEKS table (each year is a row; the week links sit in
     order inside the year's cell, so the LAST link of the newest-year row is the
     newest week), and
  3. download that PDF -- handling BOTH hosts the listing mixes: the IDSP server
     and Google Drive share links.

Stdlib only (regex HTML scan, no bs4) via the shared httputil helpers, so
discovery stays dependency-free; only the PDF *parse* step needs pdfplumber.
Everything raises loudly on failure so the orchestrator's guard can abort rather
than publish nothing-or-garbage.
"""
from __future__ import annotations

import re
import urllib.parse

from httputil import get_bytes, get_text  # stdlib helpers (src/ is on sys.path)

_TR_RE = re.compile(r"<tr\b.*?</tr>", re.IGNORECASE | re.DOTALL)
_YEAR_RE = re.compile(r"<strong>\s*(20\d\d)\s*</strong>", re.IGNORECASE)
_ANCHOR_RE = re.compile(r'<a\b([^>]*)>(.*?)</a>', re.IGNORECASE | re.DOTALL)
_HREF_RE = re.compile(r'href\s*=\s*"([^"]+)"', re.IGNORECASE)
_TITLE_RE = re.compile(r'title\s*=\s*"([^"]*)"', re.IGNORECASE)
_WEEKNO_RE = re.compile(r"(\d{1,2})\s*(?:st|nd|rd|th)?\s*week", re.IGNORECASE)


def _is_pdf_link(href: str) -> bool:
    h = href.lower()
    return h.endswith(".pdf") or "drive.google.com" in h or "/writereaddata/" in h


def gdrive_direct(url: str) -> str:
    """Turn a Google Drive share URL into a direct-download URL.

    Handles /file/d/<id>/view and ...open?id=<id> and ...uc?id=<id> forms. IDSP
    PDFs are small (~1-2 MB) so the plain uc?export=download URL returns the file
    without the large-file virus-scan confirmation dance.
    """
    m = re.search(r"/d/([A-Za-z0-9_-]{20,})", url) or re.search(r"[?&]id=([A-Za-z0-9_-]{20,})", url)
    if m:
        return f"https://drive.google.com/uc?export=download&id={m.group(1)}"
    return url


def _anchors_in_row(tr: str) -> list[tuple[str, str]]:
    """(href, title) for every weekly-PDF link in a YEAR row, in document order."""
    anchors = []
    for attrs, _text in _ANCHOR_RE.findall(tr):
        hm = _HREF_RE.search(attrs)
        if not hm:
            continue
        href = hm.group(1).strip()
        if not _is_pdf_link(href):
            continue
        tm = _TITLE_RE.search(attrs)
        anchors.append((href, tm.group(1) if tm else ""))
    return anchors


def _year_rows(html: str) -> dict[int, list[tuple[str, str]]]:
    """Map each year on the listing to its ordered list of (href, title) weeks."""
    out: dict[int, list[tuple[str, str]]] = {}
    for tr in _TR_RE.findall(html):
        ym = _YEAR_RE.search(tr)
        if not ym:
            continue
        anchors = _anchors_in_row(tr)
        if anchors:
            out[int(ym.group(1))] = anchors
    return out


def _week_of(anchors: list, idx: int, title: str) -> int:
    """Week number = link position in the row (1-based), cross-checked against the
    title text (titles occasionally carry a copy-paste typo, so position wins
    unless the title is within 1)."""
    week = idx + 1
    tm = _WEEKNO_RE.search(title)
    if tm and abs(int(tm.group(1)) - week) <= 1:
        week = int(tm.group(1))
    return week


def discover_latest(listing_url: str, insecure: bool = False) -> dict:
    """Return {pdf_url, year, week, week_label, host} for the newest weekly report.

    Raises RuntimeError if the listing page has no recognizable YEAR/WEEKS table
    (a likely sign the site was redesigned -- fail loudly, don't guess).
    """
    rows = _year_rows(get_text(listing_url, insecure=insecure))
    if not rows:
        raise RuntimeError(
            f"No weekly-report links found on the IDSP listing page ({listing_url}). "
            "The page layout may have changed -- discovery needs the YEAR/WEEKS table."
        )
    year = max(rows)
    anchors = rows[year]
    idx = len(anchors) - 1  # newest week = last link in the newest-year row
    href, title = anchors[idx]
    week = _week_of(anchors, idx, title)
    pdf_url = urllib.parse.urljoin(listing_url, href)
    host = "google-drive" if "drive.google.com" in pdf_url.lower() else "idsp-server"
    return {
        "pdf_url": pdf_url, "year": year, "week": week,
        "week_label": f"{week}{_ordinal(week)} Week, {year}", "host": host,
    }


def discover_year(listing_url: str, year: int, insecure: bool = False) -> list[dict]:
    """Return every weekly report for `year` as a list of
    {week, pdf_url, week_label, host}, ordered by week. Raises if the year is not
    on the listing (fail loudly rather than silently returning nothing)."""
    rows = _year_rows(get_text(listing_url, insecure=insecure))
    if year not in rows:
        raise RuntimeError(
            f"Year {year} not found on the IDSP listing page ({listing_url}). "
            f"Years present: {', '.join(str(y) for y in sorted(rows, reverse=True))}."
        )
    out = []
    for idx, (href, title) in enumerate(rows[year]):
        week = _week_of(rows[year], idx, title)
        out.append({
            "week": week,
            "pdf_url": urllib.parse.urljoin(listing_url, href),
            "week_label": f"{week}{_ordinal(week)} Week, {year}",
            "host": "google-drive" if "drive.google.com" in href.lower() else "idsp-server",
        })
    return out


def download_pdf(url: str, insecure: bool = False) -> bytes:
    """Download a weekly PDF from either host; verify it really is a PDF.

    Google Drive can answer a direct-download with an HTML interstitial instead
    of the file; we detect that (no %PDF header) and fail loudly rather than
    handing HTML to the parser.
    """
    fetch_url = gdrive_direct(url) if "drive.google.com" in url.lower() else url
    data = get_bytes(fetch_url, insecure=insecure)
    if data[:5] != b"%PDF-":
        head = data[:200].decode("latin-1", "replace").replace("\n", " ")
        raise RuntimeError(
            f"Downloaded content from {fetch_url} is not a PDF (no %PDF header). "
            f"First bytes: {head!r}. If this is a Google Drive link, the file may "
            "require confirmation or be access-restricted."
        )
    return data


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
