"""Load and validate the independent BDFutbol TOP capture at API startup."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from football_data_hub_api.config import ApiSettings, DEFAULT_TOP_CAPTURE, PROJECT_ROOT
from football_data_hub_api.schemas import (
    TopAffiliationConflict,
    TopAffiliationAbsence,
    TopAvailability,
    TopBootstrapResponse,
    TopCaptureMetadata,
    TopCategoryOption,
    TopCountryOption,
    TopForeignPlayerResponse,
    TopForeignStatistics,
    TopForeignersSummary,
    TopPlayerResponse,
    TopProgressSeries,
    TopRankingResponse,
    TeamResponse,
)


class TopDatasetLoadError(ValueError):
    """Raised when TOP files cannot form a verified independent capture."""


TOP_BOOTSTRAP_SCHEMA_VERSION = 3


@dataclass(frozen=True, slots=True)
class TopDatasetBundle:
    bootstrap: TopBootstrapResponse
    etag: str


@dataclass(frozen=True, slots=True)
class _ForeignersCoverage:
    source_count: int
    available_count: int
    missing_count: int
    status: Literal["complete", "documented_discrepancy"]


@dataclass(frozen=True, slots=True)
class _TopAffiliationValidation:
    conflicts: list[TopAffiliationConflict]
    absences: list[TopAffiliationAbsence]


_CATEGORY_BY_SOURCE_VALUE = {
    "1": "goals",
    "2": "minutes",
    "3": "yellow_cards",
    "4": "red_cards",
    "8": "youngest",
    "9": "oldest",
}
_CATEGORY_BY_NAME = {value: value for value in _CATEGORY_BY_SOURCE_VALUE.values()}
_METRIC_BY_CATEGORY = {
    "goals": "goals",
    "minutes": "minutes_played",
    "yellow_cards": "yellow_cards",
    "red_cards": "red_cards",
    "youngest": "age_years",
    "oldest": "age_years",
}
_UNIT_BY_CATEGORY = {
    "goals": "goals",
    "minutes": "minutes",
    "yellow_cards": "cards",
    "red_cards": "cards",
    "youngest": "years",
    "oldest": "years",
}
_PROGRESS_CATEGORIES = {"goals", "minutes", "yellow_cards", "red_cards"}
_EXPECTED_SEASON = "2026-27"


class _SourceForeignPlayer(TopPlayerResponse):
    """Full provider record retained for integrity checks, omitted from the API."""

    statistics: TopForeignStatistics


def load_top_dataset(
    settings: ApiSettings,
    *,
    active_teams: list[TeamResponse] | None = None,
    active_team_capture_id: str | None = None,
) -> TopDatasetBundle:
    paths = _top_paths(settings)
    files = {name: _read_bytes(path) for name, path in paths.items()}
    decoded = {
        name: _decode_json(files[name], paths[name])
        for name in (
            "players",
            "rankings",
            "progress",
            "foreigners",
            "capture",
            "validation",
            "teams",
        )
    }
    _validate_capture_metadata(decoded, settings.group)
    _validate_source_snapshot(files["source_html"], decoded["capture"])
    team_catalog_digest = hashlib.sha256(files["teams"]).hexdigest()
    team_catalog = decoded["players"]["metadata"].get("related_team_catalog")
    if not isinstance(team_catalog, dict):
        raise TopDatasetLoadError("La captura TOP no declara procedencia del catálogo de equipos")
    if team_catalog.get("sha256") != team_catalog_digest:
        raise TopDatasetLoadError(
            "El hash del catálogo de equipos no coincide con la referencia TOP; no se asociarán jugadores por nombre"
        )
    capture_team_catalog = decoded["capture"].get("related_team_catalog")
    if not isinstance(capture_team_catalog, dict) or capture_team_catalog != team_catalog:
        raise TopDatasetLoadError("Los metadatos de captura y los datos normalizados no coinciden en el catálogo original")
    if capture_team_catalog.get("sha256") != team_catalog_digest:
        raise TopDatasetLoadError("Los metadatos de captura no coinciden con el hash del catálogo de equipos")
    if team_catalog.get("source_capture_id") != decoded["teams"].get("metadata", {}).get("source_capture_id"):
        raise TopDatasetLoadError("La identidad de la captura del catálogo de equipos no coincide con la referencia TOP")
    for key in ("competition", "season", "group"):
        if decoded["teams"].get("metadata", {}).get(key) != decoded["capture"].get(key):
            raise TopDatasetLoadError(f"El catálogo de equipos no corresponde a la misma {key} de TOP")

    teams = _team_index(decoded["teams"])
    try:
        players = [TopPlayerResponse.model_validate(record) for record in decoded["players"]["records"]]
        rankings = [TopRankingResponse.model_validate(record) for record in decoded["rankings"]["records"]]
        progress = [TopProgressSeries.model_validate(record) for record in decoded["progress"]["records"]]
        source_foreigners = [
            _SourceForeignPlayer.model_validate(record)
            for record in decoded["foreigners"]["records"]
        ]
        foreigners = [
            TopForeignPlayerResponse(
                player_id=player.player_id,
                statistics=player.statistics,
            )
            for player in source_foreigners
        ]
    except (KeyError, TypeError, ValidationError) as exc:
        raise TopDatasetLoadError("Los registros TOP no cumplen los esquemas públicos") from exc

    foreigners_coverage = _validate_records(
        decoded,
        players,
        rankings,
        progress,
        source_foreigners,
        foreigners,
        teams,
        source_html=files["source_html"],
    )
    affiliation_validation = _validate_affiliations(
        decoded, players, teams, files["source_html"]
    )
    _validate_active_team_compatibility(players, teams, active_teams)
    if (active_teams is None) != (active_team_capture_id is None):
        raise TopDatasetLoadError("Falta la identidad de captura del catálogo activo compatible")
    metadata_data = decoded["capture"]
    category_counts = decoded["rankings"].get("category_source_counts")
    category_options = metadata_data.get("category_options")
    if not isinstance(category_counts, dict) or not isinstance(category_options, list):
        raise TopDatasetLoadError("Faltan las categorías o sus recuentos de la captura TOP")
    series_categories = {series.category for series in progress}
    options: list[TopCategoryOption] = []
    try:
        for option in category_options:
            source_value = str(option["value"])
            category = _CATEGORY_BY_SOURCE_VALUE[source_value]
            count = category_counts[category]
            options.append(
                TopCategoryOption(
                    source_value=source_value,
                    category=category,
                    label=option["label"],
                    available_count=count,
                    graph_available=category in series_categories,
                    see_all_available=category == "goals" and bool(metadata_data["see_all_available_for_goals"]),
                )
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise TopDatasetLoadError("La captura declara una categoría desconocida o mal formada") from exc
    if {option.category for option in options} != set(_CATEGORY_BY_NAME):
        raise TopDatasetLoadError("La captura no contiene exactamente las seis categorías esperadas")
    if len(options) != len(_CATEGORY_BY_NAME) or len({option.source_value for option in options}) != len(options):
        raise TopDatasetLoadError("La captura repite opciones de categoría")

    foreign_summary_raw = decoded["foreigners"].get("summary")
    try:
        countries = [
            TopCountryOption(code=item[0], label=item[1])
            for item in foreign_summary_raw["country_options"]
        ]
        foreigners_summary = TopForeignersSummary(
            source_count=foreign_summary_raw["source_count"],
            available_count=foreigners_coverage.available_count,
            missing_count=foreigners_coverage.missing_count,
            coverage_status=foreigners_coverage.status,
            source_percentage=foreign_summary_raw.get("source_percentage"),
            denominator_count=foreign_summary_raw.get("denominator_count"),
            country_options=countries,
        )
        captured_at = datetime.fromisoformat(metadata_data["captured_at_utc"])
        capture = TopCaptureMetadata(
            source=metadata_data["source"],
            url=metadata_data["url"],
            competition=metadata_data["competition"],
            season=metadata_data["season"],
            group=metadata_data["group"],
            section=metadata_data["section"],
            capture_id=metadata_data["capture_id"],
            captured_at=captured_at,
            extractor_version=metadata_data["extractor_version"],
            source_snapshot_sha256=metadata_data["source_snapshot_sha256"],
            related_team_capture_id=team_catalog["source_capture_id"],
            related_team_catalog_sha256=team_catalog_digest,
            active_team_capture_id=active_team_capture_id,
            dataset_version=f"{metadata_data['capture_id']}-{hashlib.sha256(b''.join(files.values())).hexdigest()[:12]}",
        )
        bootstrap = TopBootstrapResponse(
            metadata=capture,
            availability=TopAvailability(
                players=len(players),
                ranking_records=len(rankings),
                progress_series=len(progress),
                progress_points=sum(len(series.points) for series in progress),
                foreign_players=len(foreigners),
                categories=category_counts,
                matchdays=decoded["progress"]["matchdays"],
            ),
            categories=options,
            players=players,
            rankings=rankings,
            progress=progress,
            foreigners=foreigners,
            foreigners_summary=foreigners_summary,
            coverage_note=decoded["rankings"]["coverage_note"],
            warnings=_public_source_warnings(decoded["validation"], settings.group),
            affiliation_conflicts=affiliation_validation.conflicts,
            affiliation_absences=affiliation_validation.absences,
        )
    except (KeyError, TypeError, ValidationError) as exc:
        raise TopDatasetLoadError("Los metadatos de TOP no cumplen el contrato esperado") from exc

    # Include the response schema in the validator: the source capture can stay
    # unchanged while the API representation evolves, so old cached JSON must
    # not be revalidated as if it were the current contract.
    etag = f'"top-v{TOP_BOOTSTRAP_SCHEMA_VERSION}-{capture.dataset_version}"'
    return TopDatasetBundle(bootstrap, etag)


def _top_paths(settings: ApiSettings) -> dict[str, Path]:
    root = (PROJECT_ROOT / DEFAULT_TOP_CAPTURE).resolve()
    configured = {
        "players": settings.top_players_path,
        "rankings": settings.top_rankings_path,
        "progress": settings.top_progress_path,
        "foreigners": settings.top_foreigners_path,
        "capture": settings.top_capture_metadata_path,
        "validation": settings.top_validation_path,
        "source_html": settings.top_source_html_path,
        "teams": settings.top_team_catalog_path,
    }
    default_names = {
        "players": "normalized/players.json",
        "rankings": "normalized/rankings.json",
        "progress": "normalized/progress.json",
        "foreigners": "normalized/foreigners.json",
        "capture": "metadata/capture.json",
        "validation": "validation/results.json",
        "source_html": "raw/source.html",
    }
    result = {
        name: path.resolve() if path is not None else (root / default_names[name]).resolve()
        for name, path in configured.items()
        if name != "teams"
    }
    if settings.top_team_catalog_path is not None:
        result["teams"] = settings.top_team_catalog_path.resolve()
    else:
        capture_data = _decode_json(_read_bytes(result["capture"]), result["capture"])
        related_catalog = capture_data.get("related_team_catalog")
        catalog_path = related_catalog.get("path") if isinstance(related_catalog, dict) else None
        if not isinstance(catalog_path, str) or not catalog_path:
            raise TopDatasetLoadError("La captura TOP no declara la ruta de su catálogo original")
        referenced_path = Path(catalog_path)
        result["teams"] = (
            referenced_path.resolve()
            if referenced_path.is_absolute()
            else (PROJECT_ROOT / referenced_path).resolve()
        )
    return result


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise TopDatasetLoadError(f"No se pudo leer el archivo TOP configurado: {path.name}") from exc


def _decode_json(payload: bytes, path: Path) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TopDatasetLoadError(f"El archivo TOP {path.name} no contiene JSON válido") from exc
    if not isinstance(value, dict):
        raise TopDatasetLoadError(f"El archivo TOP {path.name} debe contener un objeto JSON")
    return value


def _validate_capture_metadata(
    data: dict[str, dict[str, Any]], expected_group: str
) -> None:
    capture = data["capture"]
    validation = data["validation"]
    if validation.get("valid") is not True or validation.get("issues") != []:
        raise TopDatasetLoadError("La captura TOP no superó su validación de origen")
    if capture.get("access", {}).get("status") != "VALID" or capture.get("access", {}).get("http_status") != 200:
        raise TopDatasetLoadError("La captura TOP no acredita acceso válido al contenido deportivo")
    if capture.get("season") != _EXPECTED_SEASON or capture.get("group") != expected_group:
        raise TopDatasetLoadError(
            f"La captura no corresponde a Primera Federación Grupo {expected_group} 2026/27"
        )
    capture_id = capture.get("capture_id")
    if not capture_id or capture.get("section") != "top":
        raise TopDatasetLoadError("La identidad de captura TOP no es válida")
    for name in ("players", "rankings", "progress", "foreigners"):
        payload = data[name]
        if payload.get("schema_version") != 1:
            raise TopDatasetLoadError(f"La versión de {name}.json no es compatible")
        metadata = payload.get("metadata", {})
        if any(
            metadata.get(key) != capture.get(key)
            for key in ("capture_id", "source", "url", "competition", "season", "group", "section", "extractor_version", "source_snapshot_sha256")
        ):
            raise TopDatasetLoadError(f"{name}.json pertenece a otra captura TOP")
        if metadata.get("related_team_catalog") != data["players"].get("metadata", {}).get("related_team_catalog"):
            raise TopDatasetLoadError(f"{name}.json referencia otro catálogo de equipos")


def _validate_source_snapshot(raw_html: bytes, capture: dict[str, Any]) -> None:
    if hashlib.sha256(raw_html).hexdigest() != capture.get("source_snapshot_sha256"):
        raise TopDatasetLoadError("El hash del HTML de origen no coincide con la captura TOP")


def _team_index(teams_data: dict[str, Any]) -> dict[int, dict[str, Any]]:
    records = teams_data.get("teams")
    if not isinstance(records, list):
        raise TopDatasetLoadError("El catálogo relacionado no contiene una lista de equipos")
    result: dict[int, dict[str, Any]] = {}
    try:
        for team in records:
            team_id = team["team_id"]
            if team_id in result:
                raise TopDatasetLoadError("El catálogo relacionado repite IDs de equipo")
            result[team_id] = team
    except (KeyError, TypeError) as exc:
        raise TopDatasetLoadError("El catálogo relacionado tiene registros inválidos") from exc
    return result


def _validate_records(
    data: dict[str, dict[str, Any]],
    players: list[TopPlayerResponse],
    rankings: list[TopRankingResponse],
    progress: list[TopProgressSeries],
    source_foreigners: list[_SourceForeignPlayer],
    foreigners: list[TopForeignPlayerResponse],
    teams: dict[int, dict[str, Any]],
    *,
    source_html: bytes,
) -> _ForeignersCoverage:
    player_ids = [player.player_id for player in players]
    player_set = set(player_ids)
    if len(player_set) != len(players):
        raise TopDatasetLoadError("La captura TOP repite identificadores de jugador")
    players_by_id = {player.player_id: player for player in players}
    for player in players:
        if player.team_id is None:
            if any(value is not None for value in (player.team_name, player.team_url, player.crest_url)):
                raise TopDatasetLoadError("Jugador sin team_id conserva datos de equipo incompatibles")
            continue
        catalog_team = teams.get(player.team_id)
        if catalog_team is None:
            raise TopDatasetLoadError(f"El jugador {player.player_id} referencia un team_id inexistente")
        if any(
            getattr(player, field) != catalog_team.get(source_field)
            for field, source_field in (("team_name", "name"), ("team_url", "team_url"), ("crest_url", "crest_url"))
        ):
            raise TopDatasetLoadError(
                f"El jugador {player.player_id} no coincide con team_id {player.team_id}; no se concilia por nombre"
            )

    ranking_keys = [(item.category, item.rank) for item in rankings]
    if len(ranking_keys) != len(set(ranking_keys)):
        raise TopDatasetLoadError("Hay rangos duplicados dentro de una categoría TOP")
    ranking_player_keys = [(item.category, item.player_id) for item in rankings]
    if len(ranking_player_keys) != len(set(ranking_player_keys)):
        raise TopDatasetLoadError("Un jugador aparece duplicado dentro de una categoría TOP")
    if any(item.player_id not in player_set for item in rankings):
        raise TopDatasetLoadError("Un ranking referencia un jugador desconocido")
    if any(item.metric != _METRIC_BY_CATEGORY[item.category] or item.unit != _UNIT_BY_CATEGORY[item.category] for item in rankings):
        raise TopDatasetLoadError("Una categoría TOP contiene una métrica o unidad incompatible")

    progress_keys = [(item.category, item.player_id) for item in progress]
    if len(progress_keys) != len(set(progress_keys)):
        raise TopDatasetLoadError("Hay series de progreso duplicadas")
    matchdays = data["progress"].get("matchdays")
    if not isinstance(matchdays, list) or not matchdays or matchdays != sorted(set(matchdays)):
        raise TopDatasetLoadError("Las jornadas de progreso no son una secuencia ordenada y única")
    for series in progress:
        if not series.points:
            raise TopDatasetLoadError("Una serie de progreso no contiene puntos")
        if series.player_id not in player_set:
            raise TopDatasetLoadError("Una serie de progreso referencia un jugador desconocido")
        if series.metric != _METRIC_BY_CATEGORY[series.category] or series.unit != _UNIT_BY_CATEGORY[series.category]:
            raise TopDatasetLoadError("Una serie de progreso contiene una métrica o unidad incompatible")
        days = [point.matchday for point in series.points]
        if days != matchdays:
            raise TopDatasetLoadError("Una serie de progreso no conserva las jornadas publicadas")
        if series.graph_selected_by_default and not any(
            item.category == series.category and item.player_id == series.player_id and item.graph_selected_by_default
            for item in rankings
        ):
            raise TopDatasetLoadError("El valor inicial del gráfico no coincide entre ranking y serie")

    foreign_ids = [player.player_id for player in foreigners]
    if len(foreign_ids) != len(set(foreign_ids)) or any(player_id not in player_set for player_id in foreign_ids):
        raise TopDatasetLoadError("La tabla de extranjeros contiene IDs duplicados o desconocidos")
    source_foreigners_by_id = {player.player_id: player for player in source_foreigners}
    public_foreigners_by_id = {player.player_id: player for player in foreigners}
    if len(source_foreigners_by_id) != len(source_foreigners) or set(source_foreigners_by_id) != set(public_foreigners_by_id):
        raise TopDatasetLoadError("Los registros de extranjeros de origen y públicos no coinciden")
    for foreign in source_foreigners:
        base = players_by_id[foreign.player_id]
        if any(
            getattr(foreign, field) != getattr(base, field)
            for field in TopPlayerResponse.model_fields
        ):
            raise TopDatasetLoadError("La tabla de extranjeros discrepa del catálogo por player_id")
        if public_foreigners_by_id[foreign.player_id].statistics != foreign.statistics:
            raise TopDatasetLoadError("Las estadísticas públicas de un extranjero discrepan del origen")

    category_counts = Counter(item.category for item in rankings)
    declared = data["rankings"].get("category_source_counts")
    expected_categories = set(_CATEGORY_BY_NAME)
    if not isinstance(declared, dict) or set(declared) != expected_categories:
        raise TopDatasetLoadError("El archivo rankings.json declara categorías desconocidas o incompletas")
    actual_category_counts = {category: category_counts.get(category, 0) for category in expected_categories}
    if declared != actual_category_counts:
        raise TopDatasetLoadError("Los recuentos por categoría no coinciden con los rankings")
    if data["capture"].get("category_source_counts") != declared:
        raise TopDatasetLoadError("Los recuentos de categorías difieren entre la captura y rankings.json")
    ranking_order: dict[str, list[int]] = {}
    for item in rankings:
        ranking_order.setdefault(item.category, []).append(item.rank)
    if any(sorted(ranking_order.get(category, [])) != list(range(1, declared[category] + 1)) for category in expected_categories):
        raise TopDatasetLoadError("Los rangos publicados tienen huecos o posiciones duplicadas")

    ranking_by_key = {(item.category, item.player_id): item for item in rankings}
    progress_by_key = {(item.category, item.player_id): item for item in progress}
    expected_progress_keys = {
        (item.category, item.player_id)
        for item in rankings
        if item.category in _PROGRESS_CATEGORIES
    }
    if set(progress_by_key) != expected_progress_keys:
        raise TopDatasetLoadError("Las series no cubren exactamente los rankings con progreso")
    for series in progress:
        ranking = ranking_by_key.get((series.category, series.player_id))
        if ranking is None or series.points[-1].value != ranking.metric_value:
            raise TopDatasetLoadError("Una serie de progreso no termina en el valor de su ranking")
        values = [point.value for point in series.points if point.value is not None]
        if any(value < 0 for value in values) or any(current < previous for previous, current in zip(values, values[1:])):
            raise TopDatasetLoadError("Una serie de progreso contiene valores negativos o no acumulativos")
        matching_rank = ranking_by_key[(series.category, series.player_id)]
        if series.graph_selected_by_default != bool(matching_rank.graph_selected_by_default):
            raise TopDatasetLoadError("La selección inicial del gráfico difiere entre ranking y serie")

    summary = data["foreigners"].get("summary", {})
    country_options = summary.get("country_options")
    source_percentage = summary.get("source_percentage")
    denominator_count = summary.get("denominator_count")
    foreigners_coverage = _validate_foreigners_coverage(
        data,
        summary,
        source_html,
        {player.player_id for player in foreigners},
    )
    if (
        (source_percentage is not None and (not isinstance(source_percentage, (int, float)) or not 0 <= source_percentage <= 100))
        or (denominator_count is not None and (not isinstance(denominator_count, int) or denominator_count < len(foreigners)))
    ):
        raise TopDatasetLoadError("El resumen de extranjeros contiene recuentos incompatibles")
    if (
        not isinstance(country_options, list)
        or not country_options
        or any(
            not isinstance(item, list)
            or len(item) != 2
            or not isinstance(item[0], str)
            or not isinstance(item[1], str)
            for item in country_options
        )
        or len({item[0] for item in country_options}) != len(country_options)
    ):
        raise TopDatasetLoadError("Las opciones de nacionalidad están incompletas o duplicadas")
    if country_options[0] != ["", "Todos"]:
        raise TopDatasetLoadError("La primera opción de nacionalidad debe ser Todos")
    valid_codes = {item[0] for item in country_options}
    if any(player.nationality_code and player.nationality_code not in valid_codes for player in source_foreigners):
        raise TopDatasetLoadError("Un jugador extranjero usa un código de país no publicado en las opciones")

    validation_counts = data["validation"].get("summary", {})
    actual_counts = {
        "categories": len(expected_categories),
        "players": len(players),
        "ranking_records": len(rankings),
        "progress_series": len(progress),
        "progress_points": sum(len(item.points) for item in progress),
        "foreign_players": len(foreigners),
        "foreign_country_options": len(country_options),
        "chart_matchdays": matchdays,
    }
    if any(validation_counts.get(key) != value for key, value in actual_counts.items()):
        raise TopDatasetLoadError("Los recuentos normalizados no coinciden con validation/results.json")
    validation_categories = data["validation"].get("category_counts")
    if validation_categories != declared:
        raise TopDatasetLoadError("Los recuentos de categoría no coinciden con validation/results.json")
    if data["capture"].get("chart_matchdays") != matchdays:
        raise TopDatasetLoadError("Las jornadas de progreso difieren entre metadatos y progress.json")
    if data["capture"].get("foreigners_summary") != summary:
        raise TopDatasetLoadError("El resumen de extranjeros difiere entre metadatos y foreigners.json")
    return foreigners_coverage


def _validate_active_team_compatibility(
    players: list[TopPlayerResponse],
    source_teams: dict[int, dict[str, Any]],
    active_teams: list[TeamResponse] | None,
) -> None:
    """Prove that TOP's team IDs still identify the same dashboard teams."""
    if active_teams is None:
        return
    active_by_id: dict[int, TeamResponse] = {}
    for team in active_teams:
        if team.team_id in active_by_id:
            raise TopDatasetLoadError("El catálogo activo contiene IDs de equipo inválidos o duplicados")
        active_by_id[team.team_id] = team
    referenced_ids = {player.team_id for player in players if player.team_id is not None}
    for team_id in referenced_ids:
        source_team = source_teams.get(team_id)
        active_team = active_by_id.get(team_id)
        if source_team is None or active_team is None:
            raise TopDatasetLoadError(f"El team_id {team_id} de TOP no existe en ambos catálogos")
        if source_team.get("name") != active_team.name or source_team.get("team_url") != active_team.team_url:
            raise TopDatasetLoadError(
                f"El team_id {team_id} tiene nombre o URL incompatibles entre TOP y la clasificación activa"
            )


