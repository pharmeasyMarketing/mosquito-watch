"""Trends-provider registry (Layer 2). Mirrors src/providers/__init__.py.

Add a source here and it's instantly selectable by name from the CLI /
TRENDS_PROVIDER env var. The mock is the DEFAULT so the pipeline runs with zero
third-party dependencies and no API key. The real providers keep their extra
requirements out of import time -- pytrends is imported lazily inside its
methods, and serpapi only reads its key when actually called -- so importing
this registry never fails even when those aren't installed or configured.
"""
from __future__ import annotations

from .apify import ApifyTrendsProvider
from .base import RegionInterest, TrendPoint, TrendsProvider
from .mock import MockTrendsProvider
from .pytrends_provider import PyTrendsProvider
from .serpapi import SerpApiTrendsProvider

_REGISTRY = {
    MockTrendsProvider.name: MockTrendsProvider,
    ApifyTrendsProvider.name: ApifyTrendsProvider,
    PyTrendsProvider.name: PyTrendsProvider,
    SerpApiTrendsProvider.name: SerpApiTrendsProvider,
}

DEFAULT_PROVIDER = MockTrendsProvider.name


def available() -> list[str]:
    return sorted(_REGISTRY)


def get_provider(name: str) -> TrendsProvider:
    try:
        return _REGISTRY[name]()
    except KeyError:
        raise SystemExit(
            f"Unknown trends provider '{name}'. Available: {', '.join(available())}"
        )


__all__ = [
    "RegionInterest",
    "TrendPoint",
    "TrendsProvider",
    "get_provider",
    "available",
    "DEFAULT_PROVIDER",
]
