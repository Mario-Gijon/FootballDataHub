"""Semantic records for a club identity and its season-scoped data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class TeamIdentity:
    team_id: int
    name: str
    team_url: str
    crest_url: str | None


@dataclass(frozen=True, slots=True)
class TeamSeasonCoach:
    coach_id: int
    display_name: str
    full_name: str | None
    profile_url: str
    photo_url: str | None
    age_years: int | None = None
    birth_date: str | None = None
    birthplace: str | None = None
    birthplace_province: str | None = None
    coached_matchdays_source: str | None = None
    matches_managed: int | None = None
    yellow_cards: int | None = None
    red_cards: int | None = None
    source_views: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TeamSeason:
    team_id: int
    season: str
    competition: str
    group: str
    competition_scope: str
    coaches: tuple[TeamSeasonCoach, ...]


@dataclass(frozen=True, slots=True)
class PlayerIdentity:
    player_id: int
    display_name: str
    full_name: str | None
    profile_url: str
    photo_url: str | None
    age_years: int | None = None
    birth_date: str | None = None
    birthplace: str | None = None
    birthplace_province: str | None = None
    nationality_flag_url: str | None = None
    source_position_code: str | None = None
    verified_indicators: tuple[str, ...] = ()
    source_views: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PlayerTeamMembership:
    player_id: int
    team_id: int
    season: str
    competition: str
    group: str
    jersey_number: int | None
    squad_group_label: str | None
    source_views: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlayerSeasonStatistics:
    player_id: int
    team_id: int
    season: str
    competition: str
    group: str
    matches_played: int | None
    starts: int | None
    full_matches: int | None
    substitute_appearances: int | None
    matches_substituted: int | None
    unused_substitute_calls: int | None
    minutes_played: int | None
    yellow_cards: int | None
    red_cards: int | None
    goals: int | None
    minutes_per_goal: int | None
    penalty_goals: int | None
    own_goals: int | None
    goals_conceded: int | None
    team_wins: int | None
    team_draws: int | None
    team_losses: int | None
    source_view: str


@dataclass(frozen=True, slots=True)
class PlayerMatchMinutes:
    player_id: int
    team_id: int
    season: str
    competition: str
    group: str
    matchday: int
    match_id: str
    metric: Literal["minutes_played"]
    value: int | None
    raw_value: str
    source_view: str
    source_state: str


@dataclass(frozen=True, slots=True)
class PlayerMatchMetric:
    """Positive player-match facts from BDFutbol Seguimiento states."""

    player_id: int
    team_id: int
    season: str
    competition: str
    group: str
    matchday: int
    match_id: str
    metric: Literal["yellow_cards", "red_cards", "goals"]
    value: int
    raw_value: str
    source_view: str
    source_state: Literal["t", "go"]


@dataclass(frozen=True, slots=True)
class TeamTransfer:
    player_id: int
    player_display_name: str
    player_full_name: str | None
    player_profile_url: str
    player_photo_url: str | None
    team_id: int
    season: str
    competition: str
    group: str
    direction: Literal["incoming", "outgoing"]
    other_team_name: str | None
    other_team_id: int | None
    other_team_url: str | None
    age_years: int | None
    source_position_code: str | None
    transfer_date: str | None
    fee: str | None
    source_view: str
    source_heading: str


@dataclass(frozen=True, slots=True)
class TeamTransferSection:
    """Proof that one source transfer section was parsed, including empty ones."""

    direction: Literal["incoming", "outgoing"]
    source_heading: Literal["Altas", "Bajas"]
    status: Literal["verified_with_rows", "verified_empty"]
    row_count: int
    source_team_column: Literal["Equipo origen", "Equipo destino"]


@dataclass(frozen=True, slots=True)
class TeamProfileData:
    identity: TeamIdentity
    season: TeamSeason
    players: tuple[PlayerIdentity, ...]
    memberships: tuple[PlayerTeamMembership, ...]
    player_statistics: tuple[PlayerSeasonStatistics, ...]
    player_match_minutes: tuple[PlayerMatchMinutes, ...]
    player_match_metrics: tuple[PlayerMatchMetric, ...]
    follow_states_captured: tuple[str, ...]
    transfers: tuple[TeamTransfer, ...]
    transfer_sections: tuple[TeamTransferSection, ...]
    group_team_ids_from_profile: tuple[int, ...]
    team_match_ids_from_profile: tuple[str, ...]
    warnings: tuple[str, ...]
