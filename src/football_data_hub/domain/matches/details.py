"""Modelos versionados para observaciones futuras de fichas de partidos.

Los valores opcionales permanecen en None hasta que una fuente los observe.
Una tupla vacía solo significa que se observó una colección vacía cuando la
evidencia correspondiente lo confirma.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields
from typing import Literal

FieldState = Literal["observed", "explicitly_absent", "not_observed", "unresolved"]
MatchEventKind = Literal[
    "goal",
    "penalty",
    "own_goal",
    "yellow_card",
    "red_card",
    "second_yellow",
    "substitution",
    "other",
]
AppearanceRole = Literal["starter", "substitute", "unknown"]


@dataclass(frozen=True, slots=True)
class FieldEvidence:
    """Procedencia de un campo; raw_value conserva ceros y cadenas vacías."""

    field_path: str
    state: FieldState
    source_reference: str | None = None
    raw_value: str | None = None
    source_capture_id: str | None = None
    source_html_sha256: str | None = None
    parser_version: str | None = None
    observed_at_utc: str | None = None


@dataclass(frozen=True, slots=True)
class MatchDetailIdentity:
    internal_id: str
    source_match_id: str
    season: str
    competition: str
    group: str
    matchday: int
    home_team_id: int
    away_team_id: int


@dataclass(frozen=True, slots=True)
class MatchScore:
    home_goals: int | None = None
    away_goals: int | None = None
    home_penalty_goals: int | None = None
    away_penalty_goals: int | None = None


@dataclass(frozen=True, slots=True)
class MatchPlayerAppearance:
    """Una aparición; se conserva el ID fuente si no se resuelve."""

    role: AppearanceRole = "unknown"
    player_id: int | None = None
    source_player_id: str | None = None
    player_name: str | None = None
    shirt_number: int | None = None
    position_code: str | None = None
    started_at_minute: int | None = None
    ended_at_minute: int | None = None
    source_reference: str | None = None


@dataclass(frozen=True, slots=True)
class MatchTeam:
    team_id: int | None = None
    source_team_id: str | None = None
    name: str | None = None
    coach_id: str | None = None
    coach_name: str | None = None
    starters: tuple[MatchPlayerAppearance, ...] | None = None
    substitutes: tuple[MatchPlayerAppearance, ...] | None = None


@dataclass(frozen=True, slots=True)
class MatchEvent:
    event_kind: MatchEventKind
    event_order: int | None = None
    minute_literal: str | None = None
    minute_base: int | None = None
    minute_added: int | None = None
    team_id: int | None = None
    player_id: int | None = None
    source_player_id: str | None = None
    player_name: str | None = None
    related_player_id: int | None = None
    related_source_player_id: str | None = None
    related_player_name: str | None = None
    is_penalty: bool | None = None
    is_own_goal: bool | None = None
    source_text: str | None = None
    source_reference: str | None = None


@dataclass(frozen=True, slots=True)
class MatchDiscrepancy:
    field_path: str
    calendar_value: str | int | None
    detail_value: str | int | None
    calendar_reference: str | None = None
    detail_reference: str | None = None


@dataclass(frozen=True, slots=True)
class MatchDetail:
    """Observación tipada, sin presuponer qué publica realmente la ficha."""

    schema_version: Literal["football_data_hub.match_detail.v1"]
    identity: MatchDetailIdentity
    source: str
    source_url: str
    source_generation_id: str
    source_capture_id: str
    capture_id: str | None = None
    captured_at_utc: str | None = None
    source_html_sha256: str | None = None
    match_date: str | None = None
    kickoff_time: str | None = None
    timezone: str | None = None
    stadium_id: str | None = None
    stadium_name: str | None = None
    stadium_url: str | None = None
    referee_id: str | None = None
    referee_name: str | None = None
    referee_url: str | None = None
    home_team: MatchTeam = MatchTeam()
    away_team: MatchTeam = MatchTeam()
    score: MatchScore = MatchScore()
    events: tuple[MatchEvent, ...] | None = None
    player_appearances: tuple[MatchPlayerAppearance, ...] | None = None
    source_references: tuple[str, ...] = ()
    field_evidence: tuple[FieldEvidence, ...] = ()
    discrepancies: tuple[MatchDiscrepancy, ...] = ()


@dataclass(frozen=True, slots=True)
class MatchDetailValidation:
    """Prueba estructurada para autorizar la promoción de un snapshot."""

    schema_version: Literal["football_data_hub.match_detail_validation.v1"]
    valid: bool
    http_status: int | None
    requested_url: str
    final_url: str | None
    identity_verified: bool
    structural_evidence: tuple[str, ...]
    challenge_detected: bool = False
    denial_detected: bool = False
    diagnostics: tuple[str, ...] = ()
    discrepancies: tuple[MatchDiscrepancy, ...] = ()


_MINUTE_PATTERN = re.compile(r"^(\d+)(?:\+(\d+))?['’]?$")


def validate_match_detail_contract(detail: MatchDetail) -> tuple[str, ...]:
    """Comprueba invariantes de tipos/semántica sin interpretar HTML fuente."""

    errors: list[str] = []
    if detail.schema_version != "football_data_hub.match_detail.v1":
        errors.append("schema_version")
    if not isinstance(detail.source, str) or detail.source != "BDFutbol":
        errors.append("source")
    if any(
        not isinstance(value, str) or not value
        for value in (
            detail.source_url,
            detail.source_generation_id,
            detail.source_capture_id,
        )
    ):
        errors.append("source_provenance")
    if any(
        not isinstance(value, str) or not value
        for value in (detail.identity.internal_id, detail.identity.source_match_id)
    ):
        errors.append("identity_ids")
    if not isinstance(detail.identity.group, str) or detail.identity.group not in ("I", "II"):
        errors.append("identity_group")
    if (
        not isinstance(detail.identity.matchday, int)
        or isinstance(detail.identity.matchday, bool)
        or detail.identity.matchday < 1
    ):
        errors.append("identity_matchday")
    team_ids = (detail.identity.home_team_id, detail.identity.away_team_id)
    if any(
        not isinstance(team_id, int) or isinstance(team_id, bool) or team_id <= 0
        for team_id in team_ids
    ) or detail.identity.home_team_id == detail.identity.away_team_id:
        errors.append("identity_team_ids")
    for name, value in (
        ("home_goals", detail.score.home_goals),
        ("away_goals", detail.score.away_goals),
        ("home_penalty_goals", detail.score.home_penalty_goals),
        ("away_penalty_goals", detail.score.away_penalty_goals),
    ):
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or value < 0
        ):
            errors.append(f"score.{name}")
    valid_event_kinds = (
        "goal",
        "penalty",
        "own_goal",
        "yellow_card",
        "red_card",
        "second_yellow",
        "substitution",
        "other",
    )
    for index, event in enumerate(detail.events or ()):
        if not isinstance(event.event_kind, str) or event.event_kind not in valid_event_kinds:
            errors.append(f"events[{index}].event_kind")
        if event.minute_base is not None and (
            not isinstance(event.minute_base, int)
            or isinstance(event.minute_base, bool)
            or event.minute_base < 0
        ):
            errors.append(f"events[{index}].minute_base")
        if event.minute_added is not None and (
            not isinstance(event.minute_added, int)
            or isinstance(event.minute_added, bool)
            or event.minute_added < 0
        ):
            errors.append(f"events[{index}].minute_added")
        if event.event_order is not None and (
            not isinstance(event.event_order, int)
            or isinstance(event.event_order, bool)
            or event.event_order < 0
        ):
            errors.append(f"events[{index}].event_order")
        if event.team_id is not None and (
            not isinstance(event.team_id, int)
            or isinstance(event.team_id, bool)
            or event.team_id not in team_ids
        ):
            errors.append(f"events[{index}].team_id")
    valid_roles = ("starter", "substitute", "unknown")
    appearances = list(detail.player_appearances or ())
    for team in (detail.home_team, detail.away_team):
        appearances.extend(team.starters or ())
        appearances.extend(team.substitutes or ())
    for index, player in enumerate(appearances):
        if not isinstance(player.role, str) or player.role not in valid_roles:
            errors.append(f"player_appearances[{index}].role")
        for name, number in (
            ("shirt_number", player.shirt_number),
            ("started_at_minute", player.started_at_minute),
            ("ended_at_minute", player.ended_at_minute),
        ):
            if number is not None and (
                not isinstance(number, int)
                or isinstance(number, bool)
                or number < 0
            ):
                errors.append(f"player_appearances[{index}].{name}")
    valid_field_states = (
        "observed",
        "explicitly_absent",
        "not_observed",
        "unresolved",
    )
    for index, evidence in enumerate(detail.field_evidence):
        if (
            not isinstance(evidence.field_path, str)
            or not evidence.field_path
            or not isinstance(evidence.state, str)
            or evidence.state not in valid_field_states
        ):
            errors.append(f"field_evidence[{index}]")
    return tuple(errors)


def match_detail_from_payload(payload: dict[str, object]) -> MatchDetail:
    """Rehidrata JSON validando estructura estricta y tipos de dataclass."""

    def construct(model: type, raw: object):
        if not isinstance(raw, dict):
            raise TypeError(f"{model.__name__} debe ser un objeto")
        allowed = {item.name for item in fields(model)}
        extra = set(raw) - allowed
        if extra:
            raise TypeError(f"{model.__name__} contiene campos desconocidos: {sorted(extra)}")
        return model(**raw)

    def appearances(raw: object) -> tuple[MatchPlayerAppearance, ...] | None:
        if raw is None:
            return None
        if not isinstance(raw, list):
            raise TypeError("La lista de apariciones debe ser array o null")
        return tuple(construct(MatchPlayerAppearance, item) for item in raw)

    def team(raw: object) -> MatchTeam:
        if not isinstance(raw, dict):
            raise TypeError("El equipo del detalle debe ser objeto")
        value = dict(raw)
        value["starters"] = appearances(value.get("starters"))
        value["substitutes"] = appearances(value.get("substitutes"))
        return construct(MatchTeam, value)

    if not isinstance(payload, dict):
        raise TypeError("MatchDetail debe ser objeto")
    value = dict(payload)
    value["identity"] = construct(MatchDetailIdentity, value.get("identity"))
    value["home_team"] = team(value.get("home_team"))
    value["away_team"] = team(value.get("away_team"))
    value["score"] = construct(MatchScore, value.get("score"))
    if value.get("events") is not None:
        raw_events = value["events"]
        if not isinstance(raw_events, list):
            raise TypeError("events debe ser array o null")
        value["events"] = tuple(construct(MatchEvent, item) for item in raw_events)
    if value.get("player_appearances") is not None:
        value["player_appearances"] = appearances(value["player_appearances"])
    for collection, model in (
        ("source_references", str),
        ("field_evidence", FieldEvidence),
        ("discrepancies", MatchDiscrepancy),
    ):
        raw_collection = value.get(collection)
        if not isinstance(raw_collection, list):
            raise TypeError(f"{collection} debe ser array")
        if model is str:
            if not all(isinstance(item, str) for item in raw_collection):
                raise TypeError("source_references solo acepta cadenas")
            value[collection] = tuple(raw_collection)
        else:
            value[collection] = tuple(construct(model, item) for item in raw_collection)
    return construct(MatchDetail, value)


def parse_literal_minute(value: str | None) -> tuple[int, int | None] | None:
    """Parsea minutos ordinarios y añadidos, conservando el literal original."""

    if value is None:
        return None
    match = _MINUTE_PATTERN.fullmatch(value.strip())
    if match is None:
        return None
    base = int(match.group(1))
    added = int(match.group(2)) if match.group(2) is not None else None
    return base, added
