"""Load explicitly published, source-verified team transfer captures."""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import ValidationError

from football_data_hub.providers.bdfutbol.teams.parser import parse_team_transfers_snapshot
from football_data_hub_api.schemas import (
    TeamResponse,
    TeamTransferRecordResponse,
    TeamTransferSectionResponse,
    TeamTransfersResponse,
)
from football_data_hub_api.team_roster_dataset import TeamRosterRegistry

logger = logging.getLogger("football_data_hub_api.team_transfers")
TRANSFERS_SEASON = "2026-27"
TRANSFERS_CONTRACT_VERSION = 1
TRANSFERS_REQUIRED_FILES = (
    "metadata/capture.json",
    "validation/results.json",
    "raw/access.json",
    "raw/transfers.html.gz",
    "normalized/team_identity.json",
    "normalized/team_season.json",
    "normalized/transfers.json",
)


class TeamTransfersLoadError(ValueError):
    """A selected capture did not pass the transfer publication checks."""


@dataclass(frozen=True, slots=True)
class TeamTransfersRegistry:
    known_teams: dict[int, tuple[str, TeamResponse]]
    profiles: dict[int, TeamTransfersResponse]
    profile_errors: dict[int, str]
    index_error: str | None
    unavailable_group_errors: dict[str, str]


def load_team_transfers_registry(
    index_path: Path | None,
    *,
    roster_registry: TeamRosterRegistry,
    unavailable_group_errors: dict[str, str] | None = None,
) -> TeamTransfersRegistry:
    """Validate fixed capture selections once; request handlers read memory only."""
    known = roster_registry.known_teams
    if index_path is None:
        return TeamTransfersRegistry(known, {}, {}, "No hay un índice de capturas de equipo configurado.", unavailable_group_errors or {})
    try:
        index = json.loads(index_path.expanduser().read_text(encoding="utf-8"))
        if not isinstance(index, dict) or index.get("schema_version") != 1 or index.get("season") != TRANSFERS_SEASON:
            raise ValueError("versión o temporada de índice no compatible")
        entries = index.get("profiles")
        if not isinstance(entries, dict):
            raise ValueError("el índice no contiene perfiles")
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        logger.exception("Índice de Traspasos no disponible")
        return TeamTransfersRegistry(known, {}, {}, f"Índice de Traspasos inválido: {exc}", unavailable_group_errors or {})

    profiles: dict[int, TeamTransfersResponse] = {}
    errors: dict[int, str] = {}
    for team_key, entry in entries.items():
        try:
            team_id = int(team_key)
            if team_id not in known:
                raise TeamTransfersLoadError("El equipo de la captura no existe en los catálogos publicados.")
            if not isinstance(entry, dict):
                raise TeamTransfersLoadError("La entrada del perfil no es un objeto.")
            if "transfers_files_sha256" not in entry:
                continue
            selected_roster = roster_registry.profiles.get(team_id)
            if selected_roster is None or selected_roster.metadata.capture_id != entry.get("capture_id"):
                raise TeamTransfersLoadError(
                    "Traspasos no pertenece a la captura de Plantilla validada para este equipo."
                )
            group, team = known[team_id]
            profiles[team_id] = _load_selected_transfers(
                team_id,
                entry,
                index_path=index_path.expanduser(),
                group_label=group,
                catalog_team=team,
            )
        except (OSError, ValueError, TypeError, KeyError, ValidationError, gzip.BadGzipFile) as exc:
            try:
                team_id = int(team_key)
            except (TypeError, ValueError):
                continue
            errors[team_id] = str(exc)
            logger.exception("Traspasos seleccionados para team_id=%s no son válidos", team_id)
    return TeamTransfersRegistry(known, profiles, errors, None, unavailable_group_errors or {})


