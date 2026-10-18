"""Stable public response contracts; provider-only fields are intentionally omitted."""

from __future__ import annotations

from datetime import date, datetime
import re
from typing import Any, Literal
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, model_validator

OptionalInt = StrictInt | None


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TeamRosterCoachResponse(ApiModel):
    coach_id: StrictInt = Field(gt=0)
    display_name: str = Field(min_length=1)
    full_name: str | None
    profile_url: str | None
    photo_url: str | None
    age_years: OptionalInt
    birth_date: date | None
    birthplace: str | None
    birthplace_province: str | None
    coached_matchdays_source: str | None
    matches_managed: OptionalInt
    yellow_cards: OptionalInt
    red_cards: OptionalInt
    source_views: list[str]


class TeamRosterPlayerResponse(ApiModel):
    player_id: StrictInt = Field(gt=0)
    display_name: str = Field(min_length=1)
    full_name: str | None
    profile_url: str | None
    photo_url: str | None
    age_years: OptionalInt
    birth_date: date | None
    birthplace: str | None
    birthplace_province: str | None
    nationality_flag_url: str | None
    source_position_code: str | None
    verified_indicators: list[str]
    source_views: list[str]


class TeamRosterMembershipResponse(ApiModel):
    player_id: StrictInt = Field(gt=0)
    team_id: StrictInt = Field(gt=0)
    season: str
    competition: str
    group: str
    jersey_number: OptionalInt
    squad_group_label: str | None
    source_views: list[str]


class TeamRosterPlayerStatisticsResponse(ApiModel):
    player_id: StrictInt = Field(gt=0)
    team_id: StrictInt = Field(gt=0)
    season: str
    competition: str
    group: str
    matches_played: OptionalInt
    starts: OptionalInt
    full_matches: OptionalInt
    substitute_appearances: OptionalInt
    matches_substituted: OptionalInt
    unused_substitute_calls: OptionalInt
    minutes_played: OptionalInt
    yellow_cards: OptionalInt
    red_cards: OptionalInt
    goals: OptionalInt
    minutes_per_goal: OptionalInt
    penalty_goals: OptionalInt
    own_goals: OptionalInt
    goals_conceded: OptionalInt
    team_wins: OptionalInt
    team_draws: OptionalInt
    team_losses: OptionalInt
    source_view: str


class TeamRosterSourceViewResponse(ApiModel):
    view: str
    url: str
    title: str
    status: Literal["VALID"]
    http_status: StrictInt
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    captured_at: datetime | None


class TeamRosterMetadataResponse(ApiModel):
    contract_version: Literal[2]
    validation_status: Literal["valid"]
    source: Literal["BDFutbol"]
    url: str
    competition: Literal["Primera Federación"]
    season: Literal["2026-27"]
    group: Literal["I", "II"]
    team_id: StrictInt = Field(gt=0)
    capture_id: str = Field(min_length=1)
    captured_at: datetime
    extractor_version: str
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class TeamRosterGroupResponse(ApiModel):
    label: str = Field(min_length=1)
    player_ids: list[StrictInt]


class TeamRosterTacticalPositionResponse(ApiModel):
    player_id: StrictInt = Field(gt=0)
    horizontal: StrictFloat = Field(ge=0, le=1)
    vertical: StrictFloat = Field(ge=0, le=1)
    line: Literal["goalkeeper", "defense", "midfield", "attack"]
    slot: StrictInt = Field(ge=1)
    line_size: StrictInt = Field(ge=1)
    source_dom_id: str = Field(pattern=r"^d_(por|def\d+\d+|mig\d+\d+|dav\d+\d+)$")

    @model_validator(mode="after")
    def validate_slot(self) -> TeamRosterTacticalPositionResponse:
        if self.slot > self.line_size:
            raise ValueError("La posición táctica supera el número de huecos de su línea.")
        return self


class TeamRosterTacticalResponse(ApiModel):
    source: Literal["BDFutbol"]
    source_view: Literal["alignment"]
    source_url: str
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    coordinate_method: Literal["source_line_and_slot_normalized"]
    layout_convention: Literal["goalkeeper_to_attack_left_to_right"]
    approximate: Literal[True]
    positions: list[TeamRosterTacticalPositionResponse] = Field(min_length=1)


