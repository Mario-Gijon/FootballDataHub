"""Typed, view-specific contracts for captured player pages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

PlayerView = Literal["profile", "statistics", "matches", "rivals"]


@dataclass(frozen=True, slots=True)
class PlayerPageBase:
    player_id: int
    source_player_key: str
    view: PlayerView
    requested_url: str
    final_url: str
    page_title_raw: str | None
    source: dict[str, Any]
    filter_controls: list[dict[str, Any]]
    tables: list[dict[str, Any]]
    relationships: list[dict[str, Any]]
    coverage: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PlayerTrajectoryPage(PlayerPageBase):
    profile: dict[str, Any]
    career_rows: list[dict[str, Any]]
    career_totals: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class PlayerStatisticsPage(PlayerPageBase):
    statistics_rows: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class PlayerMatchesPage(PlayerPageBase):
    summary_rows: list[dict[str, Any]]
    individual_matches: list[dict[str, Any]]
    detail_coverage: str
    filter_parameters: dict[str, str]
    filtered_view: bool
    exhaustiveness_status: str


@dataclass(frozen=True, slots=True)
class PlayerRivalsPage(PlayerPageBase):
    rival_records: list[dict[str, Any]]