def _load_selected_transfers(
    team_id: int,
    entry: dict[str, Any],
    *,
    index_path: Path,
    group_label: str,
    catalog_team: TeamResponse,
) -> TeamTransfersResponse:
    capture_id = entry.get("capture_id")
    directory_value = entry.get("directory")
    expected_hashes = entry.get("transfers_files_sha256")
    if not isinstance(capture_id, str) or not capture_id or not isinstance(directory_value, str) or not directory_value:
        raise TeamTransfersLoadError("Falta la selección explícita de captura de Traspasos.")
    if not isinstance(expected_hashes, dict) or any(
        not _is_sha256(expected_hashes.get(relative)) for relative in TRANSFERS_REQUIRED_FILES
    ):
        raise TeamTransfersLoadError("El índice no fija todas las huellas de Traspasos y su procedencia.")
    capture_dir_value = Path(directory_value).expanduser()
    capture_dir = capture_dir_value.resolve() if capture_dir_value.is_absolute() else (index_path.parent / capture_dir_value).resolve()
    if capture_dir.name != capture_id:
        raise TeamTransfersLoadError("El directorio no coincide con capture_id.")

    file_bytes: dict[str, bytes] = {}
    for relative in TRANSFERS_REQUIRED_FILES:
        payload = _path_inside(capture_dir, relative).read_bytes()
        if _sha256(payload) != expected_hashes[relative]:
            raise TeamTransfersLoadError(f"El SHA-256 no coincide en {relative}.")
        file_bytes[relative] = payload

    capture = _decode(file_bytes["metadata/capture.json"], "metadata/capture.json")
    validation = _decode(file_bytes["validation/results.json"], "validation/results.json")
    access = _decode(file_bytes["raw/access.json"], "raw/access.json")
    identity_doc = _decode(file_bytes["normalized/team_identity.json"], "normalized/team_identity.json")
    season_doc = _decode(file_bytes["normalized/team_season.json"], "normalized/team_season.json")
    transfer_doc = _decode(file_bytes["normalized/transfers.json"], "normalized/transfers.json")
    if capture.get("schema_version") != 1 or capture.get("capture_id") != capture_id:
        raise TeamTransfersLoadError("Metadatos de captura incompatibles con el índice.")
    expected_identity = {
        "source": "BDFutbol", "section": "team_profile", "team_id": team_id,
        "team_name": catalog_team.name, "team_url": catalog_team.team_url,
        "season": TRANSFERS_SEASON, "competition": "Primera Federación",
        "competition_scope": "Liga", "group": group_label,
    }
    if any(capture.get(key) != value for key, value in expected_identity.items()):
        raise TeamTransfersLoadError("La identidad, fuente, grupo o temporada de la captura no coincide.")
    if validation.get("valid") is not True or validation.get("summary", {}).get("team_id") != team_id:
        raise TeamTransfersLoadError("La captura no supera la validación semántica para Traspasos.")
    summary = validation.get("summary", {})
    if "transfers" not in (capture.get("requested_views") or []) or summary.get("transfer_sections") is None:
        raise TeamTransfersLoadError("La captura no demuestra ambas secciones de Traspasos.")

    for document in (identity_doc, season_doc, transfer_doc):
        if document.get("schema_version") != 1:
            raise TeamTransfersLoadError("Versión no compatible en un JSON normalizado de Traspasos.")
        metadata = document.get("metadata") or {}
        if any(metadata.get(key) != capture.get(key) for key in ("capture_id", "team_id", "season", "group")):
            raise TeamTransfersLoadError("Los JSON normalizados pertenecen a otra captura o equipo.")
    identity = identity_doc.get("record") or {}
    season_record = season_doc.get("record") or {}
    if identity.get("team_id") != team_id or identity.get("team_url") != catalog_team.team_url:
        raise TeamTransfersLoadError("La identidad normalizada no coincide con el catálogo de equipos.")
    if any(season_record.get(key) != value for key, value in (("team_id", team_id), ("season", TRANSFERS_SEASON), ("group", group_label))):
        raise TeamTransfersLoadError("El contexto normalizado no coincide con el equipo seleccionado.")
    normalized_hash = _sha256(file_bytes["normalized/transfers.json"])
    manifest_hash = (capture.get("normalized_snapshots") or {}).get("transfers.json", {}).get("sha256")
    if manifest_hash != normalized_hash:
        raise TeamTransfersLoadError("El manifiesto no coincide con normalized/transfers.json.")

    evidence = (capture.get("source_snapshots") or {}).get("transfers") or {}
    access_view = (access.get("views") or {}).get("transfers") or {}
    source_path = evidence.get("path")
    if (
        source_path != "raw/transfers.html.gz"
        or evidence.get("compression") != "gzip"
        or evidence.get("access_status") != "VALID"
        or evidence.get("http_status") != 200
        or access_view.get("status") != "VALID"
        or access_view.get("http_status") != 200
        or access_view.get("final_url") != evidence.get("url")
    ):
        raise TeamTransfersLoadError("La vista Traspasos no tiene evidencia de acceso original válida.")
    if catalog_team.name not in str(evidence.get("title") or "") or TRANSFERS_SEASON not in str(evidence.get("title") or ""):
        raise TeamTransfersLoadError("El título del snapshot no confirma el equipo y la temporada seleccionados.")
    source_html = gzip.decompress(file_bytes["raw/transfers.html.gz"])
    source_sha = _sha256(source_html)
    access_snapshot_hash = access_view.get("source_snapshot_sha256")
    if source_sha != evidence.get("sha256") or access_snapshot_hash not in {None, source_sha}:
        raise TeamTransfersLoadError("El HTML de origen no supera la huella SHA-256 publicada.")
    expected_url = _transfer_url(catalog_team.team_url)
    if evidence.get("url") != expected_url or access_view.get("requested_url") != expected_url:
        raise TeamTransfersLoadError("La evidencia de origen no corresponde a la vista Traspasos del equipo.")

    records_data = transfer_doc.get("records")
    sections_data = transfer_doc.get("sections")
    if not isinstance(records_data, list) or not isinstance(sections_data, list):
        raise TeamTransfersLoadError("El JSON no declara registros y secciones separados.")
    publication_evidence = entry.get("transfers_evidence")
    expected_publication_evidence = {
        "capture_id": capture_id,
        "team_id": team_id,
        "season": TRANSFERS_SEASON,
        "group": group_label,
        "source_snapshot": {
            "path": "raw/transfers.html.gz",
            "sha256": source_sha,
            "url": expected_url,
        },
        "normalized": {"path": "normalized/transfers.json", "sha256": normalized_hash},
        "sections": sections_data,
    }
    if publication_evidence != expected_publication_evidence:
        raise TeamTransfersLoadError("La evidencia fijada en el índice no coincide con la captura seleccionada.")
    reparsed, reparsed_sections = parse_team_transfers_snapshot(
        source_html.decode("utf-8"),
        team_id=team_id,
        season=TRANSFERS_SEASON,
        competition="Primera Federación",
        group=group_label,
        base_url=catalog_team.team_url,
    )
    if records_data != [asdict(record) for record in reparsed] or sections_data != [asdict(section) for section in reparsed_sections]:
        raise TeamTransfersLoadError("Los registros normalizados no corresponden al HTML original de Traspasos.")
    if summary.get("transfer_sections") != {
        item.direction: {"status": item.status, "rows": item.row_count} for item in reparsed_sections
    }:
        raise TeamTransfersLoadError("La validación guardada no corresponde a las secciones del HTML.")

    section_models = [TeamTransferSectionResponse.model_validate(item) for item in sections_data]
    transfer_models = [TeamTransferRecordResponse.model_validate(item) for item in records_data]
    captured_at = capture.get("captured_at_utc")
    derived_at = (capture.get("derivation") or {}).get("derived_at_utc")
    content_digest = hashlib.sha256(
        (f"{normalized_hash}:{source_sha}:{TRANSFERS_CONTRACT_VERSION}").encode("ascii")
    ).hexdigest()
    response = TeamTransfersResponse.model_validate({
        "status": "available",
        "metadata": {
            "contract_version": TRANSFERS_CONTRACT_VERSION,
            "validation_status": "valid",
            "source": "BDFutbol",
            "url": evidence["url"],
            "competition": "Primera Federación",
            "competition_scope": "Liga",
            "season": TRANSFERS_SEASON,
            "group": group_label,
            "team_id": team_id,
            "capture_id": capture_id,
            "captured_at": captured_at,
            "derived_at": derived_at,
            "extractor_version": str(capture.get("extractor_version") or "unknown"),
            "source_sha256": source_sha,
            "content_sha256": content_digest,
        },
        "sections": section_models,
        "incoming": [row for row in transfer_models if row.direction == "incoming"],
        "outgoing": [row for row in transfer_models if row.direction == "outgoing"],
        "warnings": [
            "Los equipos relacionados conservan las URLs e IDs publicados por BDFutbol; algunos enlaces pueden ser históricos."
        ],
    })
    return response


def _transfer_url(team_url: str) -> str:
    parts = urlsplit(team_url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}?t=altas"


def _path_inside(root: Path, relative: str) -> Path:
    base = root.resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(base):
        raise TeamTransfersLoadError("Una ruta de la captura sale de su directorio versionado.")
    return target


def _decode(payload: bytes, name: str) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TeamTransfersLoadError(f"JSON ilegible: {name}.") from exc
    if not isinstance(value, dict):
        raise TeamTransfersLoadError(f"El contenido JSON no es un objeto: {name}.")
    return value


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)