class TeamRosterResponse(ApiModel):
    status: Literal["available"]
    metadata: TeamRosterMetadataResponse
    team: TeamResponse
    coaches: list[TeamRosterCoachResponse]
    players: list[TeamRosterPlayerResponse]
    memberships: list[TeamRosterMembershipResponse]
    statistics: list[TeamRosterPlayerStatisticsResponse]
    squad_groups: list[TeamRosterGroupResponse]
    tactical_visualization: TeamRosterTacticalResponse | None = None
    source_views: list[TeamRosterSourceViewResponse]
    warnings: list[str]

    @model_validator(mode="after")
    def validate_player_links(self) -> TeamRosterResponse:
        player_ids = {player.player_id for player in self.players}
        if len(player_ids) != len(self.players):
            raise ValueError("El catálogo de Plantilla repite player_id.")
        if any(item.player_id not in player_ids for item in self.memberships):
            raise ValueError("Una pertenencia no tiene identidad de jugador.")
        if any(item.player_id not in player_ids for item in self.statistics):
            raise ValueError("Una estadística no tiene identidad de jugador.")
        if any(item.team_id != self.team.team_id for item in self.memberships):
            raise ValueError("Una pertenencia corresponde a otro equipo.")
        if any(item.team_id != self.team.team_id for item in self.statistics):
            raise ValueError("Una estadística corresponde a otro equipo.")
        grouped_player_ids = [player_id for group in self.squad_groups for player_id in group.player_ids]
        if any(player_id not in player_ids for player_id in grouped_player_ids):
            raise ValueError("Una agrupación de Plantilla referencia un jugador ausente.")
        if len(grouped_player_ids) != len(set(grouped_player_ids)):
            raise ValueError("Un jugador aparece repetido en las agrupaciones de Plantilla.")
        if self.tactical_visualization is not None:
            tactic_player_ids = [item.player_id for item in self.tactical_visualization.positions]
            if len(tactic_player_ids) != len(set(tactic_player_ids)):
                raise ValueError("La táctica repite player_id.")
            if not set(tactic_player_ids).issubset(player_ids):
                raise ValueError("La táctica referencia un jugador ausente del catálogo.")
            starter_ids = {
                player_id
                for group in self.squad_groups
                if group.label.casefold() == "titulares"
                for player_id in group.player_ids
            }
            if not set(tactic_player_ids).issubset(starter_ids):
                raise ValueError("La táctica incluye jugadores fuera de la agrupación Titulares.")
            alignment = next((view for view in self.source_views if view.view == "alignment"), None)
            if (
                alignment is None
                or self.tactical_visualization.source_url != alignment.url
                or self.tactical_visualization.source_sha256 != alignment.sha256
            ):
                raise ValueError("La procedencia de la táctica no coincide con Alineación.")
        return self


class TeamFollowPlayerResponse(ApiModel):
    player_id: StrictInt = Field(gt=0)
    display_name: str = Field(min_length=1)
    profile_url: str | None
    photo_url: str | None
    jersey_number: OptionalInt


class TeamFollowMatchResponse(ApiModel):
    match_id: str = Field(min_length=1)
    matchday: StrictInt = Field(ge=1, le=38)
    matchday_date: date | None
    source_match_date: date | None
    home_team_id: StrictInt = Field(gt=0)
    home_team_name: str = Field(min_length=1)
    away_team_id: StrictInt = Field(gt=0)
    away_team_name: str = Field(min_length=1)
    home_goals: OptionalInt
    away_goals: OptionalInt
    status: Literal["played", "unplayed", "incomplete"]


class TeamFollowMinutesResponse(ApiModel):
    player_id: StrictInt = Field(gt=0)
    match_id: str = Field(min_length=1)
    matchday: StrictInt = Field(ge=1, le=38)
    minutes_played: OptionalInt
    source_value: str
    source_view: Literal["follow"]
    source_state: Literal["p"]


class TeamFollowMetricResponse(ApiModel):
    player_id: StrictInt = Field(gt=0)
    match_id: str = Field(min_length=1)
    matchday: StrictInt = Field(ge=1, le=38)
    metric: Literal["yellow_cards", "red_cards", "goals"]
    value: StrictInt = Field(gt=0)
    source_value: str
    source_view: Literal["follow"]
    source_state: Literal["t", "go"]

    @model_validator(mode="after")
    def validate_metric_source(self) -> TeamFollowMetricResponse:
        expected_state = "go" if self.metric == "goals" else "t"
        if self.source_state != expected_state:
            raise ValueError("La métrica no coincide con el estado fuente de Seguimiento.")
        return self


class TeamFollowStateCoverageResponse(ApiModel):
    state: Literal["p", "t", "go", "tot"]
    available: bool
    record_count: StrictInt = Field(ge=0)
    value_total: StrictInt | None = Field(default=None, ge=0)
    matchdays: list[StrictInt]


class TeamFollowMetadataResponse(ApiModel):
    contract_version: Literal[2]
    source: Literal["BDFutbol"]
    url: str
    competition: Literal["Primera Federación"]
    competition_scope: Literal["Liga"]
    season: Literal["2026-27"]
    group: Literal["I", "II"]
    team_id: StrictInt = Field(gt=0)
    capture_id: str = Field(min_length=1)
    captured_at: datetime
    extractor_version: str
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    match_capture_id: str = Field(min_length=1)
    match_catalog_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    derived_states: list[Literal["p", "t", "go", "tot"]] = Field(default_factory=list)
    derived_at: datetime | None = None


