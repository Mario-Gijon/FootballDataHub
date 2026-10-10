"""Load and validate the independent BDFutbol TOP capture at API startup."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from football_data_hub_api.config import ApiSettings, DEFAULT_TOP_CAPTURE, PROJECT_ROOT
from football_data_hub_api.schemas import (
    TopAvailability,
    TopBootstrapResponse,
    TopCaptureMetadata,
    TopCategoryOption,
    TopCountryOption,
    TopForeignPlayerResponse,
    TopForeignersSummary,
    TopPlayerResponse,
    TopProgressSeries,
    TopRankingResponse,
)


class TopDatasetLoadError(ValueError):
    """Raised when TOP files cannot form a verified independent capture."""


@dataclass(frozen=True, slots=True)
class TopDatasetBundle:
    bootstrap: TopBootstrapResponse
    etag: str


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
_EXPECTED_GROUP = "II"


def load_top_dataset(settings: ApiSettings) -> TopDatasetBundle:
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
    _validate_capture_metadata(decoded)
    _validate_source_snapshot(files["source_html"], decoded["capture"])
    team_catalog_digest = hashlib.sha256(files["teams"]).hexdigest()
    team_catalog = decoded["players"]["metadata"].get("related_team_catalog")
    if not isinstance(team_catalog, dict):
        raise TopDatasetLoadError("La captura TOP no declara procedencia del catálogo de equipos")
    if team_catalog.get("sha256") != team_catalog_digest:
        raise TopDatasetLoadError(
            "El hash del catálogo de equipos no coincide con la referencia TOP; no se asociarán jugadores por nombre"
        )
    if decoded["capture"].get("related_team_catalog", {}).get("sha256") != team_catalog_digest:
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
        foreigners = [TopForeignPlayerResponse.model_validate(record) for record in decoded["foreigners"]["records"]]
    except (KeyError, TypeError, ValidationError) as exc:
        raise TopDatasetLoadError("Los registros TOP no cumplen los esquemas públicos") from exc

    _validate_records(decoded, players, rankings, progress, foreigners, teams)
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

    foreign_summary_raw = decoded["foreigners"].get("summary")
    try:
        countries = [
            TopCountryOption(code=item[0], label=item[1])
            for item in foreign_summary_raw["country_options"]
        ]
        foreigners_summary = TopForeignersSummary(
            source_count=foreign_summary_raw["source_count"],
            source_percentage=foreign_summary_raw.get("source_percentage"),
            # The capture has no official denominator. Do not expose its inferred value.
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
        )
    except (KeyError, TypeError, ValidationError) as exc:
        raise TopDatasetLoadError("Los metadatos de TOP no cumplen el contrato esperado") from exc

    return TopDatasetBundle(bootstrap, f'"{capture.dataset_version}"')


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
    result["teams"] = (
        settings.top_team_catalog_path.resolve()
        if settings.top_team_catalog_path is not None
        else (PROJECT_ROOT / "data/exports/bdfutbol/group2_classification/derived-res01-20261010T102656Z/normalized/matches.json").resolve()
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


def _validate_capture_metadata(data: dict[str, dict[str, Any]]) -> None:
    capture = data["capture"]
    validation = data["validation"]
    if validation.get("valid") is not True or validation.get("issues") != []:
        raise TopDatasetLoadError("La captura TOP no superó su validación de origen")
    if capture.get("access", {}).get("status") != "VALID" or capture.get("access", {}).get("http_status") != 200:
        raise TopDatasetLoadError("La captura TOP no acredita acceso válido al contenido deportivo")
    if capture.get("season") != _EXPECTED_SEASON or capture.get("group") != _EXPECTED_GROUP:
        raise TopDatasetLoadError("La captura no corresponde a Primera Federación Grupo II 2026/27")
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
    foreigners: list[TopForeignPlayerResponse],
    teams: dict[int, dict[str, Any]],
) -> None:
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
    for foreign in foreigners:
        base = players_by_id[foreign.player_id]
        if any(
            getattr(foreign, field) != getattr(base, field)
            for field in TopPlayerResponse.model_fields
        ):
            raise TopDatasetLoadError("La tabla de extranjeros discrepa del catálogo por player_id")

    category_counts = Counter(item.category for item in rankings)
    declared = data["rankings"].get("category_source_counts")
    expected_categories = set(_CATEGORY_BY_NAME)
    if not isinstance(declared, dict) or set(declared) != expected_categories:
        raise TopDatasetLoadError("El archivo rankings.json declara categorías desconocidas o incompletas")
    if dict(category_counts) != declared:
        raise TopDatasetLoadError("Los recuentos por categoría no coinciden con los rankings")
    if data["capture"].get("category_source_counts") != declared:
        raise TopDatasetLoadError("Los recuentos de categorías difieren entre la captura y rankings.json")
    ranking_order: dict[str, list[int]] = {}
    for item in rankings:
        ranking_order.setdefault(item.category, []).append(item.rank)
    if any(sorted(ranks) != list(range(1, len(ranks) + 1)) for ranks in ranking_order.values()):
        raise TopDatasetLoadError("Los rangos publicados tienen huecos o posiciones duplicadas")
    if len(players) != 217 or len(rankings) != 157 or len(progress) != 137 or sum(len(item.points) for item in progress) != 822:
        raise TopDatasetLoadError("Los recuentos de TOP no coinciden con la captura validada")
    if len(foreigners) != 101:
        raise TopDatasetLoadError("El recuento de extranjeros no coincide con la captura validada")

    summary = data["foreigners"].get("summary", {})
    country_options = summary.get("country_options")
    if summary.get("source_count") != len(foreigners) or summary.get("denominator_count") is not None:
        raise TopDatasetLoadError("El resumen de extranjeros contiene recuentos incompatibles")
    if not isinstance(country_options, list) or len(country_options) != 44 or len({item[0] for item in country_options}) != len(country_options):
        raise TopDatasetLoadError("Las opciones de nacionalidad están incompletas o duplicadas")
    if country_options[0] != ["", "Todos"]:
        raise TopDatasetLoadError("La primera opción de nacionalidad debe ser Todos")
    valid_codes = {item[0] for item in country_options}
    if any(player.nationality_code and player.nationality_code not in valid_codes for player in foreigners):
        raise TopDatasetLoadError("Un jugador extranjero usa un código de país no publicado en las opciones")

    validation_counts = data["validation"].get("summary", {})
    actual_counts = {
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
