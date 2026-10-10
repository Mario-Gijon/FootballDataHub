"""Stable public response contracts; provider-only fields are intentionally omitted."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

OptionalInt = StrictInt | None


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TeamResponse(ApiModel):
    team_id: StrictInt = Field(gt=0)
    name: str = Field(min_length=1)
    team_url: str | None
    crest_url: str | None


class MatchResponse(ApiModel):
    match_id: str = Field(min_length=1)
    matchday: StrictInt = Field(ge=1, le=38)
    matchday_date: date | None
    source_match_date: date | None
    home_team_id: StrictInt = Field(gt=0)
    away_team_id: StrictInt = Field(gt=0)
    home_goals: OptionalInt
    away_goals: OptionalInt
    home_yellow_cards: OptionalInt
    away_yellow_cards: OptionalInt
    home_red_cards: OptionalInt
    away_red_cards: OptionalInt
    status: Literal["played", "unplayed", "incomplete"]
    unplayed_state: Literal[
        "scheduled", "result_unavailable_at_capture", "unknown"
    ] | None
    postponed_by_source_rule: bool | None
    source_match_url: str | None = None
    stadium_id: str | None = None
    stadium_name: str | None = None
    stadium_url: str | None = None
    referee_id: str | None = None
    referee_name: str | None = None
    referee_url: str | None = None

    @model_validator(mode="after")
    def validate_match_state(self) -> MatchResponse:
        if self.home_team_id == self.away_team_id:
            raise ValueError("Un equipo no puede jugar contra sí mismo")
        if self.status == "played":
            if self.home_goals is None or self.away_goals is None:
                raise ValueError("Un partido disputado requiere ambos marcadores")
            if self.unplayed_state is not None:
                raise ValueError("Un partido disputado no puede tener estado sin disputar")
        elif self.status == "unplayed":
            if self.home_goals is not None or self.away_goals is not None:
                raise ValueError("Un partido sin disputar debe conservar marcadores null")
            if self.unplayed_state is None:
                raise ValueError("Un partido sin disputar requiere unplayed_state")
        return self


class ProgressResponse(ApiModel):
    team_id: StrictInt
    matchday: StrictInt
    matchday_date: date | None
    position: OptionalInt
    points: OptionalInt
    goals_for: OptionalInt
    goals_against: OptionalInt


class ProgressContextResponse(ApiModel):
    classification_type: Literal["general"]
    postponed_policy: Literal["source_defined_unknown"]
    range_type: Literal["all"]
    source_independent_of_standings_filters: bool
    available_through_matchday: StrictInt = Field(ge=1, le=38)


class PublishedStandingResponse(ApiModel):
    team_id: StrictInt
    team_name: str
    team_url: str | None
    crest_url: str | None
    position: OptionalInt
    points: OptionalInt
    matches_played: OptionalInt
    wins: OptionalInt
    draws: OptionalInt
    losses: OptionalInt
    goals_for: OptionalInt
    goals_against: OptionalInt
    yellow_cards: OptionalInt
    red_cards: OptionalInt
    position_change: Literal["up", "down", "same"] | None
    sports_zone: Literal[
        "direct_promotion", "promotion", "stay", "relegation"
    ] | None


class PublishedStandingsContext(ApiModel):
    classification_type: Literal["general", "local", "visitor"]
    matchday: StrictInt
    matchday_date: date | None
    postponed_policy: Literal["include", "exclude"]
    range_type: Literal["all", "dates", "rounds"]


class PublishedStandingsResponseModel(ApiModel):
    source: str
    source_capture_id: str
    context: PublishedStandingsContext
    rows: list[PublishedStandingResponse]


class AvailabilitySummary(ApiModel):
    teams: StrictInt
    matches: StrictInt
    played_matches: StrictInt
    unplayed_matches: StrictInt
    incomplete_matches: StrictInt
    matchdays_with_fixtures: list[StrictInt]
    last_matchday_with_results: StrictInt | None
    progress_records: StrictInt
    progress_through_matchday: StrictInt
    published_standings_available: bool


class DatasetMetadata(ApiModel):
    schema_version: StrictInt
    source: str
    url: str
    competition: str
    season: str
    group: str
    team_count: StrictInt
    scheduled_matchdays: list[StrictInt]
    last_matchday_with_results: StrictInt | None
    captured_at: datetime
    capture_id: str
    dataset_version: str
    availability: AvailabilitySummary
    progress_context: ProgressContextResponse
    warnings: list[str]


class BootstrapResponse(ApiModel):
    metadata: DatasetMetadata
    teams: list[TeamResponse]
    matches: list[MatchResponse]
    progress: list[ProgressResponse]
    published_standings: PublishedStandingsResponseModel | None


class HealthResponse(ApiModel):
    status: Literal["ok"]
    dataset_ready: bool


class ReadinessResponse(ApiModel):
    status: Literal["ready"]
    capture_id: str
    dataset_version: str


TopCategory = Literal[
    "goals", "minutes", "yellow_cards", "red_cards", "youngest", "oldest"
]
TopMetric = Literal["goals", "minutes_played", "yellow_cards", "red_cards", "age_years"]
ProgressMetric = Literal["goals", "minutes_played", "yellow_cards", "red_cards"]


class TopApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class TopCaptureMetadata(TopApiModel):
    source: str
    url: str
    competition: str
    season: str
    group: str
    section: Literal["top"]
    capture_id: str
    captured_at: datetime
    extractor_version: str
    source_snapshot_sha256: str
    related_team_capture_id: str
    related_team_catalog_sha256: str
    active_team_capture_id: str | None
    dataset_version: str


class TopPlayerResponse(TopApiModel):
    player_id: StrictInt = Field(gt=0)
    display_name: str = Field(min_length=1)
    full_name: str | None
    profile_url: str | None
    photo_url: str | None
    nationality_code: str | None
    nationality: str | None
    position_code: str | None
    position_name: str | None
    age_years: OptionalInt
    team_id: StrictInt | None
    team_name: str | None
    team_url: str | None
    crest_url: str | None


class TopRankingResponse(TopApiModel):
    category: TopCategory
    rank: StrictInt = Field(ge=1)
    player_id: StrictInt = Field(gt=0)
    metric: TopMetric
    metric_value: StrictInt = Field(ge=0)
    unit: Literal["goals", "minutes", "cards", "years"]
    matches_played: OptionalInt
    source_record: Literal["html_table", "destacats_js_lg"]
    graph_selected_by_default: bool | None


class TopProgressPoint(TopApiModel):
    matchday: StrictInt = Field(ge=1, le=38)
    value: OptionalInt


class TopProgressSeries(TopApiModel):
    category: Literal["goals", "minutes", "yellow_cards", "red_cards"]
    player_id: StrictInt = Field(gt=0)
    metric: ProgressMetric
    unit: Literal["goals", "minutes", "cards"]
    points: list[TopProgressPoint]
    graph_selected_by_default: bool


class TopCountryOption(TopApiModel):
    code: str
    label: str


class TopForeignStatistics(TopApiModel):
    matches_played: OptionalInt
    minutes_played: OptionalInt
    goals: OptionalInt
    yellow_cards: OptionalInt
    red_cards: OptionalInt


class TopForeignPlayerResponse(TopApiModel):
    player_id: StrictInt = Field(gt=0)
    statistics: TopForeignStatistics


class TopForeignersSummary(TopApiModel):
    source_count: StrictInt = Field(ge=0)
    source_percentage: float | None
    denominator_count: StrictInt | None
    country_options: list[TopCountryOption]


class TopCategoryOption(TopApiModel):
    source_value: str
    category: TopCategory
    label: str
    available_count: StrictInt = Field(ge=0)
    graph_available: bool
    see_all_available: bool


class TopAvailability(TopApiModel):
    players: StrictInt = Field(ge=0)
    ranking_records: StrictInt = Field(ge=0)
    progress_series: StrictInt = Field(ge=0)
    progress_points: StrictInt = Field(ge=0)
    foreign_players: StrictInt = Field(ge=0)
    categories: dict[TopCategory, StrictInt]
    matchdays: list[StrictInt]


class TopBootstrapResponse(TopApiModel):
    metadata: TopCaptureMetadata
    availability: TopAvailability
    categories: list[TopCategoryOption]
    players: list[TopPlayerResponse]
    rankings: list[TopRankingResponse]
    progress: list[TopProgressSeries]
    foreigners: list[TopForeignPlayerResponse]
    foreigners_summary: TopForeignersSummary
    coverage_note: str


RefereeScope = Literal["all", "group1", "group2"]


class RefereeApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RefereeMetadataResponse(RefereeApiModel):
    source: str
    url: str
    competition: str
    season: str
    group: str
    section: Literal["referees"]
    capture_id: str
    captured_at: datetime
    extractor_version: str
    dataset_version: str
    source_snapshot_sha256: dict[RefereeScope, str]
    related_matches_path: str
    related_matches_sha256: str
    related_matches_capture_id: str
    related_matches_captured_at: datetime
    match_reference_status: Literal["consistent", "discrepancies"]


class RefereeResponse(RefereeApiModel):
    referee_id: str
    display_name: str
    full_name: str | None
    profile_url: str
    photo_url: str | None
    flag_url: str | None
    nationality: str | None
    nationality_code: str | None
    age_years: StrictInt | None
    birth_date: date | None
    birthplace: str | None
    province: str | None


class RefereeStatisticsResponse(RefereeApiModel):
    referee_id: str
    season: str
    group_scope: RefereeScope
    published_order: StrictInt
    matches_officiated: OptionalInt
    yellow_cards: OptionalInt
    red_cards: OptionalInt
    statistics_url: str | None
    source_page_url: str


class RefereeScopeSummary(RefereeApiModel):
    group_scope: RefereeScope
    label: str
    referee_count: StrictInt
    matches_officiated: OptionalInt
    yellow_cards: OptionalInt
    red_cards: OptionalInt


class RefereeAvailability(RefereeApiModel):
    catalog_referee_count: StrictInt
    statistics_record_count: StrictInt
    scope_counts: dict[RefereeScope, RefereeScopeSummary]


class RefereeSeasonOption(RefereeApiModel):
    season: str
    label: str
    available: bool


class RefereeGroupOption(RefereeApiModel):
    group_scope: RefereeScope
    label: str
    referee_count: StrictInt


class RefereeBootstrapResponse(RefereeApiModel):
    metadata: RefereeMetadataResponse
    availability: RefereeAvailability
    seasons: list[RefereeSeasonOption]
    groups: list[RefereeGroupOption]
    referees: list[RefereeResponse]
    statistics: list[RefereeStatisticsResponse]
    coverage_note: str
    compatibility_warnings: list[str]