class TeamFollowResponse(ApiModel):
    status: Literal["available"]
    metadata: TeamFollowMetadataResponse
    team: TeamResponse
    players: list[TeamFollowPlayerResponse]
    matches: list[TeamFollowMatchResponse]
    matchdays: list[StrictInt]
    minutes: list[TeamFollowMinutesResponse]
    metrics: list[TeamFollowMetricResponse]
    coverage: list[TeamFollowStateCoverageResponse]
    warnings: list[str]

    @model_validator(mode="after")
    def validate_follow_references(self) -> TeamFollowResponse:
        player_ids = {player.player_id for player in self.players}
        match_ids = {match.match_id for match in self.matches}
        if len(player_ids) != len(self.players) or len(match_ids) != len(self.matches):
            raise ValueError("Seguimiento repite jugadores o partidos.")
        if len({match.matchday for match in self.matches}) != len(self.matches):
            raise ValueError("Seguimiento no puede repetir partidos de un equipo en la misma jornada.")
        if self.metadata.team_id != self.team.team_id:
            raise ValueError("Seguimiento corresponde a otro equipo.")
        if any(row.player_id not in player_ids or row.match_id not in match_ids for row in self.minutes + self.metrics):
            raise ValueError("Una celda de Seguimiento no enlaza jugador y partido.")
        if any(row.matchday != next(match.matchday for match in self.matches if match.match_id == row.match_id) for row in self.minutes + self.metrics):
            raise ValueError("La jornada de una celda no coincide con el partido.")
        minute_keys = [(row.player_id, row.match_id) for row in self.minutes]
        metric_keys = [(row.player_id, row.match_id, row.metric) for row in self.metrics]
        if len(minute_keys) != len(set(minute_keys)) or len(metric_keys) != len(set(metric_keys)):
            raise ValueError("Seguimiento repite una celda de minutos o métrica.")
        matchdays_from_matches = {match.matchday for match in self.matches}
        if self.matchdays != sorted(set(self.matchdays)) or set(self.matchdays) != matchdays_from_matches:
            raise ValueError("La lista de jornadas de Seguimiento no es coherente.")
        states = [item.state for item in self.coverage]
        if set(states) != {"p", "t", "go", "tot"} or len(states) != 4:
            raise ValueError("Seguimiento debe indicar cobertura para sus cuatro estados.")
        return self


class TeamResponse(ApiModel):
    team_id: StrictInt = Field(gt=0)
    name: str = Field(min_length=1)
    team_url: str | None
    crest_url: str | None


class TeamTransferSectionResponse(ApiModel):
    direction: Literal["incoming", "outgoing"]
    source_heading: Literal["Altas", "Bajas"]
    status: Literal["verified_with_rows", "verified_empty"]
    row_count: StrictInt = Field(ge=0)
    source_team_column: Literal["Equipo origen", "Equipo destino"]

    @model_validator(mode="after")
    def validate_section(self) -> TeamTransferSectionResponse:
        expected = {
            "incoming": ("Altas", "Equipo origen"),
            "outgoing": ("Bajas", "Equipo destino"),
        }[self.direction]
        if (self.source_heading, self.source_team_column) != expected:
            raise ValueError("La sección de traspasos no coincide con su dirección.")
        if (self.status == "verified_empty") != (self.row_count == 0):
            raise ValueError("El estado vacío de la sección no coincide con el recuento.")
        return self


class TeamTransferRecordResponse(ApiModel):
    player_id: StrictInt = Field(gt=0)
    player_display_name: str = Field(min_length=1)
    player_full_name: str | None
    player_profile_url: str
    player_photo_url: str | None
    team_id: StrictInt = Field(gt=0)
    season: Literal["2026-27"]
    competition: Literal["Primera Federación"]
    group: Literal["I", "II"]
    direction: Literal["incoming", "outgoing"]
    other_team_name: str | None
    other_team_id: StrictInt | None = Field(default=None, gt=0)
    other_team_url: str | None
    age_years: StrictInt | None = Field(default=None, ge=0)
    source_position_code: str | None
    transfer_date: str | None
    fee: str | None
    source_view: Literal["transfers"]
    source_heading: Literal["Altas", "Bajas"]

    @model_validator(mode="after")
    def validate_transfer_record(self) -> TeamTransferRecordResponse:
        expected_heading = "Altas" if self.direction == "incoming" else "Bajas"
        if self.source_heading != expected_heading:
            raise ValueError("La dirección del movimiento no coincide con source_heading.")
        player_match = re.search(r"(?:^|/)j/j(\d+)\.html$", urlsplit(self.player_profile_url).path)
        if player_match is None or int(player_match.group(1)) != self.player_id:
            raise ValueError("player_profile_url no coincide con player_id.")
        for value in (self.player_profile_url, self.player_photo_url, self.other_team_url):
            if value is None:
                continue
            parsed = urlsplit(value)
            if parsed.scheme != "https" or parsed.hostname not in {"bdfutbol.com", "www.bdfutbol.com"}:
                raise ValueError("Las URL de traspasos deben apuntar a BDFutbol mediante HTTPS.")
        if self.other_team_url:
            team_match = re.search(r"(?:^|/)t\d{4}-\d{2}(\d+)\.html$", urlsplit(self.other_team_url).path)
            if team_match is None or self.other_team_id is None or int(team_match.group(1)) != self.other_team_id:
                raise ValueError("other_team_url no coincide con other_team_id.")
        elif self.other_team_id is not None:
            raise ValueError("other_team_id requiere una URL de origen/destino.")
        return self


