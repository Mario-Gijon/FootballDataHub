"""Modelos semánticos independientes del DOM de BDFutbol."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

ClassificationType = Literal["general", "local", "visitor"]
RangeType = Literal["all", "dates", "rounds"]
PositionChange = Literal["up", "down", "same"]
SportsZone = Literal["direct_promotion", "promotion", "stay", "relegation"]


@dataclass(frozen=True, slots=True)
class ClassificationRequest:
    classification_type: ClassificationType = "general"
    matchday: int | None = None
    include_postponed: bool = True
    range_type: RangeType = "all"
    date_start: date | None = None
    date_end: date | None = None
    round_start: int | None = None
    round_end: int | None = None

    def __post_init__(self) -> None:
        if self.classification_type not in {"general", "local", "visitor"}:
            raise ValueError("classification_type debe ser general, local o visitor")
        if self.matchday is not None and not 1 <= self.matchday <= 38:
            raise ValueError("matchday debe estar entre 1 y 38")
        if self.range_type not in {"all", "dates", "rounds"}:
            raise ValueError("range_type debe ser all, dates o rounds")
        if self.range_type == "dates":
            if self.date_start is None or self.date_end is None:
                raise ValueError("El rango de fechas requiere ambos límites")
            if self.date_start > self.date_end:
                raise ValueError("date_start no puede ser posterior a date_end")
        elif self.date_start is not None or self.date_end is not None:
            raise ValueError("Los límites de fecha solo se usan con range_type=dates")
        if self.range_type == "rounds":
            if self.round_start is None or self.round_end is None:
                raise ValueError("El rango de jornadas requiere ambos límites")
            if not 1 <= self.round_start <= self.round_end <= 38:
                raise ValueError("El rango de jornadas debe cumplir 1 <= inicio <= fin <= 38")
            if self.matchday is not None and self.round_end > self.matchday:
                raise ValueError("round_end no puede superar la jornada seleccionada")
        elif self.round_start is not None or self.round_end is not None:
            raise ValueError("Los límites de jornada solo se usan con range_type=rounds")


@dataclass(frozen=True, slots=True)
class ClassificationContext:
    classification_type: ClassificationType
    matchday: int
    matchday_date: str | None
    postponed_policy: Literal["include", "exclude"]
    range_type: RangeType
    range_start_date: str | None = None
    range_end_date: str | None = None
    range_start_round: int | None = None
    range_end_round: int | None = None


@dataclass(frozen=True, slots=True)
class TeamStanding:
    team_id: int
    team_name: str
    team_url: str | None
    crest_url: str | None
    position: int | None
    points: int | None
    matches_played: int | None
    wins: int | None
    draws: int | None
    losses: int | None
    goals_for: int | None
    goals_against: int | None
    yellow_cards: int | None
    red_cards: int | None
    position_change: PositionChange | None
    zone_code: str | None
    sports_zone: SportsZone | None
    position_cell_classes: tuple[str, ...] = ()
    movement_icon_src: str | None = None
    raw_values: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProgressRecord:
    team_id: int
    matchday: int
    matchday_date: str | None
    position: int | None
    points: int | None
    goals_for: int | None
    goals_against: int | None


@dataclass(frozen=True, slots=True)
class ProgressContext:
    classification_type: Literal["general"]
    postponed_policy: Literal["source_defined_unknown"]
    range_type: Literal["all"]
    source_independent_of_standings_filters: bool
    available_through_matchday: int


@dataclass(frozen=True, slots=True)
class ParsedClassification:
    standings: tuple[TeamStanding, ...]
    progress: tuple[ProgressRecord, ...]
    progress_context: ProgressContext
    matchday_dates: dict[int, str]
    played_matchdays: int
    progress_warnings: tuple[str, ...] = ()
