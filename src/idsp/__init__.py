"""IDSP source registry (Layer 3). Mirrors src/trends_providers/__init__.py.

Add a source here and it's instantly selectable by name from the CLI / IDSP_SOURCE
env var. The `sample` (synthetic) source is the DEFAULT so the pipeline runs with
zero third-party dependencies and no network -- exactly like Layer 2's mock. The
real sources keep their heavy requirements (pdfplumber, network) out of import
time: fetch/parse/pdfplumber are imported lazily inside fetch_report(), so
importing this registry never fails even when pdfplumber is absent.

  sample  -> synthetic, deterministic, is_sample=True   (default; no deps, offline)
  fixture -> REAL parser on a saved weekly PDF           (offline regression; needs pdfplumber)
  live    -> discover + download + parse the newest PDF  (production; needs network + pdfplumber)
"""
from __future__ import annotations

from .base import IdspSource, Outbreak, WeeklyReport
from .fixture import FixtureIdspSource
from .live import LiveIdspSource
from .sample import SampleIdspSource

_REGISTRY = {
    SampleIdspSource.name: SampleIdspSource,
    FixtureIdspSource.name: FixtureIdspSource,
    LiveIdspSource.name: LiveIdspSource,
}

DEFAULT_SOURCE = SampleIdspSource.name


def available() -> list[str]:
    return sorted(_REGISTRY)


def get_source(name: str, config: dict) -> IdspSource:
    try:
        return _REGISTRY[name](config)
    except KeyError:
        raise SystemExit(
            f"Unknown IDSP source '{name}'. Available: {', '.join(available())}"
        )


__all__ = [
    "IdspSource",
    "Outbreak",
    "WeeklyReport",
    "get_source",
    "available",
    "DEFAULT_SOURCE",
]
