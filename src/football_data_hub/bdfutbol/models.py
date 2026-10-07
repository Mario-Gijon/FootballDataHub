from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .ids import ProviderRef


@dataclass(frozen=True, slots=True)
class CompetitionContext:
    competition_code: str
    season: str
    group: int
    source_url: str
    provider: str = "bdfutbol"


@dataclass(frozen=True, slots=True)
class StandingRow:
    team: ProviderRef
    team_name: str
    position: int | None
    points: int | None
    played: int | None
    won: int | None
    drawn: int | None
    lost: int | None
    goals_for: int | None
    goals_against: int | None
    yellow_cards: int | None
    red_cards: int | None
    raw: dict[str, Any] = field(default_factory=dict, compare=False)


@dataclass(frozen=True, slots=True)
class Fixture:
    match: ProviderRef
    round_number: int
    match_date: date
    home_team_slot: int
    away_team_slot: int
    home_team_name: str
    away_team_name: str
    home_team: ProviderRef | None
    away_team: ProviderRef | None
    home_goals: int | None
    away_goals: int | None
    home_yellow_cards: int | None
    away_yellow_cards: int | None
    home_red_cards: int | None
    away_red_cards: int | None
    result_code: int | None
    stadium: ProviderRef | None
    stadium_name: str | None
    referee: ProviderRef | None
    referee_name: str | None
    raw: dict[str, Any] = field(default_factory=dict, compare=False)

    @property
    def played(self) -> bool:
        return self.home_goals is not None and self.away_goals is not None


@dataclass(frozen=True, slots=True)
class CompetitionSnapshot:
    context: CompetitionContext
    standings: tuple[StandingRow, ...]
    fixtures: tuple[Fixture, ...]
    warnings: tuple[str, ...] = ()