def _validate_affiliations(
    data: dict[str, dict[str, Any]],
    players: list[TopPlayerResponse],
    teams: dict[int, dict[str, Any]],
    source_html: bytes,
) -> _TopAffiliationValidation:
    """Validate conflicts and documented no-team rows against source structures."""

    raw_conflicts = data["capture"].get("affiliation_conflicts", [])
    raw_absences = data["capture"].get("affiliation_absences", [])
    if not isinstance(raw_conflicts, list) or not isinstance(raw_absences, list):
        raise TopDatasetLoadError("La captura no contiene listas válidas de afiliaciones documentadas")
    parser = _TopSourceEvidenceParser(source_html)
    player_by_id = {player.player_id: player for player in players}
    null_team_player_ids = {player.player_id for player in players if player.team_id is None}
    conflicts: list[TopAffiliationConflict] = []
    conflict_player_ids: set[int] = set()
    absences: list[TopAffiliationAbsence] = []
    absence_player_ids: set[int] = set()
    expected_warnings: set[str] = set()

    for raw_conflict in raw_conflicts:
        try:
            conflict = TopAffiliationConflict.model_validate(raw_conflict)
        except ValidationError as exc:
            raise TopDatasetLoadError("El conflicto de afiliación no cumple el contrato") from exc
        if conflict.player_id in conflict_player_ids:
            raise TopDatasetLoadError("La captura repite un conflicto de afiliación para el mismo jugador")
        conflict_player_ids.add(conflict.player_id)
        player = player_by_id.get(conflict.player_id)
        if player is None:
            raise TopDatasetLoadError("Un conflicto de afiliación referencia un jugador inexistente")
        if player.team_id is not None or any(
            value is not None for value in (player.team_name, player.team_url, player.crest_url)
        ):
            raise TopDatasetLoadError("Un jugador con afiliaciones contradictorias debe conservar team_id=null")

        affiliation_ids: set[int] = set()
        for affiliation in conflict.affiliations:
            if affiliation.team_id in affiliation_ids:
                raise TopDatasetLoadError("El conflicto duplica un mismo ID de equipo")
            affiliation_ids.add(affiliation.team_id)
            team = teams.get(affiliation.team_id)
            if team is None or team.get("name") != affiliation.team_name:
                raise TopDatasetLoadError("Un conflicto referencia un equipo que no coincide con el catálogo por ID")
            if len(affiliation.source_records) != len(set(affiliation.source_records)):
                raise TopDatasetLoadError("El conflicto repite una procedencia de afiliación")
            for source_record in affiliation.source_records:
                source_present, source_crest = parser.source_affiliation(source_record, conflict.player_id)
                expected_crest = _crest_filename(team.get("crest_url"))
                if not source_present or source_crest is None or source_crest != expected_crest:
                    raise TopDatasetLoadError(
                        "La procedencia de una afiliación no respalda el jugador y equipo declarados"
                    )
        if len(affiliation_ids) < 2:
            raise TopDatasetLoadError("Un conflicto debe documentar al menos dos equipos distintos")

        expected_warnings.add(_affiliation_warning(conflict.player_id))
        conflicts.append(conflict)

    for raw_absence in raw_absences:
        try:
            absence = TopAffiliationAbsence.model_validate(raw_absence)
        except ValidationError as exc:
            raise TopDatasetLoadError("La ausencia de afiliación no cumple el contrato") from exc
        if absence.player_id in absence_player_ids or absence.player_id in conflict_player_ids:
            raise TopDatasetLoadError("La captura repite o solapa una afiliación documentada")
        absence_player_ids.add(absence.player_id)
        player = player_by_id.get(absence.player_id)
        if player is None or player.team_id is not None or any(
            value is not None for value in (player.team_name, player.team_url, player.crest_url)
        ):
            raise TopDatasetLoadError("Una ausencia documentada no coincide con un jugador sin team_id")
        if len(absence.source_records) != len(set(absence.source_records)):
            raise TopDatasetLoadError("La ausencia repite una procedencia de afiliación")
        for source_record in absence.source_records:
            source_present, source_crest = parser.source_affiliation(source_record, absence.player_id)
            if not source_present or source_crest is not None:
                raise TopDatasetLoadError("La fuente citada sí publica equipo o no contiene al jugador")
        if any(crest is not None for _, crest in parser.all_affiliations(absence.player_id)):
            raise TopDatasetLoadError("Otra estructura de origen sí publica una afiliación para el jugador")
        expected_warnings.add(_affiliation_absence_warning(absence.player_id))
        absences.append(absence)

    if null_team_player_ids != conflict_player_ids | absence_player_ids:
        raise TopDatasetLoadError("Hay jugadores sin afiliación verificable que no están justificados por evidencia")
    validation = data["validation"]
    summary = validation.get("summary", {})
    declared_conflict_count = summary.get("affiliation_conflicts", 0)
    declared_absence_count = summary.get("affiliation_absences", 0)
    if (
        not isinstance(declared_conflict_count, int)
        or isinstance(declared_conflict_count, bool)
        or declared_conflict_count != len(raw_conflicts)
        or not isinstance(declared_absence_count, int)
        or isinstance(declared_absence_count, bool)
        or declared_absence_count != len(raw_absences)
    ):
        raise TopDatasetLoadError("El recuento de conflictos no coincide con la validación de origen")
    warnings = validation.get("warnings", [])
    if not isinstance(warnings, list) or any(not isinstance(item, str) for item in warnings):
        raise TopDatasetLoadError("Las advertencias de afiliación tienen formato inválido")
    observed_warnings = {
        warning
        for warning in warnings
        if warning.startswith((
            "Afiliación de equipo ambigua para player_id=",
            "Afiliación de equipo no publicada para player_id=",
        ))
    }
    if observed_warnings != expected_warnings:
        raise TopDatasetLoadError("Las advertencias de afiliación no corresponden a la evidencia verificada")
    return _TopAffiliationValidation(conflicts, absences)


