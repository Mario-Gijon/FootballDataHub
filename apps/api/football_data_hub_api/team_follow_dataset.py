"""Load explicitly published player-by-match follow data from team captures."""

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
from football_data_hub.providers.bdfutbol.teams.parser import team_id_from_url
from football_data_hub_api.schemas import (
    TeamFollowMatchResponse,
    TeamFollowMetadataResponse,
    TeamFollowMetricResponse,
    TeamFollowMinutesResponse,
    TeamFollowPlayerResponse,
    TeamFollowResponse,
    TeamFollowStateCoverageResponse,
    TeamResponse,
)
from football_data_hub_api.team_roster_dataset import TeamRosterRegistry

logger = logging.getLogger("football_data_hub_api.team_follow")
FOLLOW_SEASON = "2026-27"
FOLLOW_CONTRACT_VERSION = 2
FOLLOW_INDEX_FILES = (
    "metadata/capture.json",
    "validation/results.json",
    "raw/access.json",
    "normalized/team_identity.json",
    "normalized/team_season.json",
    "normalized/players.json",
    "normalized/memberships.json",
    "normalized/player_match_minutes.json",
)
FOLLOW_STATES = ("p", "t", "go", "tot")


class TeamFollowLoadError(ValueError):
    """A selected capture failed the checks required to publish Seguimiento."""


@dataclass(frozen=True, slots=True)
class TeamFollowRegistry:
    known_teams: dict[int, tuple[str, TeamResponse]]
    profiles: dict[int, TeamFollowResponse]
    profile_errors: dict[int, str]
    index_error: str | None
    unavailable_group_errors: dict[str, str]


def load_team_follow_registry(
    index_path: Path | None,
    *,
    datasets: dict[str, DatasetBundle],
    matches_paths: dict[str, Path],
    roster_registry: TeamRosterRegistry,
    unavailable_group_errors: dict[str, str] | None = None,
) -> TeamFollowRegistry:
    """Validate selected captures once at startup; route handlers use memory only."""

    known = roster_registry.known_teams
    if index_path is None:
        return TeamFollowRegistry(known, {}, {}, "No hay un índice de capturas de equipo configurado.", unavailable_group_errors or {})
    try:
        index = json.loads(index_path.expanduser().read_text(encoding="utf-8"))
        if not isinstance(index, dict) or index.get("schema_version") != 1 or index.get("season") != FOLLOW_SEASON:
            raise ValueError("versión o temporada de índice no compatible")
        entries = index.get("profiles")
        if not isinstance(entries, dict):
            raise ValueError("el índice no contiene perfiles")
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        logger.exception("Índice de Seguimiento no disponible")
        return TeamFollowRegistry(known, {}, {}, f"Índice de capturas de Seguimiento inválido: {exc}", unavailable_group_errors or {})

    profiles: dict[int, TeamFollowResponse] = {}
    errors: dict[int, str] = {}
    for team_key, entry in entries.items():
        team_id: int | None = None
        try:
            team_id = int(team_key)
            if team_id not in known:
                raise TeamFollowLoadError("El perfil seleccionado no pertenece a un equipo conocido.")
            if not isinstance(entry, dict):
                raise TeamFollowLoadError("La entrada de perfil no es un objeto.")
            group, team = known[team_id]
            bundle = datasets.get("1" if group == "I" else "2")
            matches_path = matches_paths.get("1" if group == "I" else "2")
            if bundle is None or matches_path is None:
                raise TeamFollowLoadError("El catálogo de partidos del grupo no está disponible.")
            profiles[team_id] = _load_selected_follow(
                team_id,
                entry,
                index_path=index_path.expanduser(),
                group_label=group,
                catalog_team=team,
                dataset=bundle,
                matches_path=matches_path,
            )
        except (OSError, ValueError, TypeError, KeyError, ValidationError, gzip.BadGzipFile) as exc:
            if team_id is not None:
                errors[team_id] = str(exc)
                logger.exception("Seguimiento seleccionado para team_id=%s no es válido", team_id)
    return TeamFollowRegistry(known, profiles, errors, None, unavailable_group_errors or {})


