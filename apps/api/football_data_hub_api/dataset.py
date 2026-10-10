"""Load, validate, and hold one compatible capture bundle in memory."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from football_data_hub_api.config import ApiSettings
from football_data_hub_api.schemas import (
    AvailabilitySummary,
    BootstrapResponse,
    DatasetMetadata,
    MatchResponse,
    ProgressContextResponse,
    ProgressResponse,
    PublishedStandingResponse,
    PublishedStandingsContext,
    PublishedStandingsResponseModel,
    TeamResponse,
)

EXPECTED_TEAM_COUNT = 20
EXPECTED_MATCHDAY_COUNT = 38
EXPECTED_MATCHES_PER_MATCHDAY = 10


class DatasetLoadError(ValueError):
    """Raised when configured JSON files cannot form one valid API dataset."""


@dataclass(frozen=True, slots=True)
class DatasetBundle:
    bootstrap: BootstrapResponse
    etag: str


def load_dataset(settings: ApiSettings) -> DatasetBundle:
    """Read configured files once and reject mixed or incomplete captures."""

    raw_bytes = [
        _read_bytes(settings.matches_path),
        _read_bytes(settings.classification_path),
        _read_bytes(settings.progress_path),
        _read_bytes(settings.capture_metadata_path),
    ]
    matches_data, classification_data, progress_data, capture_data = [
        _decode_json(payload, path)
        for payload, path in zip(
            raw_bytes,
            (
                settings.matches_path,
                settings.classification_path,
                settings.progress_path,
                settings.capture_metadata_path,
            ),
            strict=True,
        )
    ]

    _check_schema_versions(matches_data, classification_data, progress_data)
    expected_group = settings.group
    _check_capture_compatibility(
        matches_data, classification_data, progress_data, capture_data, expected_group
    )

    try:
        teams = [TeamResponse.model_validate(_team_public_fields(item)) for item in matches_data["teams"]]
        matches = [
            MatchResponse.model_validate(_match_public_fields(item))
            for item in matches_data["matches"]
        ]
        progress = [
            ProgressResponse.model_validate(item) for item in progress_data["records"]
        ]
        standings = [
            PublishedStandingResponse.model_validate(_standing_public_fields(item))
            for item in classification_data["standings"]
        ]
        context_data = classification_data["context"]
        standings_context = PublishedStandingsContext.model_validate(
            {
                key: context_data.get(key)
                for key in (
                    "classification_type",
                    "matchday",
                    "matchday_date",
                    "postponed_policy",
                    "range_type",
                )
            }
        )
    except (KeyError, TypeError, ValidationError) as exc:
        raise DatasetLoadError("Los campos de los datasets no cumplen el contrato esperado") from exc

        _validate_integrity(
        matches_data,
        matches,
        teams,
        progress,
        standings,
        progress_data,
        matches_data["metadata"],
    )

    capture_id = str(capture_data["capture_id"])
    dataset_digest = hashlib.sha256(b"\n".join(raw_bytes)).hexdigest()[:12]
    dataset_version = f"{capture_id}-{dataset_digest}"
    match_counts = Counter(match.status for match in matches)
    scheduled_matchdays = sorted({match.matchday for match in matches})
    last_matchday = max(
        (match.matchday for match in matches if match.status == "played"),
        default=None,
    )
    progress_through = int(progress_data["series_context"]["available_through_matchday"])

    warnings = _quality_warnings(matches_data, progress)
    metadata = DatasetMetadata(
        schema_version=1,
        source=str(capture_data["source"]),
        url=str(capture_data["url"]),
        competition=str(capture_data["competition"]),
        season=str(capture_data["season"]),
        group=str(capture_data["group"]),
        team_count=len(teams),
        scheduled_matchdays=scheduled_matchdays,
        last_matchday_with_results=last_matchday,
        captured_at=datetime.fromisoformat(str(capture_data["captured_at_utc"])),
        capture_id=capture_id,
        dataset_version=dataset_version,
        availability=AvailabilitySummary(
            teams=len(teams),
            matches=len(matches),
            played_matches=match_counts["played"],
            unplayed_matches=match_counts["unplayed"],
            incomplete_matches=match_counts["incomplete"],
            matchdays_with_fixtures=scheduled_matchdays,
            last_matchday_with_results=last_matchday,
            progress_records=len(progress),
            progress_through_matchday=progress_through,
            published_standings_available=bool(standings),
        ),
        progress_context=ProgressContextResponse.model_validate(
            progress_data["series_context"]
        ),
        warnings=warnings,
    )
    published_standings = PublishedStandingsResponseModel(
        source=str(classification_data["metadata"]["source"]),
        source_capture_id=capture_id,
        context=standings_context,
        rows=standings,
    )
    bootstrap = BootstrapResponse(
        metadata=metadata,
        teams=teams,
        matches=matches,
        progress=progress,
        published_standings=published_standings,
    )
    return DatasetBundle(bootstrap=bootstrap, etag=f'"{dataset_version}"')


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise DatasetLoadError("No se pudo leer uno de los archivos de datos configurados") from exc


def _decode_json(payload: bytes, path: Path) -> dict[str, Any]:
    try:
        result = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DatasetLoadError("Uno de los archivos de datos no contiene JSON válido") from exc
    if not isinstance(result, dict):
        raise DatasetLoadError("Cada archivo de datos debe contener un objeto JSON")
    return result


def _check_schema_versions(
    matches: dict[str, Any], classification: dict[str, Any], progress: dict[str, Any]
) -> None:
    if matches.get("schema_version") not in {1, 2}:
        raise DatasetLoadError("La versión de matches.json no es compatible")
    if any(
        dataset.get("schema_version") != 1
        for dataset in (classification, progress)
    ):
        raise DatasetLoadError("Hay una versión de clasificación o progreso no compatible")
    if matches["schema_version"] == 2:
        enrichment_fields = {
            "source_match_url",
            "stadium_id",
            "stadium_name",
            "stadium_url",
            "referee_id",
            "referee_name",
            "referee_url",
        }
        records = matches.get("matches")
        if not isinstance(records, list) or any(
            not isinstance(record, dict) or not enrichment_fields.issubset(record)
            for record in records
        ):
            raise DatasetLoadError(
                "matches.json v2 no contiene todos los campos de enriquecimiento"
            )


def _check_capture_compatibility(
    matches: dict[str, Any],
    classification: dict[str, Any],
    progress: dict[str, Any],
    capture: dict[str, Any],
    expected_group: str,
) -> None:
    try:
        capture_id = capture["capture_id"]
        capture_metadata = matches["metadata"]
        classification_metadata = classification["metadata"]
        progress_metadata = progress["metadata"]
        reference_ids = {
            capture_id,
            capture_metadata["source_capture_id"],
            classification_metadata["capture_id"],
            progress_metadata["capture_id"],
        }
    except (KeyError, TypeError) as exc:
        raise DatasetLoadError("Faltan metadatos de procedencia necesarios") from exc
    if len(reference_ids) != 1 or not all(reference_ids):
        raise DatasetLoadError("Los JSON no pertenecen a la misma captura de origen")
    if capture.get("group") != expected_group:
        raise DatasetLoadError(
            f"La captura configurada para Grupo {expected_group} contiene datos de otro grupo"
        )

    for key in ("source", "url", "competition", "season", "group"):
        expected = capture.get(key)
        if any(
            metadata.get(key) != expected
            for metadata in (capture_metadata, classification_metadata, progress_metadata)
        ):
            raise DatasetLoadError(f"Los metadatos de {key} no coinciden entre capturas")

    context = classification.get("context")
    if not isinstance(context, dict) or context.get("classification_type") != "general":
        raise DatasetLoadError("La tabla publicada no representa la clasificación general")
    if context.get("matchday") is None:
        raise DatasetLoadError("La tabla publicada no tiene una jornada de referencia")


def _validate_integrity(
    matches_data: dict[str, Any],
    matches: list[MatchResponse],
    teams: list[TeamResponse],
    progress: list[ProgressResponse],
    standings: list[PublishedStandingResponse],
    progress_data: dict[str, Any],
    match_metadata: dict[str, Any],
) -> None:
    if len(teams) != EXPECTED_TEAM_COUNT:
        raise DatasetLoadError("El catálogo del grupo activo debe contener 20 equipos")
    team_ids = [team.team_id for team in teams]
    team_id_set = set(team_ids)
    if len(team_id_set) != len(team_ids):
        raise DatasetLoadError("Hay identificadores de equipo duplicados")

    match_ids = [match.match_id for match in matches]
    if len(match_ids) != len(set(match_ids)):
        raise DatasetLoadError("Hay identificadores de partido duplicados")
    if len(matches) != EXPECTED_MATCHDAY_COUNT * EXPECTED_MATCHES_PER_MATCHDAY:
        raise DatasetLoadError("El calendario debe contener los 380 partidos programados")
    matchday_counts = Counter(match.matchday for match in matches)
    if set(matchday_counts) != set(range(1, EXPECTED_MATCHDAY_COUNT + 1)) or any(
        count != EXPECTED_MATCHES_PER_MATCHDAY for count in matchday_counts.values()
    ):
        raise DatasetLoadError("El calendario no cubre diez partidos en cada jornada")
    if any(
        match.home_team_id not in team_id_set or match.away_team_id not in team_id_set
        for match in matches
    ):
        raise DatasetLoadError("Un partido referencia un equipo que no existe")

    counts = matches_data.get("counts", {})
    computed_counts = Counter(match.status for match in matches)
    if counts.get("matches") != len(matches) or any(
        counts.get(status) != computed_counts[status]
        for status in ("played", "unplayed", "incomplete")
    ):
        raise DatasetLoadError("Los contadores de matches.json no coinciden con sus registros")

    if {row.team_id for row in standings} != team_id_set or len(standings) != EXPECTED_TEAM_COUNT:
        raise DatasetLoadError("La tabla publicada y el catálogo no tienen los mismos equipos")
    standings_by_id = {row.team_id: row for row in standings}
    if any(
        standings_by_id[team.team_id].team_name != team.name
        or standings_by_id[team.team_id].team_url != team.team_url
        or standings_by_id[team.team_id].crest_url != team.crest_url
        for team in teams
    ):
        raise DatasetLoadError("El catálogo y la tabla publicada discrepan en datos de equipo")
    progress_pairs = [(record.team_id, record.matchday) for record in progress]
    if len(progress_pairs) != len(set(progress_pairs)):
        raise DatasetLoadError("Hay registros de progreso duplicados")
    if any(record.team_id not in team_id_set for record in progress):
        raise DatasetLoadError("Una serie de progreso referencia un equipo desconocido")
    through = progress_data.get("series_context", {}).get("available_through_matchday")
    if not isinstance(through, int) or through < 1 or through > EXPECTED_MATCHDAY_COUNT:
        raise DatasetLoadError("Los metadatos de progreso no indican una jornada válida")
    if len(progress) != EXPECTED_TEAM_COUNT * through:
        raise DatasetLoadError("El progreso no contiene un registro por equipo y jornada")
    expected_pairs = {
        (team_id, matchday)
        for team_id in team_id_set
        for matchday in range(1, through + 1)
    }
    if set(progress_pairs) != expected_pairs:
        raise DatasetLoadError("El progreso tiene huecos o jornadas fuera de su cobertura")

    matchday_dates = match_metadata.get("matchday_dates", {})
    for match in matches:
        source_date = matchday_dates.get(str(match.matchday))
        if source_date and match.matchday_date != date.fromisoformat(source_date):
            raise DatasetLoadError("La fecha de jornada de un partido no coincide con metadatos")


def _team_public_fields(team: dict[str, Any]) -> dict[str, Any]:
    return {
        "team_id": team.get("team_id"),
        "name": team.get("name"),
        "team_url": team.get("team_url"),
        "crest_url": team.get("crest_url"),
    }


def _match_public_fields(match: dict[str, Any]) -> dict[str, Any]:
    return {
        key: match.get(key)
        for key in (
            "match_id",
            "matchday",
            "matchday_date",
            "source_match_date",
            "home_team_id",
            "away_team_id",
            "home_goals",
            "away_goals",
            "home_yellow_cards",
            "away_yellow_cards",
            "home_red_cards",
            "away_red_cards",
            "status",
            "unplayed_state",
            "postponed_by_source_rule",
            "source_match_url",
            "stadium_id",
            "stadium_name",
            "stadium_url",
            "referee_id",
            "referee_name",
            "referee_url",
        )
    }


def _standing_public_fields(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row.get(key)
        for key in (
            "team_id",
            "team_name",
            "team_url",
            "crest_url",
            "position",
            "points",
            "matches_played",
            "wins",
            "draws",
            "losses",
            "goals_for",
            "goals_against",
            "yellow_cards",
            "red_cards",
            "position_change",
            "sports_zone",
        )
    }


def _quality_warnings(
    matches_data: dict[str, Any], progress: list[ProgressResponse]
) -> list[str]:
    warnings: list[str] = []
    unplayed_states = matches_data.get("counts", {}).get("unplayed_states", {})
    unavailable = int(unplayed_states.get("result_unavailable_at_capture", 0))
    if unavailable:
        warnings.append(
            f"{unavailable} encuentro(s) no tenía(n) resultado en la captura; no se interpretan como 0-0."
        )
    if matches_data.get("counts", {}).get("postponed_by_source_rule", 0) == 0:
        warnings.append(
            "La captura no contiene un partido que active la regla de aplazamiento de BDFutbol."
        )
    null_progress_values = sum(
        value is None
        for record in progress
        for value in (record.position, record.points, record.goals_for, record.goals_against)
    )
    if null_progress_values:
        warnings.append(
            f"El progreso conserva {null_progress_values} valor(es) null publicados por la fuente."
        )
    return warnings