class _TopSourceEvidenceParser(HTMLParser):
    """Extract only the foreign-player count, rows, and affiliation evidence."""

    _PLAYER_LINK = re.compile(r"(?:^|/)j(\d+)\.html(?:$|[?#])")

    def __init__(self, source_html: bytes) -> None:
        super().__init__(convert_charrefs=True)
        try:
            text = source_html.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise TopDatasetLoadError("El HTML de origen TOP no es UTF-8 válido") from exc
        self.last_heading = ""
        self.foreign_heading = ""
        self.current_heading: list[str] | None = None
        self.in_foreign_table = False
        self.current_row_player: int | None = None
        self.current_row_crests: set[str] = set()
        self.current_row_has_data = False
        self.foreign_row_count = 0
        self.foreign_rows: dict[int, list[set[str]]] = {}
        self._source_crests: dict[str, dict[int, str | None]] = {"table#tab_estran": {}, "DESTACATS_JS.LG": {}}
        self.feed(text)
        heading_match = re.search(r"\b(\d+)\s*\(\s*[\d,.]+\s*%\s*\)", self.foreign_heading)
        self.published_count = int(heading_match.group(1)) if heading_match else None
        try:
            self._load_goals_source(text)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise TopDatasetLoadError("No se pudo interpretar DESTACATS_JS.LG para validar afiliaciones") from exc

    def _load_goals_source(self, text: str) -> None:
        match = re.search(r"const\s+DESTACATS_JS\s*=\s*(\{.*?\})\s*;", text, re.DOTALL)
        if not match:
            return
        source = json.loads(match.group(1))
        records = source.get("LG", [])
        if not isinstance(records, list):
            return
        for row in records:
            if (
                isinstance(row, list)
                and len(row) > 5
                and isinstance(row[1], int)
            ):
                self._source_crests["DESTACATS_JS.LG"][row[1]] = _crest_filename(row[5])

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "h2":
            self.current_heading = []
        if tag == "table" and attributes.get("id") == "tab_estran":
            self.in_foreign_table = True
            self.foreign_heading = self.last_heading
        if not self.in_foreign_table:
            return
        if tag == "tr":
            self.current_row_player = None
            self.current_row_crests = set()
            self.current_row_has_data = False
        elif tag == "td":
            self.current_row_has_data = True
        elif tag == "a":
            href = attributes.get("href") or ""
            player_match = self._PLAYER_LINK.search(href)
            if player_match:
                self.current_row_player = int(player_match.group(1))
        elif tag == "img":
            src = attributes.get("src") or ""
            if "/eg/" in src:
                crest = _crest_filename(src)
                if crest:
                    self.current_row_crests.add(crest)

    def handle_endtag(self, tag: str) -> None:
        if tag == "h2" and self.current_heading is not None:
            self.last_heading = "".join(self.current_heading)
            self.current_heading = None
        if self.in_foreign_table and tag == "tr":
            if self.current_row_has_data:
                self.foreign_row_count += 1
                if self.current_row_player is not None:
                    self.foreign_rows.setdefault(self.current_row_player, []).append(
                        set(self.current_row_crests)
                    )
                    crests = sorted(self.current_row_crests)
                    self._source_crests["table#tab_estran"][self.current_row_player] = (
                        crests[-1] if crests else None
                    )
            self.current_row_player = None
        elif self.in_foreign_table and tag == "table":
            self.in_foreign_table = False

    def handle_data(self, data: str) -> None:
        if self.current_heading is not None:
            self.current_heading.append(data)

    def source_affiliation(self, source_record: str, player_id: int) -> tuple[bool, str | None]:
        source = self._source_crests.get(source_record, {})
        return player_id in source, source.get(player_id)

    def all_affiliations(self, player_id: int) -> list[tuple[str, str | None]]:
        return [
            (source_record, records[player_id])
            for source_record, records in self._source_crests.items()
            if player_id in records
        ]


