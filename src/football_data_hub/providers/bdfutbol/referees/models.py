"""Contratos semánticos para árbitros y estadísticas por ámbito."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

RefereeScope = Literal["all", "group1", "group2"]


@dataclass(frozen=True, slots=True)
class Referee:
    referee_id: str
    display_name: str
    full_name: str | None
    profile_url: str
    photo_url: str | None
    flag_url: str | None
    nationality: str | None
    nationality_code: str | None
    age_years: int | None
    birth_date: date | None
    birthplace: str | None
    province: str | None


@dataclass(frozen=True, slots=True)
class RefereeStatistics:
    referee_id: str
    season: str
    group_scope: RefereeScope
    published_order: int
    matches_officiated: int | None
    yellow_cards: int | None
    red_cards: int | None
    statistics_url: str | None
    source_page_url: str


@dataclass(frozen=True, slots=True)
class RefereeFilterOption:
    label: str
    value: str
    selected: bool
    target_url: str | None = None
    scope: RefereeScope | None = None


@dataclass(frozen=True, slots=True)
class RefereeRow:
    referee: Referee
    statistics: RefereeStatistics


@dataclass(frozen=True, slots=True)
class ParsedRefereePage:
    scope: RefereeScope
    source_url: str
    rows: tuple[RefereeRow, ...]
    group_options: tuple[RefereeFilterOption, ...]
    season_options: tuple[RefereeFilterOption, ...]


@dataclass(frozen=True, slots=True)
class ParsedReferees:
    referees: tuple[Referee, ...]
    statistics: tuple[RefereeStatistics, ...]
    group_options: tuple[RefereeFilterOption, ...]
    season_options: tuple[RefereeFilterOption, ...]
    scope_counts: dict[str, int]
    identity_conflicts: tuple[dict[str, object], ...] = ()
