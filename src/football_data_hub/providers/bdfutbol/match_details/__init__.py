"""Infraestructura local y offline para adquisiciones futuras de partidos."""

from .inventory import (
    MatchDetailInventoryError,
    build_match_detail_inventory,
    load_verified_match_generation,
)

__all__ = [
    "MatchDetailInventoryError",
    "build_match_detail_inventory",
    "load_verified_match_generation",
]
