"""Tiny zero-dependency JSON HTTP helper (stdlib only).

Kept deliberately small so Layer 1 runs with nothing but a Python install --
no pip, no virtualenv -- which matters for a free GitHub Actions cron later.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "VectorRiskIndex/0.1 (Layer1 breeding-favorability; non-commercial demo)"

# Scrub secrets from any URL before it lands in an error message / log.
_SECRET_QS = re.compile(r"((?:token|api_key|apikey|key)=)[^&\s]+", re.IGNORECASE)


def _redact(url: str) -> str:
    return _SECRET_QS.sub(r"\1***", url)


def build_url(base: str, params: dict) -> str:
    """Join a base URL with query params, dropping any whose value is None."""
    clean = {k: v for k, v in params.items() if v is not None}
    return f"{base}?{urllib.parse.urlencode(clean)}"


def get_json(url: str, timeout: int = 30, retries: int = 3, backoff: float = 2.0, headers: dict | None = None) -> dict:
    """GET a URL and parse JSON, with simple linear-backoff retries.

    Raises RuntimeError with the last error if every attempt fails, so callers
    can treat a persistent failure as a hard, loud error (never silent). Any
    secret query param is redacted from the error message.
    """
    hdrs = {"User-Agent": USER_AGENT}
    if headers:
        hdrs.update(headers)
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                return json.loads(resp.read().decode(charset))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as err:
            last_err = err
            if attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
    raise RuntimeError(f"GET failed after {retries} attempts: {_redact(url)}\n  last error: {last_err}")


def _ssl_context(insecure: bool):
    """Default (cert-verifying) context, or an UNVERIFIED one when insecure=True.

    Layer 3 talks to a government host (idsp.mohfw.gov.in) whose TLS chain
    verifies fine today, but state/central gov sites periodically ship an expired
    or misconfigured cert. `insecure=True` (opt-in via IDSP_INSECURE) is the
    documented escape hatch so a cert lapse doesn't block the weekly build --
    callers log loudly when they use it. Returns None to mean "urllib default".
    """
    if not insecure:
        return None
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def get_text(url: str, timeout: int = 40, retries: int = 3, backoff: float = 2.0,
             headers: dict | None = None, insecure: bool = False) -> str:
    """GET a URL and return decoded text (e.g. an HTML listing page).

    Same linear-backoff retry + secret-redaction contract as get_json. A
    browser-ish User-Agent is sent because some gov endpoints 403 the default one.
    """
    hdrs = {"User-Agent": USER_AGENT}
    if headers:
        hdrs.update(headers)
    ctx = _ssl_context(insecure)
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                return resp.read().decode(charset, "replace")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as err:
            last_err = err
            if attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
    raise RuntimeError(f"GET (text) failed after {retries} attempts: {_redact(url)}\n  last error: {last_err}")


def get_bytes(url: str, timeout: int = 90, retries: int = 3, backoff: float = 2.0,
              headers: dict | None = None, insecure: bool = False) -> bytes:
    """GET a URL and return the raw response body (e.g. a PDF download).

    Longer default timeout than the text/JSON helpers because IDSP weekly PDFs
    run to a couple of MB. Same retry + redaction contract.
    """
    hdrs = {"User-Agent": USER_AGENT}
    if headers:
        hdrs.update(headers)
    ctx = _ssl_context(insecure)
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                return resp.read()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as err:
            last_err = err
            if attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
    raise RuntimeError(f"GET (bytes) failed after {retries} attempts: {_redact(url)}\n  last error: {last_err}")


def post_json(url: str, payload: dict, timeout: int = 60, retries: int = 1, backoff: float = 2.0, headers: dict | None = None):
    """POST a JSON body and parse the JSON response.

    Used by the Apify Layer 2 provider to start an actor run. `retries` defaults
    to 1 (no retry): re-POSTing could start a second billable actor run, so
    callers that pay per call should not retry blindly. Secret query params are
    redacted from the error message; prefer passing the token via `headers`
    (Authorization: Bearer ...) so it never touches the URL at all.
    """
    body = json.dumps(payload).encode("utf-8")
    hdrs = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=body, method="POST", headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                return json.loads(resp.read().decode(charset))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as err:
            last_err = err
            if attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
    raise RuntimeError(f"POST failed after {retries} attempt(s): {_redact(url)}\n  last error: {last_err}")