def _load_selected_follow(
    team_id: int,
    entry: dict[str, Any],
    *,
    index_path: Path,
    group_label: str,
    catalog_team: TeamResponse,
    dataset: DatasetBundle,
    matches_path: Path,
) -> TeamFollowResponse:
    capture_id = entry.get("capture_id")
    directory_value = entry.get("directory")
    files_sha = entry.get("files_sha256")
    follow_sha = entry.get("follow_files_sha256")
    if not isinstance(capture_id, str) or not capture_id or not isinstance(directory_value, str) or not directory_value:
        raise TeamFollowLoadError("Falta la selección explícita de captura.")
    if not isinstance(files_sha, dict) or not isinstance(follow_sha, dict):
        raise TeamFollowLoadError("El índice no fija todos los hashes requeridos para Seguimiento.")
    if any(not _valid_sha(files_sha.get(path)) for path in FOLLOW_INDEX_FILES[:-1]):
        raise TeamFollowLoadError("El índice no fija los hashes de procedencia y catálogo de jugadores.")
    if not _valid_sha(follow_sha.get("normalized/player_match_minutes.json")):
        raise TeamFollowLoadError("El índice no fija el hash de minutos por partido.")

    configured_dir = Path(directory_value).expanduser()
    capture_dir = configured_dir.resolve() if configured_dir.is_absolute() else (index_path.parent / configured_dir).resolve()
    if capture_dir.name != capture_id:
        raise TeamFollowLoadError("El directorio no coincide con capture_id.")

    file_bytes: dict[str, bytes] = {}
    for relative in FOLLOW_INDEX_FILES[:-1]:
        payload = _path_inside(capture_dir, relative).read_bytes()
        if _sha256(payload) != files_sha.get(relative):
            raise TeamFollowLoadError(f"El SHA-256 no coincide en {relative}.")
        file_bytes[relative] = payload
    minute_bytes = _path_inside(capture_dir, "normalized/player_match_minutes.json").read_bytes()
    if _sha256(minute_bytes) != follow_sha["normalized/player_match_minutes.json"]:
        raise TeamFollowLoadError("El archivo de minutos no supera SHA-256.")
    file_bytes["normalized/player_match_minutes.json"] = minute_bytes

    capture = _decode(file_bytes["metadata/capture.json"], "metadata/capture.json")
    validation = _decode(file_bytes["validation/results.json"], "validation/results.json")
    access = _decode(file_bytes["raw/access.json"], "raw/access.json")
    if capture.get("schema_version") != 1 or capture.get("capture_id") != capture_id:
        raise TeamFollowLoadError("Metadatos de captura incompatibles con el índice.")
    expected = {
        "source": "BDFutbol", "section": "team_profile", "team_id": team_id,
        "team_name": catalog_team.name, "team_url": catalog_team.team_url,
        "season": FOLLOW_SEASON, "competition": "Primera Federación",
        "competition_scope": "Liga", "group": group_label,
    }
    if any(capture.get(key) != value for key, value in expected.items()):
        raise TeamFollowLoadError("Identidad, grupo, temporada o competición no coincide.")
    if validation.get("valid") is not True or validation.get("summary", {}).get("team_id") != team_id:
        raise TeamFollowLoadError("La captura no tiene una validación semántica válida para este equipo.")
    if "follow" not in (capture.get("requested_views") or []):
        raise TeamFollowLoadError("La captura no declara la vista Seguimiento.")

    related = capture.get("related_team_catalog") or {}
    active_match_hash = _sha256(matches_path.read_bytes())
    active_group_capture = dataset.bootstrap.metadata.capture_id
    if (
        related.get("group") != group_label or related.get("season") != FOLLOW_SEASON
        or related.get("source_capture_id") != active_group_capture
        or related.get("sha256") != active_match_hash
    ):
        raise TeamFollowLoadError("La referencia de la captura no coincide con el catálogo activo de partidos.")

    snapshots = capture.get("source_snapshots") or {}
    access_views = capture.get("access_by_view") or {}
    if access.get("capture_id") != capture_id or access.get("views") != access_views:
        raise TeamFollowLoadError("raw/access.json no coincide con los metadatos de captura.")
    follow_evidence = snapshots.get("follow")
    follow_access = access_views.get("follow")
    if not isinstance(follow_evidence, dict) or not isinstance(follow_access, dict):
        raise TeamFollowLoadError("Falta la evidencia original de Seguimiento.")
    if follow_access.get("status") != "VALID" or follow_access.get("http_status") != 200:
        raise TeamFollowLoadError("La vista Seguimiento no está validada como HTTP 200.")
    if follow_access.get("requested_url") != follow_access.get("final_url") or follow_evidence.get("url") != follow_access.get("requested_url"):
        raise TeamFollowLoadError("La URL final de Seguimiento no coincide con la captura.")
    parsed_url = urlparse(str(follow_evidence.get("url") or ""))
    if parsed_url.scheme != "https" or parsed_url.hostname not in {"bdfutbol.com", "www.bdfutbol.com"} or team_id_from_url(str(follow_evidence.get("url") or "")) != team_id:
        raise TeamFollowLoadError("La URL de Seguimiento no corresponde a BDFutbol y al equipo.")
    if follow_evidence.get("http_status") != 200 or follow_evidence.get("access_status", follow_evidence.get("status")) != "VALID":
        raise TeamFollowLoadError("El snapshot de Seguimiento no es contenido válido.")
    title = str(follow_evidence.get("title") or follow_access.get("page_title") or "")
    if FOLLOW_SEASON not in title or catalog_team.name.casefold() not in title.casefold():
        raise TeamFollowLoadError("El título del snapshot no identifica el equipo y temporada esperados.")
    follow_path = str(follow_evidence.get("path") or "")
    if not follow_path or not _valid_sha(follow_sha.get(follow_path)):
        raise TeamFollowLoadError("El índice no fija el hash del snapshot original de Seguimiento.")
    raw_follow = _path_inside(capture_dir, follow_path).read_bytes()
    if _sha256(raw_follow) != follow_sha[follow_path]:
        raise TeamFollowLoadError("El snapshot original de Seguimiento no supera SHA-256 del archivo.")
    follow_html = _decompress(raw_follow, follow_evidence.get("compression"), follow_path)
    if _sha256(follow_html) != follow_evidence.get("sha256") or follow_access.get("source_snapshot_sha256") != follow_evidence.get("sha256"):
        raise TeamFollowLoadError("El snapshot y el diagnóstico de acceso no comparten la misma huella.")

    state_manifest = capture.get("follow_states") or {}
    if not isinstance(state_manifest, dict):
        raise TeamFollowLoadError("La lista de estados capturados no es válida.")
    if any(state in state_manifest for state in ("t", "go")) and "normalized/player_match_metrics.json" not in follow_sha:
        raise TeamFollowLoadError("La captura declara Tarjetas/Goles pero el índice no fija sus métricas normalizadas.")
    captured_states: set[str] = set()
    for state, state_info in state_manifest.items():
        if state not in FOLLOW_STATES or not isinstance(state_info, dict):
            continue
        state_path = str(state_info.get("path") or "")
        if not state_path or not _valid_sha(follow_sha.get(state_path)):
            raise TeamFollowLoadError(f"El índice no fija el snapshot del estado {state}.")
        state_bytes = _path_inside(capture_dir, state_path).read_bytes()
        if _sha256(state_bytes) != follow_sha[state_path]:
            raise TeamFollowLoadError(f"El archivo fuente del estado {state} no supera SHA-256.")
        state_html = _decompress(state_bytes, state_info.get("compression"), state_path)
        if _sha256(state_html) != state_info.get("sha256") or state_info.get("selected_value") != state:
            raise TeamFollowLoadError(f"El snapshot del estado {state} no coincide con sus metadatos.")
        if state_info.get("status") == "DERIVED_OFFLINE":
            referenced_captures = {capture_id, *(str(item) for item in capture.get("reused_source_capture_ids", []))}
            if (
                state_info.get("origin") != "derived_offline"
                or state_info.get("derivation_method") != "embedded_javascript_matrices_v1"
                or state_info.get("source_snapshot_sha256") != follow_evidence.get("sha256")
                or state_info.get("source_capture_id") not in referenced_captures
                or not isinstance(state_info.get("derived_at_utc"), str)
            ):
                raise TeamFollowLoadError(f"La procedencia offline del estado {state} no está validada.")
        elif state_info.get("status", "VALID") != "VALID":
            raise TeamFollowLoadError(f"El estado {state} no es una captura válida ni una derivación reconocida.")
        captured_states.add(state)

    identity = _decode(file_bytes["normalized/team_identity.json"], "normalized/team_identity.json")
    season = _decode(file_bytes["normalized/team_season.json"], "normalized/team_season.json")
    players_doc = _decode(file_bytes["normalized/players.json"], "normalized/players.json")
    memberships_doc = _decode(file_bytes["normalized/memberships.json"], "normalized/memberships.json")
    minutes_doc = _decode(file_bytes["normalized/player_match_minutes.json"], "normalized/player_match_minutes.json")
    identity_record = identity.get("record")
    season_record = season.get("record")
    if not isinstance(identity_record, dict) or not isinstance(season_record, dict):
        raise TeamFollowLoadError("Faltan los registros de identidad o temporada normalizados.")
    if identity_record.get("team_id") != team_id or identity_record.get("team_url") != catalog_team.team_url:
        raise TeamFollowLoadError("La identidad normalizada no coincide con el catálogo.")
    if any(season_record.get(key) != value for key, value in {"team_id": team_id, "season": FOLLOW_SEASON, "group": group_label, "competition_scope": "Liga"}.items()):
        raise TeamFollowLoadError("La temporada normalizada tiene otro ámbito.")
    for document, label in ((minutes_doc, "minutos"), (players_doc, "jugadores"), (memberships_doc, "pertenencias")):
        metadata = document.get("metadata") or {}
        if metadata.get("capture_id") != capture_id or metadata.get("team_id") != team_id or metadata.get("season") != FOLLOW_SEASON or metadata.get("group") != group_label:
            raise TeamFollowLoadError(f"El JSON de {label} no pertenece a esta captura.")

    player_records = players_doc.get("records")
    membership_records = memberships_doc.get("records")
    minute_records = minutes_doc.get("records")
    if not isinstance(player_records, list) or not isinstance(membership_records, list) or not isinstance(minute_records, list) or not player_records:
        raise TeamFollowLoadError("Faltan listas normalizadas de jugadores, pertenencias o minutos.")
    player_ids = [record.get("player_id") for record in player_records]
    if any(type(value) is not int or value <= 0 for value in player_ids) or len(set(player_ids)) != len(player_ids):
        raise TeamFollowLoadError("Los jugadores tienen IDs ausentes o duplicados.")
    player_id_set = set(player_ids)
    membership_by_player: dict[int, dict[str, Any]] = {}
    for record in membership_records:
        player_id = record.get("player_id")
        if player_id in membership_by_player or player_id not in player_id_set:
            raise TeamFollowLoadError("Las pertenencias no enlazan de forma única con los jugadores.")
        if any(record.get(key) != value for key, value in {"team_id": team_id, "season": FOLLOW_SEASON, "group": group_label}.items()):
            raise TeamFollowLoadError("Una pertenencia está fuera del equipo, grupo o temporada.")
        membership_by_player[player_id] = record
    players = [TeamFollowPlayerResponse.model_validate({
        "player_id": record["player_id"], "display_name": record["display_name"],
        "profile_url": record.get("profile_url"), "photo_url": record.get("photo_url"),
        "jersey_number": membership_by_player.get(record["player_id"], {}).get("jersey_number"),
    }) for record in player_records]

    match_by_id = {match.match_id: match for match in dataset.bootstrap.matches}
    team_by_id = {team.team_id: team for team in dataset.bootstrap.teams}
    if len(match_by_id) != len(dataset.bootstrap.matches):
        raise TeamFollowLoadError("El catálogo activo de partidos repite match_id.")
    minutes: list[TeamFollowMinutesResponse] = []
    minute_keys: set[tuple[int, str]] = set()
    for record in minute_records:
        _check_scope(record, team_id=team_id, group=group_label, label="minutos")
        key = (record.get("player_id"), str(record.get("match_id")))
        if key in minute_keys or key[0] not in player_id_set:
            raise TeamFollowLoadError("Los minutos repiten jugador-partido o refieren un jugador desconocido.")
        minute_keys.add(key)
        match = _require_team_match(record, match_by_id, team_id)
        value = record.get("value")
        if value is not None and (type(value) is not int or value < 0):
            raise TeamFollowLoadError("Los minutos deben ser un entero no negativo o null.")
        if record.get("metric") != "minutes_played" or record.get("source_state") != "p" or record.get("source_view") != "follow":
            raise TeamFollowLoadError("La procedencia de minutos no corresponde al estado Partidos.")
        if record.get("matchday") != match.matchday:
            raise TeamFollowLoadError("La jornada de minutos no coincide con el partido enlazado.")
        if not isinstance(record.get("raw_value"), str):
            raise TeamFollowLoadError("Falta el valor original de minutos.")
        minutes.append(TeamFollowMinutesResponse.model_validate({
            "player_id": record["player_id"], "match_id": match.match_id, "matchday": match.matchday,
            "minutes_played": value, "source_value": record["raw_value"],
            "source_view": record["source_view"], "source_state": record["source_state"],
        }))
    if not minutes or not all(state == "p" for state in {record["source_state"] for record in minute_records}):
        raise TeamFollowLoadError("No hay minutos de Seguimiento respaldados por el estado p.")
    captured_states.add("p")

    metric_path = "normalized/player_match_metrics.json"
    metric_records: list[dict[str, Any]] = []
    if metric_path in follow_sha:
        if not _valid_sha(follow_sha.get(metric_path)):
            raise TeamFollowLoadError("El índice no fija un hash válido para métricas.")
        metric_bytes = _path_inside(capture_dir, metric_path).read_bytes()
        if _sha256(metric_bytes) != follow_sha[metric_path]:
            raise TeamFollowLoadError("Las métricas por partido no superan SHA-256.")
        metric_doc = _decode(metric_bytes, metric_path)
        metric_metadata = metric_doc.get("metadata") or {}
        if any(metric_metadata.get(key) != value for key, value in {"capture_id": capture_id, "team_id": team_id, "season": FOLLOW_SEASON, "group": group_label}.items()):
            raise TeamFollowLoadError("Las métricas no pertenecen a la captura seleccionada.")
        metric_records_value = metric_doc.get("records")
        if not isinstance(metric_records_value, list):
            raise TeamFollowLoadError("Las métricas no contienen una lista de registros.")
        metric_records = metric_records_value
        declared_states_value = metric_doc.get("captured_states")
        if not isinstance(declared_states_value, list) or set(declared_states_value) != captured_states:
            raise TeamFollowLoadError("Los estados del JSON normalizado no coinciden con los snapshots originales verificados.")

    metrics: list[TeamFollowMetricResponse] = []
    metric_keys: set[tuple[int, str, str]] = set()
    for record in metric_records:
        _check_scope(record, team_id=team_id, group=group_label, label="métricas")
        metric_name = record.get("metric")
        source_state = record.get("source_state")
        expected_state = {"yellow_cards": "t", "red_cards": "t", "goals": "go"}.get(metric_name)
        key = (record.get("player_id"), str(record.get("match_id")), str(metric_name))
        if expected_state is None or source_state != expected_state or expected_state not in captured_states:
            raise TeamFollowLoadError("Una métrica no está respaldada por su estado fuente.")
        if key in metric_keys or key[0] not in player_id_set:
            raise TeamFollowLoadError("Las métricas duplican jugador-partido-tipo o refieren un jugador desconocido.")
        metric_keys.add(key)
        match = _require_team_match(record, match_by_id, team_id)
        value = record.get("value")
        if type(value) is not int or value <= 0 or record.get("matchday") != match.matchday:
            raise TeamFollowLoadError("Una métrica requiere un valor positivo y una jornada coherente.")
        if record.get("source_view") != "follow" or not isinstance(record.get("raw_value"), str):
            raise TeamFollowLoadError("Falta la procedencia original de una métrica.")
        metrics.append(TeamFollowMetricResponse.model_validate({
            "player_id": record["player_id"], "match_id": match.match_id, "matchday": match.matchday,
            "metric": metric_name, "value": value, "source_value": record["raw_value"],
            "source_view": record["source_view"], "source_state": source_state,
        }))

    referenced_ids = {item.match_id for item in minutes} | {item.match_id for item in metrics}
    referenced_matches = [match_by_id[match_id] for match_id in referenced_ids]
    referenced_matches.sort(key=lambda match: (match.matchday, match.match_id))
    matches = [TeamFollowMatchResponse.model_validate({
        "match_id": match.match_id, "matchday": match.matchday,
        "matchday_date": match.matchday_date, "source_match_date": match.source_match_date,
        "home_team_id": match.home_team_id, "home_team_name": team_by_id[match.home_team_id].name,
        "away_team_id": match.away_team_id, "away_team_name": team_by_id[match.away_team_id].name,
        "home_goals": match.home_goals, "away_goals": match.away_goals, "status": match.status,
    }) for match in referenced_matches]
    matchdays = sorted({match.matchday for match in matches})

    coverage: list[TeamFollowStateCoverageResponse] = []
    for state in FOLLOW_STATES:
        state_metrics = [
            item for item in metrics
            if (item.metric in {"yellow_cards", "red_cards"} and state == "t")
            or (item.metric == "goals" and state == "go")
        ]
        available = state in captured_states
        if state == "p":
            known_values = [item.minutes_played for item in minutes]
            count = len(minutes)
            total = sum(value for value in known_values if value is not None) if all(value is not None for value in known_values) else None
            days = matchdays
        elif state in {"t", "go"}:
            selected = [item for item in state_metrics if item.source_state == state]
            count, total, days = len(selected), sum(item.value for item in selected) if available else None, matchdays if available else []
        else:
            count, total, days = 0, None, matchdays if available else []
        coverage.append(TeamFollowStateCoverageResponse(state=state, available=available, record_count=count, value_total=total, matchdays=days))

    warnings = [
        str(value) for value in validation.get("warnings", [])
        if isinstance(value, str)
        and "match_id de la ficha se usan como referencias" not in value
    ]
    if not {"t", "go"}.issubset(captured_states):
        missing = []
        if "t" not in captured_states:
            missing.append("tarjetas")
        if "go" not in captured_states:
            missing.append("goles")
        warnings.append(
            "La captura no incluye eventos de "
            + " ni ".join(missing)
            + "; no se han inferido."
        )
    derived_states = sorted(
        state for state, info in state_manifest.items()
        if isinstance(info, dict) and info.get("status") == "DERIVED_OFFLINE"
    )
    derived_times = [
        str(info["derived_at_utc"])
        for info in state_manifest.values()
        if isinstance(info, dict) and info.get("status") == "DERIVED_OFFLINE" and isinstance(info.get("derived_at_utc"), str)
    ]
    content_sha = hashlib.sha256(json.dumps({
        "contract_version": FOLLOW_CONTRACT_VERSION,
        "team_id": team_id,
        "season": FOLLOW_SEASON,
        "capture_id": capture_id,
        "files": {**{key: files_sha[key] for key in FOLLOW_INDEX_FILES[:-1]}, **follow_sha},
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    metadata = TeamFollowMetadataResponse.model_validate({
        "contract_version": FOLLOW_CONTRACT_VERSION, "source": "BDFutbol",
        "url": follow_evidence["url"], "competition": capture["competition"],
        "competition_scope": capture["competition_scope"], "season": capture["season"],
        "group": group_label, "team_id": team_id, "capture_id": capture_id,
        "captured_at": capture["captured_at_utc"],
        "extractor_version": capture.get("extractor_version", "unknown"),
        "content_sha256": content_sha, "match_capture_id": active_group_capture,
        "match_catalog_sha256": active_match_hash,
        "derived_states": derived_states,
        "derived_at": max(derived_times) if derived_times else None,
    })
    try:
        return TeamFollowResponse.model_validate({
            "status": "available", "metadata": metadata, "team": catalog_team,
            "players": players, "matches": matches, "matchdays": matchdays,
            "minutes": minutes, "metrics": metrics, "coverage": coverage,
            "warnings": list(dict.fromkeys(warnings)),
        })
    except ValidationError as exc:
        raise TeamFollowLoadError("La respuesta de Seguimiento no cumple el contrato público.") from exc


def _check_scope(record: dict[str, Any], *, team_id: int, group: str, label: str) -> None:
    if any(record.get(key) != value for key, value in {"team_id": team_id, "season": FOLLOW_SEASON, "competition": "Primera Federación", "group": group}.items()):
        raise TeamFollowLoadError(f"Registro de {label} fuera del equipo, grupo o temporada.")


def _require_team_match(record: dict[str, Any], matches: dict[str, Any], team_id: int) -> Any:
    match_id = str(record.get("match_id"))
    match = matches.get(match_id)
    if match is None or team_id not in {match.home_team_id, match.away_team_id}:
        raise TeamFollowLoadError(f"match_id={match_id} no pertenece al catálogo de partidos de este equipo.")
    return match


def _decode(payload: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TeamFollowLoadError(f"JSON ilegible: {label}.") from exc
    if not isinstance(value, dict):
        raise TeamFollowLoadError(f"El JSON no es un objeto: {label}.")
    return value


def _path_inside(root: Path, relative: str) -> Path:
    base = root.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(base):
        raise TeamFollowLoadError("Una ruta de evidencia sale del directorio de captura.")
    return path


def _decompress(payload: bytes, compression: Any, path: str) -> bytes:
    return gzip.decompress(payload) if compression == "gzip" or path.endswith(".gz") else payload


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)
