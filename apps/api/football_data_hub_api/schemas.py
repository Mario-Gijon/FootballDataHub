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
