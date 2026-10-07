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


@dataclass(frozen=True, slots=True)
class TeamSeasonContext:
    team: ProviderRef
    team_name: str
    season: str
    source_url: str
    competition_code: str | None = None
    competition_name: str | None = None
    group: int | None = None
    matches_played: int | None = None
    win_percentage: float | None = None
    provider: str = "bdfutbol"


@dataclass(frozen=True, slots=True)
class CoachAssignment:
    coach: ProviderRef
    coach_name: str
    age: int | None
    rounds: str | None
    matches: int | None
    yellow_cards: int | None
    red_cards: int | None
    raw: dict[str, Any] = field(default_factory=dict, compare=False)


@dataclass(frozen=True, slots=True)
class SquadMember:
    player: ProviderRef
    player_name: str
    squad_number: int | None
    squad_section: str
    position: str | None
    age: int | None
    appearances: int | None
    starts: int | None
    complete_matches: int | None
    substitute_appearances: int | None
    unused_callups: int | None
    minutes: int | None
    yellow_cards: int | None
    red_cards: int | None
    goals: int | None
    raw: dict[str, Any] = field(default_factory=dict, compare=False)


@dataclass(frozen=True, slots=True)
class TeamSeasonSnapshot:
    context: TeamSeasonContext
    coaches: tuple[CoachAssignment, ...]
    squad: tuple[SquadMember, ...]
    warnings: tuple[str, ...] = ()
