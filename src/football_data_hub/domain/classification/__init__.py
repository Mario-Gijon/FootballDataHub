"""Cálculo local de clasificaciones deportivas, sin navegador ni red."""

from .engine import calculate_standings
from .models import (
    CalculatedStanding,
    CalculatedTable,
    ClassificationFilter,
    MatchResult,
    Team,
)

__all__ = [
    "CalculatedStanding",
    "CalculatedTable",
    "ClassificationFilter",
    "MatchResult",
    "Team",
    "calculate_standings",
]
