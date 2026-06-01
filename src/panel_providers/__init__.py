"""Panel-provider registry (Layer 3 v1, Fever Panel). Mirrors src/trends_providers/.

Add a source here and it's instantly selectable by name from the CLI / the
PANEL_SOURCE env var. The mock is the DEFAULT so the pipeline runs with zero
third-party dependencies and no credentials, writing clearly-badged sample data
until the real weekly backend feed (googlesheet) is wired.
"""
from __future__ import annotations

from .base import PanelProvider, SeriesPoint
from .googlesheet import GoogleSheetPanelProvider
from .mock import MockPanelProvider

_REGISTRY = {
    MockPanelProvider.name: MockPanelProvider,
    GoogleSheetPanelProvider.name: GoogleSheetPanelProvider,
}

DEFAULT_PROVIDER = MockPanelProvider.name


def available() -> list[str]:
    return sorted(_REGISTRY)


def get_provider(name: str) -> PanelProvider:
    try:
        return _REGISTRY[name]()
    except KeyError:
        raise SystemExit(
            f"Unknown panel provider '{name}'. Available: {', '.join(available())}"
        )


__all__ = [
    "PanelProvider",
    "SeriesPoint",
    "get_provider",
    "available",
    "DEFAULT_PROVIDER",
]
