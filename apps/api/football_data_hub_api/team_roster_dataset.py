"""Load explicitly published, normalized BDFutbol team-roster captures."""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import ValidationError

from football_data_hub_api.dataset import DatasetBundle
from football_data_hub_api.schemas import (
    TeamResponse,
    TeamRosterCoachResponse,
    TeamRosterGroupResponse,
    TeamRosterMembershipResponse,
    TeamRosterMetadataResponse,
    TeamRosterPlayerResponse,
    TeamRosterPlayerStatisticsResponse,
    TeamRosterResponse,
    TeamRosterSourceViewResponse,
)

logger = logging.getLogger("football_data_hub_api.team_roster")
ROSTER_CONTRACT_VERSION = 1
ROSTER_SEASON = "2026-27"
ROSTER_REQUIRED_VIEWS = ("alignment", "squad", "statistics")
ROSTER_REQUIRED_FILES = (
    "metadata/capture.json",
    "validation/results.json",
    "raw/access.json",
    "normalized/team_identity.json",
    "normalized/team_season.json",
    "normalized/players.json",
    "normalized/memberships.json",
    "normalized/player_statistics.json",
)


class TeamRosterLoadError(ValueError):
    """A selected capture failed the checks required to publish its roster."""


@dataclass(frozen=True, slots=True)
class TeamRosterRegistry:
    known_teams: dict[int, tuple[str, TeamResponse]]
    profiles: dict[int, TeamRosterResponse]
    profile_errors: dict[int, str]
    index_error: str | None
    unavailable_group_errors: dict[str, str]


def load_team_roster_registry(
    index_path: Path | None,
    *,
    datasets: dict[str, DatasetBundle],
    matches_paths: dict[str, Path],
    unavailable_group_errors: dict[str, str] | None = None,
) -> TeamRosterRegistry:
    """Read and validate the selected captures once; HTTP handlers use memory only."""

    known: dict[int, tuple[str, TeamResponse]] = {}
    catalog_references: dict[str, dict[str, Any]] = {}
    for group in ("1", "2"):
        bundle = datasets.get(group)
        matches_path = matches_paths.get(group)
        if bundle is None or matches_path is None:
            continue
        group_label = "I" if group == "1" else "II"
        try:
            matches_sha256 = _sha256_file(matches_path)
        except OSError:
            logger.exception("No se pudo verificar el catálogo del Grupo %s", group_label)
            continue
        catalog_references[group_label] = {
            "capture_id": bundle.bootstrap.metadata.capture_id,
            "sha256": matches_sha256,
        }
        for team in bundle.bootstrap.teams:
            if team.team_id in known:
                logger.error("team_id duplicado entre catálogos: %s", team.team_id)
                continue
            known[team.team_id] = (group_label, team)

    if index_path is None:
        return TeamRosterRegistry(
            known, {}, {}, "No hay un índice de plantillas configurado.",
            unavailable_group_errors or {},
        )

    try:
        index = json.loads(index_path.expanduser().read_text(encoding="utf-8"))
        if not isinstance(index, dict) or index.get("schema_version") != 1:
            raise ValueError("versión de índice no compatible")
        if index.get("season") != ROSTER_SEASON:
            raise ValueError("el índice no corresponde a la temporada 2026/27")
        entries = index.get("profiles")
        if not isinstance(entries, dict):
            raise ValueError("el índice no contiene el mapa de perfiles")
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        logger.exception("Índice de plantillas no disponible")
        return TeamRosterRegistry(
            known, {}, {}, f"Índice de plantillas inválido: {exc}",
            unavailable_group_errors or {},
        )

    profiles: dict[int, TeamRosterResponse] = {}
    profile_errors: dict[int, str] = {}
    for team_key, entry in entries.items():
        try:
            team_id = int(team_key)
        except (TypeError, ValueError):
            logger.error("El índice contiene team_id no numérico: %r", team_key)
            continue
        try:
            if team_id not in known:
                raise TeamRosterLoadError("El perfil no corresponde a un equipo conocido.")
            if not isinstance(entry, dict):
                raise TeamRosterLoadError("La entrada del perfil no es un objeto.")
            profiles[team_id] = _load_selected_profile(
                team_id,
                entry,
                index_path=index_path.expanduser(),
                group_label=known[team_id][0],
                catalog_team=known[team_id][1],
                catalog_reference=catalog_references.get(known[team_id][0]),
            )
        except (OSError, ValueError, TypeError, KeyError, ValidationError, gzip.BadGzipFile) as exc:
            profile_errors[team_id] = str(exc)
            logger.exception("La plantilla seleccionada para team_id=%s no es válida", team_id)

    return TeamRosterRegistry(
        known,
        profiles,
        profile_errors,
        None,
        unavailable_group_errors or {},
    )


