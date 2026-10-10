"""Stable public response contracts; provider-only fields are intentionally omitted."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, model_validator

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


class TopAffiliationSource(TopApiModel):
    team_id: StrictInt = Field(gt=0)
    team_name: str = Field(min_length=1)
    source_records: list[str] = Field(min_length=1)


class TopAffiliationConflict(TopApiModel):
    player_id: StrictInt = Field(gt=0)
    affiliations: list[TopAffiliationSource] = Field(min_length=2)


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
    warnings: list[str]
    affiliation_conflicts: list[TopAffiliationConflict]


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
    related_match_datasets: dict[str, "RefereeRelatedMatchDataset"]


class RefereeRelatedMatchDataset(RefereeApiModel):
    capture_id: str
    captured_at: datetime
    sha256: str
    reference_status: Literal["consistent", "discrepancies"]


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


class StatisticsApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


StatisticsNumber = StrictInt | StrictFloat | None


class StatisticsCaptureMetadata(StatisticsApiModel):
    source: str
    url: str
    competition: str
    season: str
    group: str
    section: Literal["statistics"]
    capture_id: str
    captured_at: datetime
    extractor_version: str
    dataset_version: str
    source_snapshot_sha256: str
    chart_data_provider_sha256: str
    match_dataset_path: str
    match_dataset_sha256: str
    match_dataset_capture_id: str
    match_dataset_captured_at: datetime
    active_match_capture_id: str


class StatisticsMetricCoverage(StatisticsApiModel):
    matches_played: StrictInt = Field(ge=0)
    matches_with_value: StrictInt = Field(ge=0)
    missing_match_ids: list[str]


class StatisticsRoundResponse(StatisticsApiModel):
    matchday: StrictInt = Field(ge=1, le=38)
    scheduled_matches: StrictInt = Field(ge=0)
    played_matches: StrictInt = Field(ge=0)
    unplayed_matches: StrictInt = Field(ge=0)
    incomplete_matches: StrictInt = Field(ge=0)
    coverage: Literal["complete", "partial", "not_started", "incomplete"]
    goals: OptionalInt
    yellow_cards: OptionalInt
    red_cards: OptionalInt
    yellow_card_coverage: StatisticsMetricCoverage
    red_card_coverage: StatisticsMetricCoverage


class CompetitionStatisticsResponse(StatisticsApiModel):
    competition: str
    season: str
    group: str
    team_count: StrictInt = Field(ge=0)
    scheduled_matches: StrictInt = Field(ge=0)
    played_matches: StrictInt = Field(ge=0)
    unplayed_matches: StrictInt = Field(ge=0)
    incomplete_matches: StrictInt = Field(ge=0)
    home_wins: StrictInt = Field(ge=0)
    away_wins: StrictInt = Field(ge=0)
    draws: StrictInt = Field(ge=0)
    goals: OptionalInt
    goals_per_match: StrictFloat | None
    yellow_cards: OptionalInt
    yellow_cards_per_match: StrictFloat | None
    red_cards: OptionalInt
    red_cards_per_match: StrictFloat | None
    yellow_card_coverage: StatisticsMetricCoverage
    red_card_coverage: StatisticsMetricCoverage
    rounds: list[StatisticsRoundResponse]


class StatisticsMatchRecord(StatisticsApiModel):
    match_id: str
    matchday: StrictInt = Field(ge=1, le=38)
    home_team_id: StrictInt = Field(gt=0)
    away_team_id: StrictInt = Field(gt=0)
    home_goals: StrictInt = Field(ge=0)
    away_goals: StrictInt = Field(ge=0)


class StatisticsRecordSet(StatisticsApiModel):
    kind: Literal["largest_home_win", "largest_away_win", "most_goals"]
    measure: StrictInt = Field(ge=0)
    matches: list[StatisticsMatchRecord] = Field(min_length=1)


class StatisticsStreak(StatisticsApiModel):
    team_id: StrictInt = Field(gt=0)
    kind: Literal["winning", "losing", "unbeaten", "winless"]
    match_count: StrictInt = Field(ge=1)
    matchday_start: StrictInt = Field(ge=1, le=38)
    matchday_end: StrictInt = Field(ge=1, le=38)
    match_ids: list[str] = Field(min_length=1)


class StatisticsRecords(StatisticsApiModel):
    match_records: list[StatisticsRecordSet]
    streaks: list[StatisticsStreak]


class StatisticsPenalties(StatisticsApiModel):
    penalties_awarded: StrictInt = Field(ge=0)
    penalties_scored: StrictInt = Field(ge=0)
    penalties_missed: StrictInt = Field(ge=0)
    source_labels: list[str]
    unit: Literal["penalties"]
    scope: Literal["competition_total"]
    source_url: str


class StatisticsPublishedMetric(StatisticsApiModel):
    statistic: str
    calculated: StatisticsNumber
    published: StatisticsNumber
    difference_published_minus_calculated: StatisticsNumber
    comparison_basis: str
    status: str
    cause: str | None


class StatisticsPenaltyCheckValues(StatisticsApiModel):
    penalties_awarded: StrictInt
    penalties_scored: StrictInt
    penalties_missed: StrictInt
    source_labels: list[str]


class StatisticsPublishedPenaltyCheck(StatisticsApiModel):
    source: StatisticsPenaltyCheckValues
    status: str
    equation_valid: bool


class StatisticsPublishedRecordCheck(StatisticsApiModel):
    kind: Literal["largest_home_win", "largest_away_win", "most_goals"]
    measure: StrictInt
    match_id: str
    home_goals: StrictInt
    away_goals: StrictInt
    source_url: str
    home_team_id: StrictInt
    away_team_id: StrictInt
    calculated_measure: StrictInt
    calculated_match_ids: list[str]
    status: str


class StatisticsPublishedStreakCheck(StatisticsApiModel):
    kind: Literal["winning", "losing", "unbeaten", "winless"]
    published_team_name: str
    resolved_team_id: StrictInt
    published_match_count: StrictInt
    published_matchday_start: StrictInt
    published_matchday_end: StrictInt
    calculated_max_match_count: StrictInt
    calculated_tied_team_ids: list[StrictInt]
    calculated_match_ids: list[list[str]]
    status: str


class StatisticsRoundCheck(StatisticsApiModel):
    matchday: StrictInt = Field(ge=1, le=38)
    statistic: Literal["goals", "yellow_cards", "red_cards"]
    calculated: StatisticsNumber
    published: StatisticsNumber
    difference_published_minus_calculated: StatisticsNumber
    played_matches: StrictInt = Field(ge=0)
    scheduled_matches: StrictInt = Field(ge=0)
    coverage: Literal["complete", "partial", "not_started", "incomplete"]
    status: str
    cause: str | None


class StatisticsReconciliationSummary(StatisticsApiModel):
    metric_count: StrictInt = Field(ge=0)
    metric_matches: StrictInt = Field(ge=0)
    metric_differences: StrictInt = Field(ge=0)
    metric_semantics_unverified: StrictInt = Field(ge=0)
    record_statuses: dict[str, str]
    round_series_differences: StrictInt = Field(ge=0)


class StatisticsReconciliation(StatisticsApiModel):
    statistics_capture_id: str
    statistics_captured_at_utc: datetime
    match_dataset_capture_id: str
    match_dataset_captured_at_utc: datetime
    capture_windows_differ: bool
    temporal_comparison_status: str
    match_data_alignment: dict[str, object]
    metrics: list[StatisticsPublishedMetric]
    exclusive_penalties: StatisticsPublishedPenaltyCheck
    published_match_records: list[StatisticsPublishedRecordCheck]
    published_streaks: list[StatisticsPublishedStreakCheck]
    round_series: list[StatisticsRoundCheck]
    summary: StatisticsReconciliationSummary


class StatisticsBootstrapResponse(StatisticsApiModel):
    metadata: StatisticsCaptureMetadata
    statistics: CompetitionStatisticsResponse
    penalties: StatisticsPenalties
    records: StatisticsRecords
    reconciliation: StatisticsReconciliation
    methodology: dict[str, str]
    limitations: list[str]