class TeamTransfersMetadataResponse(ApiModel):
    contract_version: Literal[1]
    validation_status: Literal["valid"]
    source: Literal["BDFutbol"]
    url: str
    competition: Literal["Primera Federación"]
    competition_scope: Literal["Liga"]
    season: Literal["2026-27"]
    group: Literal["I", "II"]
    team_id: StrictInt = Field(gt=0)
    capture_id: str = Field(min_length=1)
    captured_at: datetime
    derived_at: datetime | None
    extractor_version: str
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class TeamTransfersResponse(ApiModel):
    status: Literal["available"]
    metadata: TeamTransfersMetadataResponse
    sections: list[TeamTransferSectionResponse]
    incoming: list[TeamTransferRecordResponse]
    outgoing: list[TeamTransferRecordResponse]
    warnings: list[str]

    @model_validator(mode="after")
    def validate_transfer_collections(self) -> TeamTransfersResponse:
        if self.metadata.team_id <= 0 or len(self.sections) != 2:
            raise ValueError("Metadatos o secciones de Traspasos incompletos.")
        section_by_direction = {item.direction: item for item in self.sections}
        if set(section_by_direction) != {"incoming", "outgoing"}:
            raise ValueError("Traspasos debe declarar Altas y Bajas por separado.")
        for direction, rows in (("incoming", self.incoming), ("outgoing", self.outgoing)):
            section = section_by_direction[direction]
            if section.row_count != len(rows):
                raise ValueError("El recuento de sección no coincide con los movimientos publicados.")
            if any(
                row.direction != direction
                or row.team_id != self.metadata.team_id
                or row.group != self.metadata.group
                or row.season != self.metadata.season
                for row in rows
            ):
                raise ValueError("Un movimiento pertenece a otra dirección o contexto.")
        keys = [(row.direction, row.player_id) for row in self.incoming + self.outgoing]
        if len(keys) != len(set(keys)):
            raise ValueError("Traspasos repite un jugador dentro de la misma dirección.")
        return self


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


class MatchGenerationRecordResponse(ApiModel):
    internal_id: str = Field(min_length=1)
    source_match_id: str = Field(min_length=1)
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
    source_match_url: str | None
    stadium_id: str | None
    stadium_name: str | None
    stadium_url: str | None
    referee_id: str | None
    referee_name: str | None
    referee_url: str | None

    @model_validator(mode="after")
    def validate_source_match(self) -> MatchGenerationRecordResponse:
        if self.home_team_id == self.away_team_id:
            raise ValueError("Un encuentro no puede enfrentar al mismo equipo.")
        if self.status == "played":
            if self.home_goals is None or self.away_goals is None or self.unplayed_state is not None:
                raise ValueError("El resultado disputado requiere marcador completo.")
        elif self.status == "unplayed":
            if self.home_goals is not None or self.away_goals is not None or self.unplayed_state is None:
                raise ValueError("El encuentro pendiente debe conservar marcador null.")
        elif self.unplayed_state is not None:
            raise ValueError("Un encuentro incompleto no puede usar estado pendiente.")
        if self.source_match_url is not None:
            parsed = urlsplit(self.source_match_url)
            if (
                parsed.scheme != "https"
                or parsed.hostname != "www.bdfutbol.com"
                or parsed.path != "/es/p/p.php"
                or parse_qs(parsed.query).get("id") != [self.source_match_id]
            ):
                raise ValueError("La URL de partido no coincide con su ID BDFutbol.")
        return self


class MatchGenerationTeamResponse(ApiModel):
    team_id: StrictInt = Field(gt=0)
    name: str = Field(min_length=1)
    team_url: str | None
    crest_url: str | None


class MatchGenerationCountsResponse(ApiModel):
    teams: StrictInt = Field(ge=0)
    matches: StrictInt = Field(ge=0)
    played: StrictInt = Field(ge=0)
    unplayed: StrictInt = Field(ge=0)
    incomplete: StrictInt = Field(ge=0)


class MatchGenerationGroupResponse(ApiModel):
    group: Literal["I", "II"]
    source_capture_id: str = Field(min_length=1)
    source_captured_at: datetime
    teams: list[MatchGenerationTeamResponse]
    matches: list[MatchGenerationRecordResponse]
    scheduled_matchdays: list[StrictInt]
    counts: MatchGenerationCountsResponse

    @model_validator(mode="after")
    def validate_group_dataset(self) -> MatchGenerationGroupResponse:
        team_ids = {team.team_id for team in self.teams}
        match_ids = [match.internal_id for match in self.matches]
        if len(team_ids) != len(self.teams) or len(match_ids) != len(set(match_ids)):
            raise ValueError("El grupo contiene IDs de equipo o partido repetidos.")
        if any(
            match.home_team_id not in team_ids or match.away_team_id not in team_ids
            for match in self.matches
        ):
            raise ValueError("Un partido referencia un equipo fuera de su grupo.")
        expected_prefix = f"pf-2026-27-group-{self.group.lower()}-bdfutbol-"
        if any(
            match.internal_id != f"{expected_prefix}{match.source_match_id}"
            for match in self.matches
        ):
            raise ValueError("El ID interno de un partido no coincide con su grupo y su ID de fuente.")
        if self.counts.teams != len(self.teams) or self.counts.matches != len(self.matches):
            raise ValueError("Los recuentos no coinciden con las colecciones del grupo.")
        actual = {
            "played": sum(match.status == "played" for match in self.matches),
            "unplayed": sum(match.status == "unplayed" for match in self.matches),
            "incomplete": sum(match.status == "incomplete" for match in self.matches),
        }
        if any(getattr(self.counts, key) != value for key, value in actual.items()):
            raise ValueError("Los recuentos por estado no coinciden con los partidos.")
        if self.scheduled_matchdays != sorted(set(self.scheduled_matchdays)):
            raise ValueError("Las jornadas deben ser únicas y estar ordenadas.")
        return self


