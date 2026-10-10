"""Modelos semánticos de la pestaña Estadísticas de BDFutbol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from football_data_hub.domain.statistics.models import RecordKind, StreakKind

StatisticsScope = Literal["competition"]


@dataclass(frozen=True, slots=True)
class PublishedCompetitionSummary:
    teams: int
    matches: int
    home_wins: int
    away_wins: int
    draws: int
    goals: int
    goals_per_match: float
    yellow_cards: int
    yellow_cards_per_match: float
    expulsions: int
    expulsions_per_match: float


@dataclass(frozen=True, slots=True)
class PublishedPenaltyStatistics:
    penalties_awarded: int
    penalties_scored: int
    penalties_missed: int
    source_labels: tuple[str, str, str] = (
        "Penaltis pitados",
        "Penaltis marcados",
        "Penaltis fallados",
    )


@dataclass(frozen=True, slots=True)
class PublishedMatchRecord:
    kind: RecordKind
    measure: int
    match_id: str
    home_goals: int
    away_goals: int
    source_url: str


@dataclass(frozen=True, slots=True)
class PublishedStreak:
    kind: StreakKind
    team_name: str
    match_count: int
    matchday_start: int
    matchday_end: int


@dataclass(frozen=True, slots=True)
class PublishedRoundPoint:
    matchday: int
    goals: int | None
    yellow_cards: int | None
    red_cards: int | None


@dataclass(frozen=True, slots=True)
class PublishedChart:
    library: str
    category_field: str
    graph_fields: tuple[tuple[str, str], ...]
    points: tuple[PublishedRoundPoint, ...]


@dataclass(frozen=True, slots=True)
class ParsedBDFutbolStatistics:
    source_url: str
    competition: str
    season: str
    group: str
    source_summary: PublishedCompetitionSummary
    exclusive_penalties: PublishedPenaltyStatistics
    match_records: tuple[PublishedMatchRecord, ...]
    streaks: tuple[PublishedStreak, ...]
    chart: PublishedChart
