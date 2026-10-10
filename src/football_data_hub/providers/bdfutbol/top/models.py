"""Contratos semánticos para la pestaña Destacados."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TopCategory = Literal[
    "goals", "minutes", "yellow_cards", "red_cards", "youngest", "oldest"
]


@dataclass(frozen=True, slots=True)
class TopPlayer:
    player_id: int
    display_name: str
    full_name: str | None
    profile_url: str
    photo_url: str | None
    nationality_code: str | None
    nationality: str | None
    position_code: str | None
    position_name: str | None
    age_years: int | None
    team_id: int | None
    team_name: str | None
    team_url: str | None
    crest_url: str | None


@dataclass(frozen=True, slots=True)
class TeamAffiliationEvidence:
    team_id: int
    team_name: str
    source_records: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlayerAffiliationConflict:
    player_id: int
    affiliations: tuple[TeamAffiliationEvidence, ...]


@dataclass(frozen=True, slots=True)
class RankingRecord:
    category: TopCategory
    rank: int
    player_id: int
    metric: str
    metric_value: int
    unit: str
    matches_played: int | None
    source_record: Literal["html_table", "destacats_js_lg"]
    graph_selected_by_default: bool | None


@dataclass(frozen=True, slots=True)
class ProgressPoint:
    matchday: int
    value: int | None


@dataclass(frozen=True, slots=True)
class ProgressSeries:
    category: Literal["goals", "minutes", "yellow_cards", "red_cards"]
    player_id: int
    metric: str
    unit: str
    points: tuple[ProgressPoint, ...]
    graph_selected_by_default: bool


@dataclass(frozen=True, slots=True)
class ForeignPlayerStatistics:
    player_id: int
    matches_played: int | None
    minutes_played: int | None
    goals: int | None
    yellow_cards: int | None
    red_cards: int | None


@dataclass(frozen=True, slots=True)
class ForeignersSummary:
    source_count: int
    source_percentage: float | None
    denominator_count: int | None
    implied_denominator_count: int | None
    country_options: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class ParsedTop:
    players: tuple[TopPlayer, ...]
    rankings: tuple[RankingRecord, ...]
    progress: tuple[ProgressSeries, ...]
    foreigners: tuple[ForeignPlayerStatistics, ...]
    foreigners_summary: ForeignersSummary
    category_options: tuple[tuple[str, str], ...]
    category_source_counts: dict[str, int]
    chart_matchdays: tuple[int, ...]
    see_all_available: bool
    warnings: tuple[str, ...] = ()
    affiliation_conflicts: tuple[PlayerAffiliationConflict, ...] = ()