class MatchGenerationMetadataResponse(ApiModel):
    schema_version: Literal[1]
    source: Literal["BDFutbol"]
    competition: Literal["Primera Federación"]
    season: Literal["2026-27"]
    generation_id: str = Field(min_length=1)
    generation_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    captured_at: datetime
    team_count: StrictInt = Field(ge=0)
    match_count: StrictInt = Field(ge=0)
    played_count: StrictInt = Field(ge=0)
    unplayed_count: StrictInt = Field(ge=0)
    incomplete_count: StrictInt = Field(ge=0)


class MatchGenerationBootstrapResponse(ApiModel):
    metadata: MatchGenerationMetadataResponse
    groups: dict[Literal["I", "II"], MatchGenerationGroupResponse]

    @model_validator(mode="after")
    def validate_generation_scope(self) -> MatchGenerationBootstrapResponse:
        if set(self.groups) != {"I", "II"}:
            raise ValueError("La generación debe contener Grupo I y Grupo II.")
        teams = sum(group.counts.teams for group in self.groups.values())
        matches = sum(group.counts.matches for group in self.groups.values())
        if teams != self.metadata.team_count or matches != self.metadata.match_count:
            raise ValueError("Los totales de generación no coinciden con los grupos.")
        internal_ids = [
            match.internal_id
            for group in self.groups.values()
            for match in group.matches
        ]
        if len(internal_ids) != len(set(internal_ids)):
            raise ValueError("La generación contiene IDs internos de partido repetidos.")
        return self


class MatchPageTeamResponse(ApiModel):
    team_id: StrictInt = Field(gt=0)
    name: str = Field(min_length=1)
    team_url: str | None
    crest_url: str | None


class MatchPublishedPlayerResponse(ApiModel):
    player_id: OptionalInt = Field(default=None, gt=0)
    display_name: str = Field(min_length=1)
    profile_url: str | None
    photo_url: str | None
    shirt_number: OptionalInt = Field(default=None, ge=0)
    position: str | None
    role: Literal["starter", "substitute"]
    participation_status: Literal["entered", "no_entry_marker", "not_applicable"] | None = None
    player_profile_available: bool = False


class MatchPublishedCoachResponse(ApiModel):
    coach_id: OptionalInt = Field(default=None, gt=0)
    display_name: str = Field(min_length=1)
    profile_url: str | None
    photo_url: str | None


class MatchPublishedSideResponse(ApiModel):
    team_id: StrictInt = Field(gt=0)
    coach: MatchPublishedCoachResponse | None
    starters: list[MatchPublishedPlayerResponse] | None
    substitutes: list[MatchPublishedPlayerResponse] | None


class MatchPublishedEventResponse(ApiModel):
    event_kind: Literal[
        "goal", "penalty", "own_goal", "yellow_card", "red_card",
        "second_yellow", "substitution", "substitution_in", "substitution_out", "other",
    ]
    minute: str | None
    team_id: StrictInt = Field(gt=0)
    player_id: OptionalInt = Field(default=None, gt=0)
    player_name: str | None
    related_player_id: OptionalInt = Field(default=None, gt=0)
    related_player_name: str | None
    is_penalty: bool | None
    is_own_goal: bool | None
    score_after_home: OptionalInt = Field(default=None, ge=0)
    score_after_away: OptionalInt = Field(default=None, ge=0)
    player_profile_available: bool = False
    related_player_profile_available: bool = False


class MatchPublishedDetailsResponse(ApiModel):
    """Public projection for details explicitly validated and approved for publication."""

    publication_status: Literal["approved", "preview_only"]
    validation_status: Literal["valid"]
    source: Literal["BDFutbol"]
    internal_id: str = Field(min_length=1)
    source_match_id: str = Field(min_length=1)
    source_generation_id: str = Field(min_length=1)
    source_capture_id: str = Field(min_length=1)
    source_html_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    match_date: date | None
    home_team_id: StrictInt = Field(gt=0)
    away_team_id: StrictInt = Field(gt=0)
    home_goals: StrictInt = Field(ge=0)
    away_goals: StrictInt = Field(ge=0)
    home: MatchPublishedSideResponse
    away: MatchPublishedSideResponse
    events: list[MatchPublishedEventResponse] | None


class MatchPageMetadataResponse(ApiModel):
    contract_version: Literal[2]
    source: Literal["BDFutbol"]
    competition: Literal["Primera Federación"]
    season: Literal["2026-27"]
    group: Literal["I", "II"]
    generation_id: str = Field(min_length=1)
    generation_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_capture_id: str = Field(min_length=1)
    source_captured_at: datetime


