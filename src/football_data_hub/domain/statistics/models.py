"""Modelos del dominio para estadísticas de competición."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

StatisticsContext = Literal["competition"]
RoundCoverage = Literal["complete", "partial", "not_started", "incomplete"]
RecordKind = Literal["largest_home_win", "largest_away_win", "most_goals"]
StreakKind = Literal["winning", "losing", "unbeaten", "winless"]


@dataclass(frozen=True, slots=True)
class CompetitionContext:
    competition: str
    season: str
    group: str

    def __post_init__(self) -> None:
        if not self.competition.strip():
            raise ValueError("competition no puede estar vacío")
        if not self.season.strip():
            raise ValueError("season no puede estar vacío")
        if not self.group.strip():
            raise ValueError("group no puede estar vacío")


@dataclass(frozen=True, slots=True)
class MetricCoverage:
    matches_played: int
    matches_with_value: int
    missing_match_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.matches_played < 0 or self.matches_with_value < 0:
            raise ValueError("Los recuentos de cobertura no pueden ser negativos")
        if self.matches_with_value > self.matches_played:
            raise ValueError("La cobertura no puede superar los partidos disputados")
        if len(self.missing_match_ids) != len(set(self.missing_match_ids)):
            raise ValueError("missing_match_ids no puede contener duplicados")

    @property
    def complete(self) -> bool:
        return self.matches_with_value == self.matches_played


@dataclass(frozen=True, slots=True)
class RoundStatistics:
    matchday: int
    scheduled_matches: int
    played_matches: int
    unplayed_matches: int
    incomplete_matches: int
    coverage: RoundCoverage
    goals: int | None
    yellow_cards: int | None
    red_cards: int | None
    yellow_card_coverage: MetricCoverage
    red_card_coverage: MetricCoverage

    def __post_init__(self) -> None:
        if self.matchday < 1:
            raise ValueError("matchday debe ser positivo")
        if min(
            self.scheduled_matches,
            self.played_matches,
            self.unplayed_matches,
            self.incomplete_matches,
        ) < 0:
            raise ValueError("Los recuentos de jornada no pueden ser negativos")
        if self.played_matches + self.unplayed_matches + self.incomplete_matches != self.scheduled_matches:
            raise ValueError("Los estados de partido deben cubrir los fixtures de la jornada")
        if self.played_matches == 0 and any(
            value is not None for value in (self.goals, self.yellow_cards, self.red_cards)
        ):
            raise ValueError("Una jornada sin partidos disputados no puede tener métricas")


@dataclass(frozen=True, slots=True)
class CompetitionStatistics:
    context: CompetitionContext
    team_count: int
    scheduled_matches: int
    played_matches: int
    unplayed_matches: int
    incomplete_matches: int
    home_wins: int
    away_wins: int
    draws: int
    goals: int | None
    goals_per_match: float | None
    yellow_cards: int | None
    yellow_cards_per_match: float | None
    red_cards: int | None
    red_cards_per_match: float | None
    yellow_card_coverage: MetricCoverage
    red_card_coverage: MetricCoverage
    rounds: tuple[RoundStatistics, ...]

    def __post_init__(self) -> None:
        if self.team_count < 1:
            raise ValueError("team_count debe ser positivo")
        if min(
            self.scheduled_matches,
            self.played_matches,
            self.unplayed_matches,
            self.incomplete_matches,
            self.home_wins,
            self.away_wins,
            self.draws,
        ) < 0:
            raise ValueError("Las estadísticas de competición no pueden ser negativas")
        if self.played_matches != self.home_wins + self.away_wins + self.draws:
            raise ValueError("Cada partido disputado debe ser una victoria o un empate")
        if len({item.matchday for item in self.rounds}) != len(self.rounds):
            raise ValueError("Las jornadas de la serie no pueden repetirse")


@dataclass(frozen=True, slots=True)
class MatchRecord:
    match_id: str
    matchday: int
    home_team_id: int
    away_team_id: int
    home_goals: int
    away_goals: int


@dataclass(frozen=True, slots=True)
class RecordSet:
    kind: RecordKind
    measure: int
    matches: tuple[MatchRecord, ...]

    def __post_init__(self) -> None:
        if self.measure < 0:
            raise ValueError("measure no puede ser negativo")
        if not self.matches:
            raise ValueError("Un récord calculado debe tener al menos un partido")
        if len({item.match_id for item in self.matches}) != len(self.matches):
            raise ValueError("Un mismo partido no puede repetirse en un récord")


@dataclass(frozen=True, slots=True)
class StreakRecord:
    team_id: int
    kind: StreakKind
    match_count: int
    matchday_start: int
    matchday_end: int
    match_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.team_id <= 0 or self.match_count < 1:
            raise ValueError("Una racha requiere equipo y partidos válidos")
        if self.matchday_start > self.matchday_end:
            raise ValueError("El inicio de una racha no puede superar el final")
        if len(self.match_ids) != self.match_count:
            raise ValueError("match_ids debe enumerar todos los partidos de la racha")
        if len(set(self.match_ids)) != len(self.match_ids):
            raise ValueError("Una racha no puede contar dos veces un mismo partido")


@dataclass(frozen=True, slots=True)
class CompetitionRecords:
    match_records: tuple[RecordSet, ...]
    streaks: tuple[StreakRecord, ...]


@dataclass(frozen=True, slots=True)
class CompetitionStatisticsReport:
    statistics: CompetitionStatistics
    records: CompetitionRecords