def _crest_filename(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    match = re.search(r"(?:^|/)([^/]+\.(?:png|jpe?g|webp))(?:$|[?#])", value, re.IGNORECASE)
    return match.group(1).lower() if match else None


def _affiliation_warning(player_id: int) -> str:
    return (
        f"Afiliación de equipo ambigua para player_id={player_id}; se conserva como null en el catálogo "
        "y las fuentes/IDs están en affiliation_conflicts."
    )


def _affiliation_absence_warning(player_id: int) -> str:
    return (
        f"Afiliación de equipo no publicada para player_id={player_id}; se conserva como null en el catálogo "
        "y la ausencia está respaldada por las fuentes indicadas en affiliation_absences."
    )


def _validate_foreigners_coverage(
    data: dict[str, dict[str, Any]],
    summary: dict[str, Any],
    source_html: bytes,
    normalized_player_ids: set[int],
) -> _ForeignersCoverage:
    """Reconcile published count, actual source table, normalized rows and validation."""

    source_count = summary.get("source_count")
    if not isinstance(source_count, int) or isinstance(source_count, bool) or source_count < 0:
        raise TopDatasetLoadError("El recuento publicado de extranjeros no es válido")
    evidence = _TopSourceEvidenceParser(source_html)
    if evidence.published_count != source_count:
        raise TopDatasetLoadError("El recuento de extranjeros no coincide con el encabezado HTML original")
    if evidence.foreign_row_count != len(normalized_player_ids):
        raise TopDatasetLoadError("La tabla HTML de extranjeros y los registros normalizados no tienen el mismo tamaño")
    if set(evidence.foreign_rows) != normalized_player_ids:
        raise TopDatasetLoadError("Los IDs de extranjeros normalizados no coinciden con las filas HTML originales")

    difference = source_count - len(normalized_player_ids)
    warnings = data["validation"].get("warnings", [])
    if not isinstance(warnings, list) or any(not isinstance(item, str) for item in warnings):
        raise TopDatasetLoadError("Las advertencias de cobertura de extranjeros tienen formato inválido")
    count_warnings = [item for item in warnings if item.startswith("#tab_estran expone ")]
    if difference == 0:
        if count_warnings:
            raise TopDatasetLoadError("La validación advierte una diferencia de extranjeros que ya no existe")
        return _ForeignersCoverage(source_count, len(normalized_player_ids), 0, "complete")
    expected_warning = (
        f"#tab_estran expone {len(normalized_player_ids)} registros, pero el encabezado publica {source_count}; "
        "no se ha completado la fila ausente."
    )
    if (
        difference < 0
        or count_warnings != [expected_warning]
        or data["validation"].get("valid") is not True
        or data["validation"].get("issues") != []
        or data["validation"].get("summary", {}).get("foreign_players") != len(normalized_player_ids)
    ):
        raise TopDatasetLoadError("La diferencia de extranjeros no está justificada por evidencia y validación coherentes")
    return _ForeignersCoverage(
        source_count,
        len(normalized_player_ids),
        difference,
        "documented_discrepancy",
    )


def _public_source_warnings(validation: dict[str, Any], expected_group: str) -> list[str]:
    warnings = validation.get("warnings", [])
    if not isinstance(warnings, list) or any(not isinstance(item, str) for item in warnings):
        raise TopDatasetLoadError("Las advertencias de origen de Destacados tienen formato inválido")
    # The warnings are taken only from the selected group's validation file.
    return list(warnings)