class MatchPageRecordResponse(ApiModel):
    internal_id: str = Field(pattern=r"^pf-2026-27-group-(?:i|ii)-bdfutbol-\d+$")
    source_match_id: str = Field(pattern=r"^\d+$")
    matchday: StrictInt = Field(ge=1, le=38)
    matchday_date: date | None
    source_match_date: date | None
    home_team: MatchPageTeamResponse
    away_team: MatchPageTeamResponse
    home_goals: OptionalInt
    away_goals: OptionalInt
    status: Literal["played", "unplayed", "incomplete"]
    unplayed_state: Literal[
        "scheduled", "result_unavailable_at_capture", "unknown"
    ] | None
    stadium_name: str | None
    stadium_url: str | None
    referee_name: str | None
    referee_url: str | None
    source_match_url: str | None

    @model_validator(mode="after")
    def validate_score_state(self) -> MatchPageRecordResponse:
        if self.home_team.team_id == self.away_team.team_id:
            raise ValueError("El partido no puede enfrentar al mismo equipo.")
        if self.status == "played" and (self.home_goals is None or self.away_goals is None):
            raise ValueError("Un partido disputado requiere ambos marcadores, incluido 0–0.")
        if self.status == "unplayed" and (
            self.home_goals is not None or self.away_goals is not None or self.unplayed_state is None
        ):
            raise ValueError("Un partido pendiente debe conservar marcadores nulos y su estado.")
        if self.status == "incomplete" and (
            self.home_goals is not None or self.away_goals is not None or self.unplayed_state is not None
        ):
            raise ValueError("Un partido incompleto no puede publicar marcador ni estado pendiente.")
        if self.source_match_url is not None:
            parsed = urlsplit(self.source_match_url)
            if (
                parsed.scheme != "https"
                or parsed.hostname != "www.bdfutbol.com"
                or parsed.path != "/es/p/p.php"
                or parse_qs(parsed.query).get("id") != [self.source_match_id]
            ):
                raise ValueError("La URL externa no coincide con el ID de partido.")
        return self


class MatchPageResponse(ApiModel):
    metadata: MatchPageMetadataResponse
    match: MatchPageRecordResponse
    detail_status: Literal["not_available", "available", "preview_only"]
    details: MatchPublishedDetailsResponse | None

    @model_validator(mode="after")
    def validate_identity_and_publication(self) -> MatchPageResponse:
        expected_group = "i" if self.metadata.group == "I" else "ii"
        if f"-group-{expected_group}-" not in self.match.internal_id:
            raise ValueError("El partido y la metadata no pertenecen al mismo grupo.")
        if self.match.internal_id != (
            f"pf-2026-27-group-{self.metadata.group.lower()}-bdfutbol-"
            f"{self.match.source_match_id}"
        ):
            raise ValueError("El ID interno no coincide con la identidad del partido.")
        if (self.detail_status == "not_available") == (self.details is not None):
            raise ValueError("El estado de detalles no coincide con el contenido publicado.")
        if self.details is not None and (
            (self.detail_status == "available" and self.details.publication_status != "approved")
            or (self.detail_status == "preview_only" and self.details.publication_status != "preview_only")
        ):
            raise ValueError("El estado de detalles no coincide con su aprobación.")
        if self.details is not None and (
            self.details.internal_id != self.match.internal_id
            or self.details.source_match_id != self.match.source_match_id
            or self.details.source_generation_id != self.metadata.generation_id
            or self.details.source_capture_id != self.metadata.source_capture_id
            or self.details.home_team_id != self.match.home_team.team_id
            or self.details.away_team_id != self.match.away_team.team_id
            or self.details.home.team_id != self.match.home_team.team_id
            or self.details.away.team_id != self.match.away_team.team_id
            or self.details.home_goals != self.match.home_goals
            or self.details.away_goals != self.match.away_goals
            or (self.match.source_match_date is not None and self.details.match_date != self.match.source_match_date)
        ):
            raise ValueError("Los detalles aprobados no corresponden a la generación y partido solicitados.")
        if self.details is not None and any(
            event.team_id not in {self.match.home_team.team_id, self.match.away_team.team_id}
            for event in (self.details.events or [])
        ):
            raise ValueError("Un evento aprobado referencia un equipo que no disputa el partido.")
        return self


PlayerScalar = str | int | float | bool | None


class PlayerTeamAssociationResponse(ApiModel):
    team_id: StrictInt = Field(gt=0)
    team_name: str = Field(min_length=1)
    group: Literal["I", "II"]
    evidence_types: list[Literal["membership", "transfer_reference"]]


class PlayerIndexRecordResponse(ApiModel):
    player_id: StrictInt = Field(gt=0)
    display_name: str | None
    full_name: str | None
    profile_url: str | None
    photo_url: str | None
    birth_date: date | None
    age_years: OptionalInt = Field(default=None, ge=0)
    nationality: str | None
    position_name: str | None
    groups: list[Literal["I", "II"]]
    association_status: Literal["roster_membership_observed", "transfer_reference_only"]
    team_associations: list[PlayerTeamAssociationResponse]
    profile_status: Literal[
        "four_views_verified", "partial_individual_views", "inventory_only"
    ]


class PlayerTeamFilterResponse(ApiModel):
    team_id: StrictInt = Field(gt=0)
    team_name: str = Field(min_length=1)
    group: Literal["I", "II"]


class PlayerDirectoryMetadataResponse(ApiModel):
    season: Literal["2026-27"]
    inventory_generated_at: datetime
    inventory_player_count: StrictInt = Field(ge=0)
    complete_individual_profile_count: StrictInt = Field(ge=0)
    partial_individual_profile_count: StrictInt = Field(ge=0)
    inventory_only_count: StrictInt = Field(ge=0)
    roster_membership_count: StrictInt = Field(ge=0)
    transfer_only_count: StrictInt = Field(ge=0)
    compact_generation_id: str | None
    compact_generated_at: datetime | None
    inventory_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class PlayerDirectoryResponse(ApiModel):
    metadata: PlayerDirectoryMetadataResponse
    available_teams: list[PlayerTeamFilterResponse]
    query: str
    group: Literal["I", "II"] | None
    team_id: StrictInt | None
    page: StrictInt = Field(ge=1)
    page_size: StrictInt = Field(ge=1, le=100)
    total: StrictInt = Field(ge=0)
    players: list[PlayerIndexRecordResponse]