def _load_selected_profile(
    team_id: int,
    entry: dict[str, Any],
    *,
    index_path: Path,
    group_label: str,
    catalog_team: TeamResponse,
    catalog_reference: dict[str, Any] | None,
) -> TeamRosterResponse:
    capture_id = entry.get("capture_id")
    directory_value = entry.get("directory")
    expected_hashes = entry.get("files_sha256")
    if not isinstance(capture_id, str) or not capture_id:
        raise TeamRosterLoadError("Falta el capture_id explícito en el índice.")
    if not isinstance(directory_value, str) or not directory_value:
        raise TeamRosterLoadError("Falta el directorio explícito en el índice.")
    if not isinstance(expected_hashes, dict):
        raise TeamRosterLoadError("Faltan los hashes fijados de la captura.")
    if any(not _valid_sha256(expected_hashes.get(name)) for name in ROSTER_REQUIRED_FILES):
        raise TeamRosterLoadError("El índice no fija todos los hashes necesarios para Plantilla.")

    configured_dir = Path(directory_value).expanduser()
    capture_dir = configured_dir.resolve() if configured_dir.is_absolute() else (index_path.parent / configured_dir).resolve()
    if capture_dir.name != capture_id:
        raise TeamRosterLoadError("El directorio seleccionado no coincide con capture_id.")

    file_bytes: dict[str, bytes] = {}
    for relative in ROSTER_REQUIRED_FILES:
        path = _path_inside(capture_dir, relative)
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != expected_hashes[relative]:
            raise TeamRosterLoadError(f"El SHA-256 no coincide en {relative}.")
        file_bytes[relative] = payload

    capture_metadata = _decode_json(file_bytes["metadata/capture.json"], "metadata/capture.json")
    stored_validation = _decode_json(file_bytes["validation/results.json"], "validation/results.json")
    raw_access = _decode_json(file_bytes["raw/access.json"], "raw/access.json")
    if capture_metadata.get("schema_version") != 1:
        raise TeamRosterLoadError("Versión de metadatos de captura no compatible.")
    expected_identity = {
        "source": "BDFutbol",
        "section": "team_profile",
        "team_id": team_id,
        "team_name": catalog_team.name,
        "team_url": catalog_team.team_url,
        "season": ROSTER_SEASON,
        "competition": "Primera Federación",
        "competition_scope": "Liga",
        "group": group_label,
    }
    if any(capture_metadata.get(key) != value for key, value in expected_identity.items()):
        raise TeamRosterLoadError("Identidad, grupo o temporada de la captura no coincide con el catálogo.")
    if capture_metadata.get("capture_id") != capture_id:
        raise TeamRosterLoadError("El capture_id de metadatos no coincide con el índice.")
    if stored_validation.get("valid") is not True:
        raise TeamRosterLoadError("El informe de validación guardado no marca esta captura como válida.")
    validation_summary = stored_validation.get("summary") or {}
    if validation_summary.get("team_id") != team_id:
        raise TeamRosterLoadError("El informe de validación pertenece a otro equipo.")
    if not set(ROSTER_REQUIRED_VIEWS).issubset(set(validation_summary.get("requested_views") or [])):
        raise TeamRosterLoadError("La captura no tiene validación para las tres vistas de Plantilla.")

    related_catalog = capture_metadata.get("related_team_catalog") or {}
    if (
        catalog_reference is None
        or related_catalog.get("group") != group_label
        or related_catalog.get("season") != ROSTER_SEASON
        or related_catalog.get("source_capture_id") != catalog_reference["capture_id"]
        or related_catalog.get("sha256") != catalog_reference["sha256"]
    ):
        raise TeamRosterLoadError("La referencia al catálogo activo del grupo no coincide.")

    access_by_view = capture_metadata.get("access_by_view") or {}
    if raw_access.get("capture_id") != capture_id or raw_access.get("views") != access_by_view:
        raise TeamRosterLoadError("raw/access.json no coincide con los metadatos de la captura.")
    requested_views = set(capture_metadata.get("requested_views") or [])
    if not set(ROSTER_REQUIRED_VIEWS).issubset(requested_views):
        raise TeamRosterLoadError("La captura no solicita Alineación, Plantilla y Estadísticas.")

    source_snapshots = capture_metadata.get("source_snapshots") or {}
    source_views: list[TeamRosterSourceViewResponse] = []
    for view in ROSTER_REQUIRED_VIEWS:
        evidence = source_snapshots.get(view)
        access = access_by_view.get(view)
        if not isinstance(evidence, dict) or not isinstance(access, dict):
            raise TeamRosterLoadError(f"Falta evidencia de procedencia para la vista {view}.")
        relative_path = evidence.get("path")
        if not isinstance(relative_path, str):
            raise TeamRosterLoadError(f"Falta el snapshot original de {view}.")
        original = _path_inside(capture_dir, relative_path).read_bytes()
        html = gzip.decompress(original) if evidence.get("compression") == "gzip" or relative_path.endswith(".gz") else original
        source_sha256 = hashlib.sha256(html).hexdigest()
        if source_sha256 != evidence.get("sha256"):
            raise TeamRosterLoadError(f"El snapshot original de {view} no supera SHA-256.")
        if evidence.get("http_status") != 200 or evidence.get("access_status", evidence.get("status")) != "VALID":
            raise TeamRosterLoadError(f"La vista {view} no tiene estado HTTP/validación aceptable.")
        requested_url = access.get("requested_url")
        final_url = access.get("final_url")
        if not requested_url or requested_url != final_url or evidence.get("url") != requested_url:
            raise TeamRosterLoadError(f"La URL final de {view} no coincide con la captura.")
        if access.get("http_status") != 200 or access.get("status") != "VALID":
            raise TeamRosterLoadError(f"La vista {view} no está marcada como VALID/200 en el registro de acceso.")
        parsed_url = urlparse(requested_url)
        if parsed_url.netloc not in {"www.bdfutbol.com", "bdfutbol.com"} or str(team_id) not in parsed_url.path:
            raise TeamRosterLoadError(f"La URL de {view} no corresponde a BDFutbol/team_id.")
        title = str(evidence.get("title") or access.get("page_title") or "")
        if ROSTER_SEASON not in title or catalog_team.name.casefold() not in title.casefold():
            raise TeamRosterLoadError(f"El título de {view} no confirma equipo y temporada.")
        captured_at_value = evidence.get("captured_at_utc") or access.get("captured_at_utc")
        source_views.append(TeamRosterSourceViewResponse.model_validate({
            "view": view,
            "url": requested_url,
            "title": title,
            "status": "VALID",
            "http_status": 200,
            "sha256": source_sha256,
            "captured_at": captured_at_value,
        }))

    normalized: dict[str, dict[str, Any]] = {}
    for name in ("team_identity", "team_season", "players", "memberships", "player_statistics"):
        relative = f"normalized/{name}.json"
        document = _decode_json(file_bytes[relative], relative)
        if document.get("schema_version") != 1:
            raise TeamRosterLoadError(f"Versión no compatible en {relative}.")
        dataset_metadata = document.get("metadata") or {}
        if (
            dataset_metadata.get("source") != "BDFutbol"
            or dataset_metadata.get("team_id") != team_id
            or dataset_metadata.get("capture_id") != capture_id
            or dataset_metadata.get("season") != ROSTER_SEASON
            or dataset_metadata.get("group") != group_label
            or (dataset_metadata.get("related_team_catalog") or {}).get("sha256") != related_catalog.get("sha256")
        ):
            raise TeamRosterLoadError(f"Metadatos incompatibles en {relative}.")
        source_file_hash = (capture_metadata.get("normalized_snapshots") or {}).get(f"{name}.json", {}).get("sha256")
        if source_file_hash and source_file_hash != expected_hashes[relative]:
            raise TeamRosterLoadError(f"El hash registrado no coincide en {relative}.")
        normalized[name] = document

    identity_record = normalized["team_identity"].get("record")
    season_record = normalized["team_season"].get("record")
    if not isinstance(identity_record, dict) or not isinstance(season_record, dict):
        raise TeamRosterLoadError("Identidad o temporada normalizada incompleta.")
    if (
        identity_record.get("team_id") != team_id
        or identity_record.get("name") != catalog_team.name
        or identity_record.get("team_url") != catalog_team.team_url
        or identity_record.get("crest_url") != catalog_team.crest_url
        or season_record.get("team_id") != team_id
        or season_record.get("season") != ROSTER_SEASON
        or season_record.get("group") != group_label
    ):
        raise TeamRosterLoadError("La identidad normalizada no coincide con el catálogo de equipos.")

    players_data = normalized["players"].get("records")
    memberships_data = normalized["memberships"].get("records")
    statistics_data = normalized["player_statistics"].get("records")
    if not all(isinstance(value, list) for value in (players_data, memberships_data, statistics_data)):
        raise TeamRosterLoadError("Los archivos normalizados de Plantilla deben contener listas.")
    players = [TeamRosterPlayerResponse.model_validate(record) for record in players_data]
    memberships = [TeamRosterMembershipResponse.model_validate(record) for record in memberships_data]
    statistics = [TeamRosterPlayerStatisticsResponse.model_validate(record) for record in statistics_data]
    coaches = [TeamRosterCoachResponse.model_validate(record) for record in season_record.get("coaches", [])]

    player_ids = [player.player_id for player in players]
    if not player_ids or len(player_ids) != len(set(player_ids)):
        raise TeamRosterLoadError("El catálogo contiene player_id ausentes o duplicados.")
    player_id_set = set(player_ids)
    membership_ids = [membership.player_id for membership in memberships]
    statistics_ids = [stat.player_id for stat in statistics]
    if len(membership_ids) != len(set(membership_ids)) or set(membership_ids) - player_id_set:
        raise TeamRosterLoadError("Las pertenencias no enlazan de forma única por player_id.")
    if len(statistics_ids) != len(set(statistics_ids)) or set(statistics_ids) - player_id_set:
        raise TeamRosterLoadError("Las estadísticas no enlazan de forma única por player_id.")
    if any(item.team_id != team_id or item.season != ROSTER_SEASON or item.group != group_label for item in memberships + statistics):
        raise TeamRosterLoadError("Pertenencias o estadísticas fuera del equipo/temporada/grupo seleccionados.")

    grouped_ids: dict[str, list[int]] = {}
    for membership in memberships:
        if membership.squad_group_label:
            grouped_ids.setdefault(membership.squad_group_label, []).append(membership.player_id)
    squad_groups = [TeamRosterGroupResponse(label=label, player_ids=ids) for label, ids in grouped_ids.items()]
    file_content_hash = hashlib.sha256(
        json.dumps(expected_hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    metadata = TeamRosterMetadataResponse.model_validate({
        "contract_version": ROSTER_CONTRACT_VERSION,
        "validation_status": "valid",
        "source": "BDFutbol",
        "url": identity_record["team_url"],
        "competition": capture_metadata["competition"],
        "season": capture_metadata["season"],
        "group": group_label,
        "team_id": team_id,
        "capture_id": capture_id,
        "captured_at": capture_metadata["captured_at_utc"],
        "extractor_version": capture_metadata.get("extractor_version", "unknown"),
        "content_sha256": file_content_hash,
    })
    warnings = list(dict.fromkeys(str(item) for item in stored_validation.get("warnings", [])))
    if not (capture_metadata.get("follow_states") or {}):
        warnings.append("La captura no contiene estados enriquecidos de Seguimiento; no son necesarios para Plantilla.")

    try:
        return TeamRosterResponse.model_validate({
            "status": "available",
            "metadata": metadata,
            "team": catalog_team,
            "coaches": coaches,
            "players": players,
            "memberships": memberships,
            "statistics": statistics,
            "squad_groups": squad_groups,
            "source_views": source_views,
            "warnings": warnings,
        })
    except ValidationError as exc:
        raise TeamRosterLoadError("La respuesta de Plantilla no cumple el contrato público.") from exc


def _decode_json(payload: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TeamRosterLoadError(f"JSON ilegible: {label}.") from exc
    if not isinstance(value, dict):
        raise TeamRosterLoadError(f"El contenido JSON no es un objeto: {label}.")
    return value


def _path_inside(root: Path, relative: str) -> Path:
    base = root.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(base):
        raise TeamRosterLoadError("Una ruta de evidencia sale del directorio de captura.")
    return path


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _valid_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(character in "0123456789abcdef" for character in value)
