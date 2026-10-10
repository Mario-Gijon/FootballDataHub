"""Contratos de dominio para equipos, partidos y clasificaciones calculadas."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

ClassificationType = Literal["general", "local", "visitor"]
RangeType = Literal["all", "dates", "rounds"]
MatchStatus = Literal["played", "unplayed", "incomplete"]
UnplayedState = Literal["scheduled", "result_unavailable_at_capture", "unknown"]


@dataclass(frozen=True, slots=True)
class Team:
    team_id: int
    name: str
    team_url: str | None = None
    crest_url: str | None = None

    def __post_init__(self) -> None:
        if self.team_id <= 0:
            raise ValueError("team_id debe ser positivo")
        if not self.name.strip():
            raise ValueError("name no puede estar vacío")


@dataclass(frozen=True, slots=True)
class MatchResult:
    """Resultado de una jornada; un partido sin marcador conserva nulls.

    Venue and referee references are optional enrichment from a source match
    row. They do not affect classification calculations.
    """

    match_id: str
    matchday: int
    matchday_date: date | None
    source_match_date: date | None
    home_team_id: int
    away_team_id: int
    home_goals: int | None
    away_goals: int | None
    home_yellow_cards: int | None
    away_yellow_cards: int | None
    home_red_cards: int | None
    away_red_cards: int | None
    status: MatchStatus
    unplayed_state: UnplayedState | None
    postponed_by_source_rule: bool | None
    source_match_url: str | None = None
    source_references: tuple[str, ...] = ()
    source_fields: dict[str, str] = field(default_factory=dict)
    stadium_id: str | None = None
    stadium_name: str | None = None
    stadium_url: str | None = None
    referee_id: str | None = None
    referee_name: str | None = None
    referee_url: str | None = None

    def __post_init__(self) -> None:
        if not self.match_id.strip():
            raise ValueError("match_id no puede estar vacío")
        if not 1 <= self.matchday <= 38:
            raise ValueError("matchday debe estar entre 1 y 38")
        if self.home_team_id == self.away_team_id:
            raise ValueError("Un equipo no puede jugar contra sí mismo")
        if self.status == "played":
            if self.home_goals is None or self.away_goals is None:
                raise ValueError("Un partido disputado requiere ambos marcadores")
            if self.home_goals < 0 or self.away_goals < 0:
                raise ValueError("Los goles de un partido disputado no pueden ser negativos")
        elif self.status == "unplayed":
            if self.home_goals is not None or self.away_goals is not None:
                raise ValueError("Un partido sin disputar no puede contener marcador")
            if self.unplayed_state not in {
                "scheduled",
                "result_unavailable_at_capture",
                "unknown",
            }:
                raise ValueError("Un partido sin disputar requiere unplayed_state")
        elif self.status != "incomplete":
            raise ValueError(f"Estado de partido no admitido: {self.status}")
        elif self.unplayed_state is not None:
            raise ValueError("Un partido incompleto no puede tener unplayed_state")
        if self.status == "played" and self.unplayed_state is not None:
            raise ValueError("Un partido disputado no puede tener unplayed_state")
        for field_name in (
            "home_goals",
            "away_goals",
            "home_yellow_cards",
            "away_yellow_cards",
            "home_red_cards",
            "away_red_cards",
        ):
            value = getattr(self, field_name)
            if value is not None and value < 0:
                raise ValueError(f"{field_name} no puede ser negativo")


@dataclass(frozen=True, slots=True)
class ClassificationFilter:
    classification_type: ClassificationType = "general"
    matchday_cap: int | None = None
    include_postponed: bool = True
    range_type: RangeType = "all"
    date_start: date | None = None
    date_end: date | None = None
    round_start: int | None = None
    round_end: int | None = None

    def __post_init__(self) -> None:
        if self.classification_type not in {"general", "local", "visitor"}:
            raise ValueError("classification_type debe ser general, local o visitor")
        if self.matchday_cap is not None and not 1 <= self.matchday_cap <= 38:
            raise ValueError("matchday_cap debe estar entre 1 y 38")
        if self.range_type not in {"all", "dates", "rounds"}:
            raise ValueError("range_type debe ser all, dates o rounds")
        if self.range_type == "dates":
            if self.date_start is None or self.date_end is None:
                raise ValueError("El rango de fechas requiere ambos límites")
            if self.date_start > self.date_end:
                raise ValueError("date_start no puede ser posterior a date_end")
            if self.round_start is not None or self.round_end is not None:
                raise ValueError("Un rango de fechas no admite límites de jornada")
        elif self.date_start is not None or self.date_end is not None:
            raise ValueError("Los límites de fecha solo se usan con range_type=dates")
        if self.range_type == "rounds":
            if self.round_start is None or self.round_end is None:
                raise ValueError("El rango de jornadas requiere ambos límites")
            if not 1 <= self.round_start <= self.round_end <= 38:
                raise ValueError("El rango debe cumplir 1 <= inicio <= fin <= 38")
        elif self.round_start is not None or self.round_end is not None:
            raise ValueError("Los límites de jornada solo se usan con range_type=rounds")


@dataclass(frozen=True, slots=True)
class CalculatedStanding:
    team: Team
    position: int
    points: int
    matches_played: int
    wins: int
    draws: int
    losses: int
    goals_for: int
    goals_against: int
    yellow_cards: int | None
    red_cards: int | None
    goal_difference: int
    disciplinary_score: int | None


@dataclass(frozen=True, slots=True)
class CalculatedTable:
    source_capture_id: str | None
    source_snapshot: str | None
    algorithm_version: str
    classification_type: ClassificationType
    selected_matchday: int
    selected_matchday_date: date | None
    include_postponed: bool
    range_type: RangeType
    date_start: date | None
    date_end: date | None
    round_start: int | None
    round_end: int | None
    matches_available: int
    matches_counted: int
    unplayed_matches_skipped: int
    incomplete_matches_skipped: int
    rows: tuple[CalculatedStanding, ...]
    warnings: tuple[str, ...] = ()