class PlayerSeasonStatisticResponse(ApiModel):
    team_id: StrictInt = Field(gt=0)
    team_name: str | None
    group: Literal["I", "II"]
    matches_played: OptionalInt
    starts: OptionalInt
    minutes_played: OptionalInt
    goals: OptionalInt
    assists: OptionalInt
    yellow_cards: OptionalInt
    red_cards: OptionalInt
    source_view: str | None


class PlayerMatchMetricResponse(ApiModel):
    team_id: StrictInt = Field(gt=0)
    team_name: str | None
    group: Literal["I", "II"]
    match_id: str | None
    matchday: StrictInt = Field(ge=1, le=38)
    metric: str | None
    value: StrictInt = Field(ge=0)
    raw_value: str | None
    source_state: str | None
    captured_at: datetime | None


class PlayerIdentityConflictResponse(ApiModel):
    field: str = Field(min_length=1)
    inventory_value: str
    individual_profile_value: str
    selected_source: Literal["individual_profile"]


class PlayerIdentityResponse(ApiModel):
    display_name: str | None
    full_name: str | None
    birth_date: date | None
    age_years: OptionalInt = Field(default=None, ge=0)
    birth_place: str | None
    birth_place_raw: str | None
    birthplace_province: str | None
    country_of_birth: str | None
    nationality: str | None
    position_name: str | None
    height_cm: StrictInt | StrictFloat | None
    height_raw: str | None
    weight_kg: StrictInt | StrictFloat | None
    weight_raw: str | None
    field_sources: dict[str, Literal["inventory", "individual_profile", "unavailable"]]
    inventory_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    individual_profile_source_url: str | None
    individual_profile_captured_at: datetime | None
    individual_profile_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    conflicts: list[PlayerIdentityConflictResponse]


class PlayerMembershipHistoryResponse(ApiModel):
    team_id: StrictInt = Field(gt=0)
    team_name: str = Field(min_length=1)
    group: Literal["I", "II"]
    season: Literal["2026-27"]
    captured_at: datetime | None
    capture_id: str | None
    jersey_number: OptionalInt
    squad_group_label: str | None
    source_views: list[str]


class PlayerTransferEvidenceResponse(ApiModel):
    capture_id: str | None
    captured_at: datetime | None
    source_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    source_record_index: OptionalInt
    team_id: StrictInt = Field(gt=0)
    group: Literal["I", "II"] | None
    direction: Literal["incoming", "outgoing"]


class PlayerClubReferenceResponse(ApiModel):
    status: Literal["observed", "not_confirmed"]
    team_id: StrictInt | None
    team_name: str | None
    group: Literal["I", "II"] | None
    observed_at: datetime | None
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_observed_club(self) -> PlayerClubReferenceResponse:
        fields = (self.team_id, self.team_name, self.group)
        if self.status == "observed" and any(value is None for value in fields):
            raise ValueError("Un club observado requiere ID, nombre y grupo.")
        if self.status == "not_confirmed" and any(value is not None for value in fields):
            raise ValueError("Un club no confirmado no puede publicar una identidad elegida.")
        return self


class PlayerClubMovementResponse(ApiModel):
    from_team_id: StrictInt = Field(gt=0)
    from_team_name: str = Field(min_length=1)
    from_group: Literal["I", "II"] | None
    to_team_id: StrictInt = Field(gt=0)
    to_team_name: str = Field(min_length=1)
    to_group: Literal["I", "II"] | None
    season: Literal["2026-27"]
    transfer_date: date | None
    observed_at: datetime | None
    evidence_count: StrictInt = Field(ge=1)
    evidence: list[PlayerTransferEvidenceResponse] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_movement(self) -> PlayerClubMovementResponse:
        if self.from_team_id == self.to_team_id:
            raise ValueError("Un movimiento no puede conectar un equipo consigo mismo.")
        if self.evidence_count != len(self.evidence):
            raise ValueError("El recuento de evidencias del movimiento no coincide.")
        return self


class PlayerTransferReferenceResponse(ApiModel):
    team_id: StrictInt = Field(gt=0)
    team_name: str | None
    group: Literal["I", "II"]
    direction: Literal["incoming", "outgoing"]
    other_team_name: str | None
    other_team_id: StrictInt | None
    source_position_code: str | None
    age_years: OptionalInt
    transfer_date: date | None
    capture_id: str | None
    captured_at: datetime | None
    source_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    source_record_index: OptionalInt


class PlayerTableColumnResponse(ApiModel):
    label: str = Field(min_length=1)
    source_header: str | None
    title: str | None
    hidden_in_source: bool
    source_index: StrictInt | None = None
    group_header: str | None = None
    data_colid: str | None = None


class PlayerTableCellResponse(ApiModel):
    raw_value: PlayerScalar
    normalized_integer: StrictInt | None
    value_status: str | None


class PlayerTableRowResponse(ApiModel):
    context: dict[str, PlayerScalar]
    cells: list[PlayerTableCellResponse]
    source_fields: dict[str, Any] = Field(default_factory=dict)
    internal_player_id: StrictInt | None = Field(default=None, gt=0)


class PlayerMatchStatisticResponse(ApiModel):
    label: str = Field(min_length=1)
    raw_value: str | StrictInt | StrictFloat | None
    normalized_integer: OptionalInt


