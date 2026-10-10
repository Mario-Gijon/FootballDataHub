"""Cálculo local de clasificaciones deportivas, sin navegador ni red."""

from .engine import calculate_standings
from .models import (
    CalculatedStanding,
    CalculatedTable,
    ClassificationFilter,
    MatchResult,
    Team,
)
from .results import (
    MatchListEntry,
    ResultsMatrix,
    ResultsMatrixCell,
    ResultsMatrixRow,
    build_group2_results_matrix,
    build_results_matrix,
    list_competition_results,
    list_group2_results,
)

__all__ = [
    "CalculatedStanding",
    "CalculatedTable",
    "ClassificationFilter",
    "MatchResult",
    "MatchListEntry",
    "ResultsMatrix",
    "ResultsMatrixCell",
    "ResultsMatrixRow",
    "Team",
    "build_group2_results_matrix",
    "build_results_matrix",
    "calculate_standings",
    "list_competition_results",
    "list_group2_results",
]
