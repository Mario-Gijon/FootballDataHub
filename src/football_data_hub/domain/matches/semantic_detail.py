"""Observed, non-promotable semantic model for offline match-detail parsing.

This model is intentionally separate from the verified ``MatchDetail`` capture
contract. Parsing an existing discovery artifact must never imply that it is a
publishable or promotable capture.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

FieldState = Literal["observed", "explicitly_absent", "not_observed", "unresolved"]
EvidenceOrigin = Literal["match_detail_dom", "match_catalog", "discovery_metadata"]
EventKind = Literal[
    "goal",
    "penalty_goal",
    "missed_penalty",
    "yellow_card",
    "red_card",
    "second_yellow",
    "substitution_in",
    "substitution_out",
    "unknown",
]
Side = Literal["home", "away"]
AppearanceRole = Literal["starter", "substitute"]


@dataclass(frozen=True, slots=True)
class ProvenancedValue:
    value: str | int | None
    state: FieldState
    origin: EvidenceOrigin
    raw_value: str | None = None
    source_reference: str | None = None


@dataclass(frozen=True, slots=True)
class SemanticEvidence:
    field_path: str
    state: FieldState
    source_reference: str
    raw_value: str | None
    normalized_value: str | int | None
    source_html_sha256: str
    parser_version: str


@dataclass(frozen=True, slots=True)
class MatchDetailSource:
    provider: Literal["BDFutbol"]
    internal_id: str
    requested_url: str
    final_url: str
    canonical_url: str
    source_match_id: str
    discovery_id: str
    inventory_id: str
    source_capture_id: str
    source_generation_id: str
    source_html_sha256: str
    parser_version: str
    captured_at_utc: str
    artifact_access_status: str
    promotion_eligible: Literal[False] = False


@dataclass(frozen=True, slots=True)
class MatchContext:
    season: ProvenancedValue
    competition: ProvenancedValue
    group: ProvenancedValue
    matchday: ProvenancedValue


@dataclass(frozen=True, slots=True)
class TeamIdentity:
    side: Side
    team_id: int
    name: str
    team_url: str
    crest_url: str | None


@dataclass(frozen=True, slots=True)
class Coach:
    coach_id: int
    name: str
    profile_url: str
    photo_url: str | None
    nationality_class: str | None


@dataclass(frozen=True, slots=True)
class PlayerAppearance:
    role: AppearanceRole
    player_id: int
    name: str
    profile_url: str
    photo_url: str | None
    shirt_number: int | None
    position_code: str | None
    nationality_class: str | None
    participation_status: Literal["entered", "no_entry_marker", "not_applicable"]
    source_row: str


@dataclass(frozen=True, slots=True)
class MatchSide:
    team: TeamIdentity
    coach: Coach | None
    starters: tuple[PlayerAppearance, ...] | None
    substitutes: tuple[PlayerAppearance, ...] | None


@dataclass(frozen=True, slots=True)
class MatchScore:
    home_goals: int
    away_goals: int


@dataclass(frozen=True, slots=True)
class MatchEvent:
    event_type: EventKind
    side: Side
    team_id: int
    player_id: int | None
    player_name: str | None
    minute_literal: str | None
    minute_base: int | None
    minute_added: int | None
    is_penalty: bool | None
    score_after_home: int | None
    score_after_away: int | None
    raw_icon_class: str | None
    raw_icon_title: str | None
    raw_text: str
    source_reference: str


@dataclass(frozen=True, slots=True)
class AdditionalSourceNote:
    note_type: str
    text: str
    source_reference: str
    linked_player_id: int | None = None


@dataclass(frozen=True, slots=True)
class ValidationCheck:
    check: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class SemanticValidation:
    semantic_valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    checks: tuple[ValidationCheck, ...]
    promotion_eligible: Literal[False] = False


@dataclass(frozen=True, slots=True)
class MatchDetailObservation:
    schema_version: Literal["football_data_hub.match_detail_observation.v1"]
    source: MatchDetailSource
    context: MatchContext
    match_date: ProvenancedValue
    kickoff_time_local: ProvenancedValue
    timezone: ProvenancedValue
    home: MatchSide
    away: MatchSide
    score: MatchScore
    stadium_name: ProvenancedValue
    stadium_id: ProvenancedValue
    stadium_url: ProvenancedValue
    referee_name: ProvenancedValue
    referee_id: ProvenancedValue
    referee_url: ProvenancedValue
    events: tuple[MatchEvent, ...]
    additional_notes: tuple[AdditionalSourceNote, ...]
    aggregate_statistics_state: FieldState
    evidence: tuple[SemanticEvidence, ...]
    validation: SemanticValidation


def observation_to_payload(observation: MatchDetailObservation) -> dict[str, object]:
    """Return a JSON-compatible mapping without persisting it anywhere."""

    return asdict(observation)