class PlayerCompactTableResponse(ApiModel):
    table_role: str
    source_table_index: StrictInt | None
    table_id: str | None = None
    schema_id: str | None = None
    columns: list[PlayerTableColumnResponse]
    rows: list[PlayerTableRowResponse]


class PlayerHistoricalMatchResponse(ApiModel):
    match_id: str | None
    match_url: str | None
    date: date | None
    date_raw: str | None
    season: str | None
    competition: str | None
    round_label: str | None
    player_team: str | None
    opponent_team: str | None
    side: str | None
    home_goals: OptionalInt = None
    away_goals: OptionalInt = None
    home_team_id: StrictInt | None = Field(default=None, gt=0)
    away_team_id: StrictInt | None = Field(default=None, gt=0)
    minutes: StrictInt | None
    match_state: str | None
    appearance_status: str | None
    participation: str = "Sin participación registrada"
    match_statistics: list[PlayerMatchStatisticResponse] = Field(default_factory=list)
    source_fields: dict[str, Any] = Field(default_factory=dict)


class PlayerIndividualViewResponse(ApiModel):
    view: Literal["profile", "statistics", "matches", "rivals"]
    source_url: str
    captured_at: datetime | None
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    scope_note: str
    tables: list[PlayerCompactTableResponse]
    profile: dict[str, Any] | None = None
    coverage: dict[str, Any] | None = None
    historical_matches: list[PlayerHistoricalMatchResponse]
    summoned_without_participation: list[PlayerHistoricalMatchResponse] = Field(default_factory=list)
    other_match_records: list[PlayerHistoricalMatchResponse] = Field(default_factory=list)
    record_counts: dict[str, Any] = Field(default_factory=dict)
    individual_matches_source: str | None = None
    window_p_parse_status: str | None = None
    window_p_record_count: StrictInt | None = None
    detail_coverage: str | None = None
    exhaustiveness_status: str | None = None
    filter_parameters: dict[str, Any] = Field(default_factory=dict)
    filtered_view: bool | None = None


class PlayerDetailResponse(ApiModel):
    metadata: PlayerDirectoryMetadataResponse
    player: PlayerIndexRecordResponse
    identity: PlayerIdentityResponse
    club_reference: PlayerClubReferenceResponse
    last_observed_movement: PlayerClubMovementResponse | None
    movement_resolution: Literal["identified", "ambiguous", "none"]
    birth_place: str | None
    birthplace_province: str | None
    nationality_flag_url: str | None
    verified_indicators: list[str]
    associations: list[PlayerTeamAssociationResponse]
    membership_history: list[PlayerMembershipHistoryResponse]
    transfer_references: list[PlayerTransferReferenceResponse]
    season_statistics: list[PlayerSeasonStatisticResponse]
    match_minutes: list[PlayerMatchMetricResponse]
    match_metrics: list[PlayerMatchMetricResponse]
    verified_individual_views: list[PlayerIndividualViewResponse]
    warnings: list[str]

    @model_validator(mode="after")
    def validate_player_detail(self) -> PlayerDetailResponse:
        if self.player.profile_status == "four_views_verified":
            views = {item.view for item in self.verified_individual_views}
            if views != {"profile", "statistics", "matches", "rivals"}:
                raise ValueError("Un perfil completo debe incluir las cuatro vistas verificadas.")
        elif self.player.profile_status == "inventory_only" and self.verified_individual_views:
            raise ValueError("Un jugador sin compacto verificado no puede declarar vistas completas.")
        elif self.player.profile_status == "partial_individual_views" and not self.verified_individual_views:
            raise ValueError("Un perfil parcial debe incluir al menos una vista verificada.")
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
    # Set only by the API after corroborating the source ID against the local player inventory.
    internal_player_id: StrictInt | None = None
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
    # Set only by the API after corroborating the source ID against the local player inventory.
    internal_player_id: StrictInt | None = None
    statistics: TopForeignStatistics


class TopForeignersSummary(TopApiModel):
    source_count: StrictInt = Field(ge=0)
    available_count: StrictInt = Field(ge=0)
    missing_count: StrictInt = Field(ge=0)
    coverage_status: Literal["complete", "documented_discrepancy"]
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


class TopAffiliationAbsence(TopApiModel):
    player_id: StrictInt = Field(gt=0)
    source_records: list[str] = Field(min_length=1)
    reason: Literal["not_published"]


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
    affiliation_absences: list[TopAffiliationAbsence]


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
    related_matches_path: str = Field(
        description="Ruta declarada por REF-01 para su referencia histórica de Grupo II."
    )
    related_matches_sha256: str = Field(
        description="Hash declarado por REF-01 para la misma referencia histórica de Grupo II."
    )
    related_matches_capture_id: str = Field(
        description="ID de la referencia histórica de Grupo II declarada por REF-01."
    )
    related_matches_captured_at: datetime = Field(
        description="Fecha de captura de la referencia histórica de Grupo II declarada por REF-01."
    )
    match_reference_status: Literal["consistent", "discrepancies"] = Field(
        description="Estado del informe histórico REF-01 de Grupo II."
    )
    related_match_datasets: dict[str, "RefereeRelatedMatchDataset"] = Field(
        description="Referencias de partidos por grupo que pasaron la verificación activa de procedencia."
    )


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
