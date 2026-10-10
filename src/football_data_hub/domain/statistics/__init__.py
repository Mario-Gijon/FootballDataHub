"""Estadísticas generales de competición calculadas sin dependencias externas."""

from .engine import STATISTICS_ENGINE_VERSION, calculate_competition_statistics
from .models import CompetitionContext, CompetitionStatistics

__all__ = [
    "STATISTICS_ENGINE_VERSION",
    "CompetitionContext",
    "CompetitionStatistics",
    "calculate_competition_statistics",
]
