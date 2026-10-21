"""Loopback-only incremental updates using existing BDFutbol pipelines.

Competition snapshots are acquired sequentially, validated, compared by stable
IDs, and activated automatically only when the generation is conflict-free.
Team capture helpers remain for historical job compatibility; they are not
exposed by the current update API.
"""

from __future__ import annotations

import fcntl
import gzip
import hashlib
import hmac
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit, parse_qs

from football_data_hub_api.config import GroupDatasetSettings


class ManualUpdateError(RuntimeError):
    """A requested update could not be safely prepared."""


class UpdateAlreadyRunning(ManualUpdateError):
    """Another update owns the browser or the requested scope."""


TEAM_FOLLOW_AUTO_POLICY_ID = "validated-incremental-team-follow-v1"
TEAM_PROFILE_REFRESH_VIEWS = ("squad", "statistics", "follow")


def _has_related_section_changes(sections: object) -> bool:
    """Whether a candidate contains at least one activated related capture."""
    if not isinstance(sections, dict):
        return False
    groups = sections.get("groups", {})
    if isinstance(groups, dict) and any(
        isinstance(group_sections, dict) and bool(group_sections)
        for group_sections in groups.values()
    ):
        return True
    return bool(sections.get("referees"))


def _team_match_ids_by_group(
    matches_by_group: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, dict[int, set[str]]], dict[str, dict[int, dict[str, Any]]]]:
    """Return played fixture IDs per club and the validated match catalogs."""
    played: dict[str, dict[int, set[str]]] = {"I": {}, "II": {}}
    matches: dict[str, dict[int, dict[str, Any]]] = {"I": {}, "II": {}}
    for group in ("I", "II"):
        for match in matches_by_group.get(group, []):
            match_id = str(match.get("match_id") or "")
            home_id = match.get("home_team_id")
            away_id = match.get("away_team_id")
            if not match_id or type(home_id) is not int or type(away_id) is not int:
                raise ManualUpdateError(f"El catálogo del Grupo {group} contiene un partido sin identidad completa.")
            if match_id in matches[group]:
                raise ManualUpdateError(f"El catálogo del Grupo {group} contiene match_id duplicado {match_id}.")
            matches[group][match_id] = match
            if match.get("status") == "played":
                if match.get("home_goals") is None or match.get("away_goals") is None:
                    raise ManualUpdateError(f"El partido disputado {match_id} no tiene marcador verificable.")
                for team_id in (home_id, away_id):
                    played[group].setdefault(team_id, set()).add(match_id)
    return played, matches


def _follow_covered_match_ids(
    records: list[dict[str, Any]],
    *,
    team_id: int,
    group: str,
    matches: dict[str, dict[str, Any]],
) -> set[str]:
    """Identify played matches with at least one observed numeric minute.

    Upcoming fixtures can already occur in BDFutbol's matrix with blank cells;
    those rows do not count as coverage. Numeric zeroes are preserved as real
    observations but coverage requires at least one positive minute in the match.
    """
    values_by_match: dict[str, list[int]] = {}
    identities: set[tuple[int, str]] = set()
    for row in records:
        if not isinstance(row, dict):
            raise ManualUpdateError(f"Seguimiento de team_id={team_id} contiene una fila inválida.")
        if (
            row.get("team_id") != team_id
            or row.get("season") != "2026-27"
            or row.get("group") != group
            or row.get("metric") != "minutes_played"
        ):
            raise ManualUpdateError(f"Seguimiento de team_id={team_id} mezcla identidad, temporada o métrica.")
        match_id = str(row.get("match_id") or "")
        match = matches.get(match_id)
        if match is None or team_id not in {match.get("home_team_id"), match.get("away_team_id")}:
            raise ManualUpdateError(f"Seguimiento referencia un partido ajeno o desconocido: {match_id}.")
        try:
            player_id = int(row["player_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ManualUpdateError(f"Seguimiento de team_id={team_id} contiene un jugador sin ID.") from exc
        key = (player_id, match_id)
        if key in identities:
            raise ManualUpdateError(f"Seguimiento contiene la pareja jugador/partido duplicada: {player_id}/{match_id}.")
        identities.add(key)
        value = row.get("value")
        if value is not None:
            if type(value) is not int or value < 0:
                raise ManualUpdateError(f"Seguimiento contiene minutos no válidos para {player_id}/{match_id}.")
            values_by_match.setdefault(match_id, []).append(value)
    return {
        match_id
        for match_id, values in values_by_match.items()
        if matches[match_id].get("status") == "played" and any(value > 0 for value in values)
    }


def _verified_follow_state_bytes(
    capture_dir: Path,
    *,
    state: str,
    evidence: dict[str, Any],
    indexed_file_hashes: dict[str, Any],
    indexed_state_hashes: dict[str, Any] | None = None,
) -> bytes:
    """Verify both the stored snapshot bytes and its decompressed HTML hash.

    Team publication indexes hash compressed files, while capture metadata's
    ``sha256`` identifies the uncompressed HTML. They are distinct integrity
    checks and must not be compared to each other.
    """
    relative = Path(str(evidence.get("path") or ""))
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ManualUpdateError(f"El estado de Seguimiento {state} tiene una ruta inválida.")
    unresolved = capture_dir / relative
    _reject_symlink_components(unresolved)
    path = unresolved.resolve()
    if not path.is_relative_to(capture_dir.resolve()) or not path.is_file():
        raise ManualUpdateError(f"El estado de Seguimiento {state} no tiene un snapshot dentro de la captura.")
    expected_file_hash = indexed_file_hashes.get(relative.as_posix())
    payload = path.read_bytes()
    if not isinstance(expected_file_hash, str) or _sha256(payload) != expected_file_hash:
        raise ManualUpdateError(f"El archivo fuente del estado de Seguimiento {state} no supera SHA-256.")
    compression = evidence.get("compression")
    try:
        if compression == "gzip":
            content = gzip.decompress(payload)
        elif compression in {None, "none", "identity"}:
            content = payload
        else:
            raise ManualUpdateError(f"Compresión no reconocida para Seguimiento {state}.")
    except (OSError, EOFError, zlib.error) as exc:
        raise ManualUpdateError(f"El snapshot comprimido del estado {state} está corrupto.") from exc
    content_hash = _sha256(content)
    if content_hash != evidence.get("sha256"):
        raise ManualUpdateError(f"El HTML descomprimido del estado {state} no coincide con sus metadatos.")
    if indexed_state_hashes is not None:
        indexed_state_hash = indexed_state_hashes.get(state)
        if indexed_state_hash is not None and indexed_state_hash != content_hash:
            raise ManualUpdateError(f"El índice y los metadatos discrepan en el estado de Seguimiento {state}.")
    return content


def apply_active_group_data(settings: GroupDatasetSettings, group: str, data_root: Path | None) -> GroupDatasetSettings:
    """Resolve the last reviewed group-source pointer, if one has been activated."""
    if data_root is None:
        return settings
    if (data_root / "operations" / "manual-updates" / "activation-pending.json").exists():
        raise ManualUpdateError("Hay una activación de competición interrumpida; se requiere recuperación administrativa antes de servir datos mezclados.")
    pointer_path = data_root / "operations" / "manual-updates" / "active-group-data.json"
    if pointer_path.is_symlink():
        raise ManualUpdateError("El puntero activo del grupo es un symlink.")
    if not pointer_path.is_file():
        return settings
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        if pointer.get("schema_version") not in {
            "football_data_hub.manual_group_data.v1",
            "football_data_hub.manual_group_data.v2",
        }:
            raise ValueError("versión de puntero no compatible")
        entry = pointer.get("groups", {}).get(group)
        if not isinstance(entry, dict):
            raise ValueError(f"el puntero no contiene el Grupo {group}")
        paths: dict[str, Path] = {}
        for key in ("matches", "classification", "progress", "capture_metadata"):
            item = entry.get(key)
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                raise ValueError(f"ruta {key} ausente")
            relative = Path(item["path"])
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"ruta {key} debe ser relativa a la raíz")
            unresolved = data_root / relative
            _reject_symlink_components(unresolved)
            path = unresolved.resolve()
            if not path.is_relative_to(data_root.resolve()) or not path.is_file():
                raise ValueError(f"ruta {key} fuera de la raíz o no disponible")
            if _sha256(path.read_bytes()) != item.get("sha256"):
                raise ValueError(f"hash {key} alterado")
            paths[key] = path
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise ManualUpdateError(f"El puntero activo del Grupo {group} no supera la verificación: {exc}") from exc
    replacement = replace(
        settings,
        matches_path=paths["matches"],
        classification_path=paths["classification"],
        progress_path=paths["progress"],
        capture_metadata_path=paths["capture_metadata"],
    )
    return replacement


def apply_active_group_sections(
    settings: GroupDatasetSettings, group: str, data_root: Path | None
) -> GroupDatasetSettings:
    """Resolve optional TOP/STAT captures independently from core Results.

    A missing or corrupt optional section must not prevent the verified
    classification/results catalogue from loading.
    """
    pointer = _read_active_pointer(data_root)
    if pointer is None:
        return settings
    sections = pointer.get("sections", {})
    groups = sections.get("groups", {}) if isinstance(sections, dict) else {}
    group_sections = groups.get(group, {}) if isinstance(groups, dict) else {}
    if not isinstance(group_sections, dict):
        raise ManualUpdateError(f"Las secciones activas del Grupo {group} no cumplen el contrato.")
    replacement = settings
    top_root = _verified_active_section_root(data_root, group_sections.get("top")) if data_root else None
    if top_root is not None:
        replacement = replace(
            replacement,
            top_players_path=top_root / "normalized/players.json",
            top_rankings_path=top_root / "normalized/rankings.json",
            top_progress_path=top_root / "normalized/progress.json",
            top_foreigners_path=top_root / "normalized/foreigners.json",
            top_capture_metadata_path=top_root / "metadata/capture.json",
            top_validation_path=top_root / "validation/results.json",
            top_source_html_path=top_root / "raw/source.html",
            top_team_catalog_path=None,
        )
    statistics_root = _verified_active_section_root(data_root, group_sections.get("statistics")) if data_root else None
    if statistics_root is not None:
        replacement = replace(replacement, statistics_root=statistics_root)
    return replacement


def apply_active_group_section(
    settings: GroupDatasetSettings,
    group: str,
    data_root: Path | None,
    section: str,
) -> GroupDatasetSettings:
    """Resolve one optional section while keeping failures section-local."""
    if section not in {"top", "statistics"}:
        raise ValueError("Sección de grupo no válida")
    pointer = _read_active_pointer(data_root)
    if pointer is None:
        return settings
    sections = pointer.get("sections", {})
    groups = sections.get("groups", {}) if isinstance(sections, dict) else {}
    group_sections = groups.get(group, {}) if isinstance(groups, dict) else {}
    if not isinstance(group_sections, dict):
        raise ManualUpdateError(f"Las secciones activas del Grupo {group} no cumplen el contrato.")
    root = _verified_active_section_root(data_root, group_sections.get(section)) if data_root else None
    if root is None:
        return settings
    if section == "statistics":
        return replace(settings, statistics_root=root)
    return replace(
        settings,
        top_players_path=root / "normalized/players.json",
        top_rankings_path=root / "normalized/rankings.json",
        top_progress_path=root / "normalized/progress.json",
        top_foreigners_path=root / "normalized/foreigners.json",
        top_capture_metadata_path=root / "metadata/capture.json",
        top_validation_path=root / "validation/results.json",
        top_source_html_path=root / "raw/source.html",
        top_team_catalog_path=None,
    )


def apply_active_referee_data(settings: Any, data_root: Path | None) -> Any:
    """Resolve a versioned REF capture from the same atomic active-data pointer."""
    pointer = _read_active_pointer(data_root)
    if pointer is None:
        return settings
    root = _verified_active_section_root(data_root, pointer.get("sections", {}).get("referees"))
    return replace(settings, referees_root=root) if root is not None else settings


def _read_active_pointer(data_root: Path | None) -> dict[str, Any] | None:
    if data_root is None:
        return None
    pointer_path = data_root / "operations" / "manual-updates" / "active-group-data.json"
    if pointer_path.is_symlink():
        raise ManualUpdateError("El puntero activo de grupos es un symlink.")
    if not pointer_path.is_file():
        return None
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        if pointer.get("schema_version") not in {
            "football_data_hub.manual_group_data.v1",
            "football_data_hub.manual_group_data.v2",
        }:
            raise ValueError("versión de puntero no compatible")
        if not isinstance(pointer.get("groups"), dict):
            raise ValueError("grupos ausentes")
        return pointer
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ManualUpdateError(f"El puntero activo de secciones no se pudo verificar: {exc}") from exc


def _verified_active_section_root(data_root: Path, entry: Any) -> Path | None:
    if entry is None:
        return None
    if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
        raise ManualUpdateError("Una ruta de sección activa no cumple el contrato.")
    relative = Path(entry["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ManualUpdateError("La ruta de sección activa debe ser relativa a FDH_LOCAL_DATA_ROOT.")
    unresolved = data_root / relative
    _reject_symlink_components(unresolved)
    root = unresolved.resolve()
    if not root.is_relative_to(data_root.resolve()) or not root.is_dir():
        raise ManualUpdateError("La captura activa de sección no está disponible en el almacén.")
    if _tree_sha256(root) != entry.get("sha256"):
        raise ManualUpdateError("El hash de una captura activa de sección cambió.")
    return root


def _activate_group_data_pointer(data_root: Path, candidate: dict[str, Any]) -> str:
    pointer_path = data_root / "operations" / "manual-updates" / "active-group-data.json"
    if pointer_path.is_symlink():
        raise ManualUpdateError("El puntero activo de grupos es un symlink; se detuvo.")
    if pointer_path.is_file():
        pointer_bytes = pointer_path.read_bytes()
        pointer = json.loads(pointer_bytes)
        if pointer.get("schema_version") not in {
            "football_data_hub.manual_group_data.v1",
            "football_data_hub.manual_group_data.v2",
        } or not isinstance(pointer.get("groups"), dict):
            raise ManualUpdateError("El puntero activo de grupos no cumple el contrato esperado.")
        groups = dict(pointer["groups"])
    else:
        pointer_bytes = None
        groups = {}
    sources = candidate.get("source_captures") or {}
    normalized = candidate.get("normalized_matches") or {}
    if not candidate.get("no_competition_changes", candidate.get("no_changes") is True):
        for group in ("I", "II"):
            capture_root_unresolved = Path(sources[group])
            match_path_unresolved = Path(normalized[group])
            _reject_symlink_components(capture_root_unresolved)
            _reject_symlink_components(match_path_unresolved)
            capture_root = capture_root_unresolved.resolve()
            match_path = match_path_unresolved.resolve()
            values = {
                "matches": match_path,
                "classification": capture_root / "normalized/classification.json",
                "progress": capture_root / "normalized/progress.json",
                "capture_metadata": capture_root / "metadata/capture.json",
            }
            entry = {}
            for key, path in values.items():
                if not path.is_relative_to(data_root.resolve()) or not path.is_file() or path.is_symlink():
                    raise ManualUpdateError(f"El nuevo archivo activo de Grupo {group} no está en el almacén verificado.")
                entry[key] = {
                    "path": path.relative_to(data_root.resolve()).as_posix(),
                    "sha256": _sha256(path.read_bytes()),
                }
            capture = json.loads(values["capture_metadata"].read_text(encoding="utf-8"))
            entry["capture_id"] = capture.get("capture_id")
            entry["activated_at"] = utc_now()
            groups[group] = entry
    sections = dict(pointer.get("sections", {})) if pointer_bytes is not None else {}
    related = candidate.get("related_sections", {})
    group_sections = dict(sections.get("groups", {}))
    for group, section_map in (related.get("groups", {}) if isinstance(related, dict) else {}).items():
        if group not in {"I", "II"} or not isinstance(section_map, dict):
            raise ManualUpdateError("El candidato contiene una sección de grupo desconocida.")
        active_group_sections = dict(group_sections.get(group, {}))
        for section, item in section_map.items():
            if section not in {"top", "statistics"} or not isinstance(item, dict):
                raise ManualUpdateError("El candidato contiene una captura de sección inválida.")
            root_unresolved = Path(str(item.get("path", "")))
            _reject_symlink_components(root_unresolved)
            root = root_unresolved.resolve()
            digest = _tree_sha256(root)
            if not root.is_relative_to(data_root.resolve()) or digest != item.get("sha256"):
                raise ManualUpdateError(f"La captura {section} del Grupo {group} no supera integridad/procedencia.")
            active_group_sections[section] = {
                "path": root.relative_to(data_root.resolve()).as_posix(),
                "sha256": digest,
                "capture_id": item.get("capture_id"),
            }
        group_sections[group] = active_group_sections
    if group_sections:
        sections["groups"] = group_sections
    referee_item = related.get("referees") if isinstance(related, dict) else None
    if isinstance(referee_item, dict):
        root_unresolved = Path(str(referee_item.get("path", "")))
        _reject_symlink_components(root_unresolved)
        root = root_unresolved.resolve()
        digest = _tree_sha256(root)
        if not root.is_relative_to(data_root.resolve()) or digest != referee_item.get("sha256"):
            raise ManualUpdateError("La captura de Árbitros no supera integridad/procedencia.")
        sections["referees"] = {
            "path": root.relative_to(data_root.resolve()).as_posix(),
            "sha256": digest,
            "capture_id": referee_item.get("capture_id"),
        }
    if pointer_bytes is not None:
        history = pointer_path.parent / "active-group-data-history"
        history.mkdir(parents=True, exist_ok=True, mode=0o700)
        previous_id = _sha256(pointer_bytes)
        history_path = history / f"{previous_id}.json"
        _create_once(history_path, pointer_bytes)
    _atomic_json(pointer_path, {
        "schema_version": "football_data_hub.manual_group_data.v2" if sections else "football_data_hub.manual_group_data.v1",
        "season": "2026-27",
        "groups": groups,
        **({"sections": sections} if sections else {}),
        "updated_at": utc_now(),
    })
    return _sha256(pointer_path.read_bytes())


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _candidate_sha256(candidate: dict[str, Any]) -> str:
    body = {key: value for key, value in candidate.items() if key != "candidate_sha256"}
    return _sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode())


def _legacy_statistics_section_identity(
    capture_root: Path, metadata: dict[str, Any], validation: dict[str, Any], group: str
) -> bool:
    """Recognize older statistics exports whose metadata omitted ``section``.

    Identity is recovered only from the exact expected BDFutbol statistics URL
    plus matching, valid HTTP/access evidence in the immutable capture. The
    normal statistics dataset loader still performs the full hash and semantic
    validation afterwards.
    """
    if metadata.get("section") is not None:
        return False
    from football_data_hub.providers.bdfutbol.context import get_competition_context

    expected_url = get_competition_context(group=1 if group == "I" else 2).section_url("statistics")
    try:
        access = json.loads((capture_root / "raw/access.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    source_page = validation.get("source_page")
    if not isinstance(source_page, dict):
        return False
    requested = metadata.get("requested_url")
    final = metadata.get("final_url")
    parsed = urlsplit(str(requested or ""))
    return bool(
        requested == expected_url
        and final == expected_url
        and metadata.get("http_status") == 200
        and access.get("status") == "VALID"
        and access.get("http_status") == 200
        and access.get("requested_url") == expected_url
        and access.get("final_url") == expected_url
        and source_page.get("access_status") == "VALID"
        and source_page.get("http_status") == 200
        and source_page.get("requested_url") == expected_url
        and source_page.get("final_url") == expected_url
        and parsed.hostname == "www.bdfutbol.com"
        and parse_qs(parsed.query).get("tab") == ["stats"]
    )


def public_manual_update_job(job: dict[str, Any] | None) -> dict[str, Any] | None:
    """Project only user-facing progress; source paths and integrity hashes stay local."""
    if job is None:
        return None
    error = job.get("error")
    log_tail = job.get("log_tail")
    if isinstance(error, str) and "código " in error and isinstance(log_tail, str):
        error = _friendly_process_failure(log_tail, error)
    elif isinstance(error, str) and error.startswith("ManualUpdateError: "):
        error = error.removeprefix("ManualUpdateError: ")
    return {
        key: job.get(key)
        for key in ("job_id", "scope", "team_id", "group", "status", "stage",
                    "created_at", "updated_at", "finished_at", "summary")
    } | {
        "error": error,
        "progress": (
            {
                "completed": job["match_details_progress"].get("completed", 0),
                "total": job["match_details_progress"].get("total", 0),
            }
            if isinstance(job.get("match_details_progress"), dict)
            else None
        ),
    }


def _friendly_process_failure(log_tail: str, fallback: str) -> str:
    """Summarize known subprocess failures without returning private paths/logs."""
    if "FileExistsError" in log_tail and "validation/matches.json" in log_tail:
        group = "II" if "group-ii" in log_tail else "I"
        return (
            f"Falló la normalización de partidos del Grupo {group}: el informe de "
            "validación ya existía en una ruta compartida. Las capturas se conservaron "
            "y no se reintentó la adquisición."
        )
    diagnostic_lines = [
        line.strip()
        for line in log_tail.splitlines()
        if re.search(r"\b[A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception)\s*:", line)
    ]
    if not diagnostic_lines:
        return fallback
    diagnostic = diagnostic_lines[-1]
    diagnostic = re.sub(r"['\"]/(?:[^\s'\"]+/)*[^\s'\"]*['\"]", "<ruta local>", diagnostic)
    diagnostic = re.sub(r"(?<![\w:])/(?:[^\s:'\"]+/)*[^\s:'\"]+", "<ruta local>", diagnostic)
    return f"Falló un proceso de actualización. Diagnóstico: {diagnostic[:240]}"


def _reject_symlink_components(path: Path) -> None:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current = current / component
        try:
            if current.is_symlink():
                raise ManualUpdateError(f"La ruta contiene un symlink no permitido: {current}")
        except OSError as exc:
            raise ManualUpdateError(f"No se pudo comprobar la ruta {current}.") from exc


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    data = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def _create_once(path: Path, data: bytes) -> None:
    """Atomically create an immutable artifact without replacing history."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ManualUpdateError(f"El artefacto inmutable es un symlink: {path}")
    if path.exists():
        if path.read_bytes() != data:
            raise ManualUpdateError(f"El artefacto inmutable ya existe con otros bytes: {path}")
        return
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes() != data:
                raise ManualUpdateError(f"El artefacto inmutable apareció con contenido diferente: {path}")
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def _tree_sha256(root: Path) -> str:
    """Hash a capture tree by relative file names and bytes; reject links."""
    _reject_symlink_components(root)
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ManualUpdateError(f"La captura no es un directorio normal: {root}")
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if path.is_symlink():
            raise ManualUpdateError(f"La captura contiene un symlink no permitido: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ManualUpdateError(f"La captura contiene un archivo especial: {path}")
        relative = path.relative_to(root).as_posix().encode("utf-8")
        data = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _tail(path: Path, limit: int = 5000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-limit:]
    except OSError:
        return ""


def _last_json_object(text: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    parsed: dict[str, Any] | None = None
    best_end = -1
    best_start = len(text)
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, size = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        end = index + size
        # Worker logs contain several JSON receipts (one per captured group,
        # then the activation receipt). Select the final complete object, not
        # the largest one: the final activation receipt is intentionally much
        # smaller than either capture receipt.
        if isinstance(value, dict) and (end > best_end or (end == best_end and index < best_start)):
            parsed = value
            best_end = end
            best_start = index
    if parsed is None:
        raise ManualUpdateError("El comando terminó sin un recibo JSON verificable.")
    return parsed


def _sports_projection(path: Path, *, kind: str) -> Any:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if kind == "classification":
        rows = payload.get("standings")
        if not isinstance(rows, list):
            raise ManualUpdateError(f"No hay filas de clasificación verificables en {path}.")
        return sorted(rows, key=lambda row: int(row["team_id"]))
    teams = payload.get("teams")
    matches = payload.get("matches")
    if not isinstance(teams, list) or not isinstance(matches, list):
        raise ManualUpdateError(f"No hay equipos y partidos normalizados verificables en {path}.")
    team_fields = ("team_id", "name", "team_name", "team_url", "crest_url")
    match_fields = (
        "match_id", "matchday", "matchday_date", "source_match_date",
        "home_team_id", "away_team_id", "home_goals", "away_goals",
        "home_yellow_cards", "away_yellow_cards", "home_red_cards", "away_red_cards",
        "status", "unplayed_state", "postponed_by_source_rule", "source_match_url",
        "stadium_id", "stadium_name", "stadium_url", "referee_id", "referee_name", "referee_url",
    )
    projected_teams = [
        {key: row.get(key) for key in team_fields if key in row}
        for row in sorted(teams, key=lambda item: int(item["team_id"]))
    ]

    def match_key(row: dict[str, Any]) -> str:
        return str(row.get("match_id") or row.get("source_match_id") or "")

    projected_matches = [
        {key: row.get(key) for key in match_fields if key in row}
        for row in sorted(matches, key=match_key)
    ]
    return {"teams": projected_teams, "matches": projected_matches}


def _sports_section_changed(candidate: Path, active: Path, *, kind: str) -> bool:
    try:
        new_data = _sports_projection(candidate, kind=kind)
        active_data = _sports_projection(active, kind=kind)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise ManualUpdateError(f"No se pudo comparar de forma segura {kind}: {exc}") from exc
    return json.dumps(new_data, sort_keys=True, ensure_ascii=False) != json.dumps(
        active_data, sort_keys=True, ensure_ascii=False
    )


def _classification_changes(candidate: Path, active: Path) -> list[dict[str, Any]]:
    try:
        new_rows = _sports_projection(candidate, kind="classification")
        old_rows = _sports_projection(active, kind="classification")
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise ManualUpdateError(f"No se pudo comparar de forma segura la clasificación: {exc}") from exc
    old_by_id = {int(row["team_id"]): row for row in old_rows}
    changes: list[dict[str, Any]] = []
    for row in new_rows:
        team_id = int(row["team_id"])
        before = old_by_id.get(team_id)
        if before is None:
            changes.append({"team_id": team_id, "kind": "team_added"})
            continue
        fields = [
            {"field": field, "before": before.get(field), "after": value}
            for field, value in row.items()
            if before.get(field) != value
        ]
        if fields:
            changes.append({"team_id": team_id, "kind": "standing_changed", "changes": fields})
    new_ids = {int(row["team_id"]) for row in new_rows}
    changes.extend(
        {"team_id": team_id, "kind": "team_missing"}
        for team_id in sorted(set(old_by_id) - new_ids)
    )
    return changes


def _progress_changes(candidate: Path, active: Path) -> list[dict[str, Any]]:
    try:
        new_payload = json.loads(candidate.read_text(encoding="utf-8"))
        old_payload = json.loads(active.read_text(encoding="utf-8"))
        new_rows, old_rows = new_payload.get("records"), old_payload.get("records")
        if not isinstance(new_rows, list) or not isinstance(old_rows, list):
            raise ValueError("progress records ausentes")
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ManualUpdateError(f"No se pudo comparar de forma segura el progreso: {exc}") from exc
    old_by_key = {(int(row["team_id"]), int(row["matchday"])): row for row in old_rows}
    changes: list[dict[str, Any]] = []
    for row in new_rows:
        key = (int(row["team_id"]), int(row["matchday"]))
        before = old_by_key.get(key)
        if before is None:
            changes.append({"team_id": key[0], "matchday": key[1], "kind": "record_added"})
            continue
        fields = [
            {"field": field, "before": value, "after": row.get(field)}
            for field, value in before.items()
            if field in row and value != row.get(field)
        ]
        if fields:
            changes.append({"team_id": key[0], "matchday": key[1], "kind": "record_changed", "changes": fields})
    new_keys = {(int(row["team_id"]), int(row["matchday"])) for row in new_rows}
    changes.extend(
        {"team_id": team_id, "matchday": matchday, "kind": "record_missing"}
        for team_id, matchday in sorted(set(old_by_key) - new_keys)
    )
    return changes


_PROVENANCE_FIELDS = {
    "capture_id", "captured_at", "captured_at_utc", "created_at_utc",
    "source_capture_id", "source_captured_at_utc", "source_snapshot_sha256",
    "extractor_version", "parent_extractor_version",
}


def _without_capture_provenance(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_capture_provenance(item)
            for key, item in value.items()
            if key not in _PROVENANCE_FIELDS and key != "metadata"
        }
    if isinstance(value, list):
        return [_without_capture_provenance(item) for item in value]
    return value


def _related_section_content_sha256(root: Path, section: str) -> str:
    """Hash normalized source data, excluding capture-specific provenance."""
    files_by_section = {
        "top": (
            "normalized/players.json", "normalized/rankings.json",
            "normalized/progress.json", "normalized/foreigners.json",
        ),
        "statistics": (
            "normalized/derived_statistics.json", "normalized/exclusive_statistics.json",
        ),
        "referees": (
            "normalized/referees.json", "normalized/statistics.json",
            "normalized/filter_options.json",
        ),
    }
    if section not in files_by_section:
        raise ManualUpdateError(f"Sección relacionada desconocida: {section}")
    digest = hashlib.sha256()
    for relative in files_by_section[section]:
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise ManualUpdateError(f"Falta un archivo normalizado de {section}: {relative}.")
        try:
            payload = _without_capture_provenance(json.loads(path.read_text(encoding="utf-8")))
            canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        except (OSError, ValueError, TypeError) as exc:
            raise ManualUpdateError(f"No se pudo comparar el contenido normalizado de {section}.") from exc
        encoded_name = relative.encode("utf-8")
        digest.update(len(encoded_name).to_bytes(8, "big"))
        digest.update(encoded_name)
        digest.update(len(canonical).to_bytes(8, "big"))
        digest.update(canonical)
    return digest.hexdigest()


def _team_comparison_value(relative: str, value: Any) -> Any:
    cleaned = _without_capture_provenance(value)
    if relative == "normalized/transfers.json" and isinstance(cleaned, dict):
        records = cleaned.get("records")
        if not isinstance(records, list):
            raise ManualUpdateError("La vista normalizada de traspasos no contiene una colección verificable.")
        keyed: list[tuple[tuple[str, int], dict[str, Any]]] = []
        for record in records:
            if not isinstance(record, dict) or record.get("direction") not in {"incoming", "outgoing"}:
                raise ManualUpdateError("La vista de traspasos contiene una dirección no verificable.")
            try:
                player_id = int(record["player_id"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ManualUpdateError("La vista de traspasos contiene un jugador sin ID verificable.") from exc
            keyed.append(((str(record["direction"]), player_id), record))
        keys = [key for key, _record in keyed]
        if len(keys) != len(set(keys)):
            raise ManualUpdateError("La vista de traspasos contiene movimientos duplicados por dirección e ID de jugador.")
        cleaned["records"] = [record for _key, record in sorted(keyed, key=lambda item: item[0])]
    return cleaned


def _team_change_details(
    candidate_dir: Path,
    prior_dir: Path | None,
    changed_files: list[str],
) -> list[dict[str, Any]]:
    """Build a compact, semantic review summary from the two verified captures."""
    if prior_dir is None:
        return [{"section": "Perfil del equipo", "items": ["Se publicó la primera captura verificada."]}]

    def payload(base: Path, relative: str) -> Any:
        try:
            return _without_capture_provenance(json.loads((base / relative).read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError) as exc:
            raise ManualUpdateError(f"No se pudo preparar la revisión de {relative}.") from exc

    def player_names(base: Path) -> dict[int, str]:
        players_payload = payload(base, "normalized/players.json")
        records = players_payload.get("records") if isinstance(players_payload, dict) else None
        if not isinstance(records, list):
            raise ManualUpdateError("La captura no contiene un catálogo de jugadores verificable para la revisión.")
        return {
            int(record["player_id"]): str(record.get("display_name") or record.get("full_name") or record["player_id"])
            for record in records
            if isinstance(record, dict) and record.get("player_id") is not None
        }

    old_names = player_names(prior_dir)
    new_names = player_names(candidate_dir)
    names = {**old_names, **new_names}
    field_labels = {
        "jersey_number": "dorsal",
        "matches_played": "partidos jugados",
        "starts": "titularidades",
        "full_matches": "partidos completos",
        "minutes_played": "minutos",
        "minutes_per_goal": "minutos por gol",
        "goals": "goles",
        "penalty_goals": "goles de penalti",
        "own_goals": "autogoles",
        "yellow_cards": "tarjetas amarillas",
        "red_cards": "tarjetas rojas",
        "team_wins": "victorias del equipo",
        "team_draws": "empates del equipo",
        "team_losses": "derrotas del equipo",
        "matches_substituted": "partidos sustituidos",
        "substitute_appearances": "entradas desde el banquillo",
        "unused_substitute_calls": "convocatorias como suplente sin entrar",
        "goals_conceded": "goles recibidos",
        "matches_managed": "partidos dirigidos",
        "coached_matchdays_source": "jornadas dirigidas",
    }

    def display(value: Any) -> str:
        if value is None:
            return "—"
        if isinstance(value, list):
            return ", ".join(map(str, value)) or "—"
        return str(value)

    def row_details(relative: str, *, key_field: str, section: str) -> dict[str, Any] | None:
        old_payload = payload(prior_dir, relative)
        new_payload = payload(candidate_dir, relative)
        old_rows = old_payload.get("records") if isinstance(old_payload, dict) else None
        new_rows = new_payload.get("records") if isinstance(new_payload, dict) else None
        if not isinstance(old_rows, list) or not isinstance(new_rows, list):
            raise ManualUpdateError(f"La vista {relative} no contiene filas para revisar.")
        old_by_id = {int(row[key_field]): row for row in old_rows if isinstance(row, dict) and row.get(key_field) is not None}
        new_by_id = {int(row[key_field]): row for row in new_rows if isinstance(row, dict) and row.get(key_field) is not None}
        items: list[str] = []
        identity_fields = {key_field, "team_id", "season", "competition", "group", "source_view", "source_views"}
        for record_id in sorted(set(old_by_id) | set(new_by_id)):
            before = old_by_id.get(record_id)
            after = new_by_id.get(record_id)
            if before is None or after is None:
                kind = "añadido" if before is None else "retirado"
                items.append(f"{names.get(record_id, str(record_id))} (#{record_id}): registro {kind}.")
                continue
            fields = sorted((set(before) | set(after)) - identity_fields)
            changes = [
                f"{field_labels.get(field, field.replace('_', ' '))} {display(before.get(field))} → {display(after.get(field))}"
                for field in fields if before.get(field) != after.get(field)
            ]
            if changes:
                items.append(f"{names.get(record_id, str(record_id))} (#{record_id}): " + "; ".join(changes) + ".")
        return {"section": section, "items": items} if items else None

    details: list[dict[str, Any]] = []
    for relative, section in (
        ("normalized/memberships.json", "Plantilla"),
        ("normalized/player_statistics.json", "Estadísticas de jugadores"),
    ):
        if relative in changed_files:
            detail = row_details(relative, key_field="player_id", section=section)
            if detail:
                details.append(detail)

    for relative, section, record_label in (
        ("normalized/player_match_minutes.json", "Seguimiento · minutos", "registros de minutos"),
        ("normalized/player_match_metrics.json", "Seguimiento · eventos", "métricas"),
    ):
        if relative not in changed_files:
            continue
        old_rows = payload(prior_dir, relative).get("records", [])
        new_rows = payload(candidate_dir, relative).get("records", [])
        key_fields = ("match_id", "player_id", "metric")

        def row_key(row: dict[str, Any]) -> tuple[str, ...]:
            return tuple(str(row.get(field)) for field in key_fields)

        old_by_key = {row_key(row): row for row in old_rows if isinstance(row, dict)}
        new_by_key = {row_key(row): row for row in new_rows if isinstance(row, dict)}
        grouped: dict[tuple[str, str], dict[str, Any]] = {}
        for item_key in set(old_by_key) | set(new_by_key):
            before = old_by_key.get(item_key)
            after = new_by_key.get(item_key)
            row = after or before
            assert row is not None
            group_key = (str(row.get("matchday") or "?"), str(row.get("match_id") or "?"))
            bucket = grouped.setdefault(group_key, {"added": 0, "removed": 0, "updated": 0, "metrics": {}})
            change_kind = "added" if before is None else "removed" if after is None else "updated"
            if before is None or after is None or before != after:
                bucket[change_kind] += 1
                metric = str(row.get("metric") or "registro")
                bucket["metrics"][metric] = bucket["metrics"].get(metric, 0) + (1 if change_kind == "added" else 0)
        items = []
        for (matchday, match_id), bucket in sorted(grouped.items(), key=lambda item: (item[0][0], item[0][1])):
            if not (bucket["added"] or bucket["removed"] or bucket["updated"]):
                continue
            singular_label = "registro de minutos" if relative.endswith("minutes.json") else "métrica"
            status = f"+{bucket['added']} {singular_label if bucket['added'] == 1 else record_label}"
            if bucket["removed"]:
                status += f", −{bucket['removed']} retirados"
            if bucket["updated"]:
                status += f", {bucket['updated']} actualizados"
            metrics = bucket["metrics"]
            if metrics and relative == "normalized/player_match_metrics.json":
                plural_labels = {
                    "goals": ("gol", "goles"),
                    "yellow_cards": ("tarjeta amarilla", "tarjetas amarillas"),
                    "red_cards": ("tarjeta roja", "tarjetas rojas"),
                    "own_goals": ("autogol", "autogoles"),
                }
                metric_labels = []
                for metric, count in sorted(metrics.items()):
                    singular, plural = plural_labels.get(metric, (field_labels.get(metric, metric.replace('_', ' ')), field_labels.get(metric, metric.replace('_', ' '))))
                    metric_labels.append(f"{count} {singular if count == 1 else plural}")
                status += " (" + ", ".join(metric_labels) + ")"
            items.append(f"Jornada {matchday}, partido {match_id}: {status}.")
        if items:
            details.append({"section": section, "items": items})

    if "normalized/profile_references.json" in changed_files:
        before = payload(prior_dir, "normalized/profile_references.json")
        after = payload(candidate_dir, "normalized/profile_references.json")
        items = []
        for key in ("match_ids_from_profile", "team_ids_from_profile"):
            old_values = set(map(str, before.get(key, [])))
            new_values = set(map(str, after.get(key, [])))
            added, removed = sorted(new_values - old_values), sorted(old_values - new_values)
            entity = "partidos" if key == "match_ids_from_profile" else "equipos"
            if added:
                items.append(f"Nuevos {entity} referenciados: {', '.join(added)}.")
            if removed:
                items.append(f"{entity.capitalize()} que dejaron de estar referenciados: {', '.join(removed)}.")
        if items:
            details.append({"section": "Referencias del perfil", "items": items})

    if "normalized/team_season.json" in changed_files:
        before = payload(prior_dir, "normalized/team_season.json").get("record", {})
        after = payload(candidate_dir, "normalized/team_season.json").get("record", {})
        old_coaches = {int(item["coach_id"]): item for item in before.get("coaches", []) if item.get("coach_id") is not None}
        new_coaches = {int(item["coach_id"]): item for item in after.get("coaches", []) if item.get("coach_id") is not None}
        items = []
        for coach_id in sorted(set(old_coaches) | set(new_coaches)):
            old, new = old_coaches.get(coach_id), new_coaches.get(coach_id)
            if old is None or new is None:
                items.append(f"Entrenador #{coach_id}: registro {'añadido' if old is None else 'retirado'}.")
                continue
            name = str(new.get("display_name") or old.get("display_name") or f"#{coach_id}")
            changes = [
                f"{field_labels.get(field, field.replace('_', ' '))} {display(old.get(field))} → {display(new.get(field))}"
                for field in sorted(set(old) | set(new))
                if field not in {"coach_id", "source_views"} and old.get(field) != new.get(field)
            ]
            if changes:
                items.append(f"{name} (#{coach_id}): " + "; ".join(changes) + ".")
        if items:
            details.append({"section": "Entrenador y temporada", "items": items})

    summarized = {
        "normalized/memberships.json", "normalized/player_statistics.json",
        "normalized/player_match_minutes.json", "normalized/player_match_metrics.json",
        "normalized/profile_references.json", "normalized/team_season.json",
    }
    for relative in changed_files:
        if relative not in summarized:
            details.append({"section": "Otros datos del equipo", "items": [f"Cambió {relative.removeprefix('normalized/').removesuffix('.json').replace('_', ' ')}."]})
    return details


def _team_data_changes(
    candidate_dir: Path,
    prior_entry: dict[str, Any],
    index_path: Path,
) -> list[str]:
    # Published team indexes split normalized-file hashes across several
    # fields (core profile, follow states, transfers, and the complete
    # normalized inventory). Merge all of them before comparing; silently
    # omitting one makes a verified historical view look corrupt.
    old_hashes: dict[str, str] = {}
    for field in (
        "files_sha256",
        "normalized_files_sha256",
        "follow_files_sha256",
        "transfers_files_sha256",
    ):
        values = prior_entry.get(field) or {}
        if not isinstance(values, dict):
            raise ManualUpdateError(f"El índice del equipo contiene hashes inválidos en {field}.")
        for name, digest in values.items():
            name = str(name)
            if not name.startswith("normalized/"):
                continue
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest.lower())
            ):
                raise ManualUpdateError(f"El índice del equipo contiene un SHA-256 inválido para {name}.")
            previous_digest = old_hashes.get(name)
            if previous_digest is not None and not hmac.compare_digest(previous_digest, digest):
                raise ManualUpdateError(f"El índice del equipo contiene hashes contradictorios para {name}.")
            old_hashes[name] = digest
    prior_value = prior_entry.get("directory")
    if not prior_value:
        return sorted(path.relative_to(candidate_dir).as_posix() for path in (candidate_dir / "normalized").glob("*.json"))
    prior_root_value = Path(str(prior_value)).expanduser()
    prior_dir = prior_root_value.resolve() if prior_root_value.is_absolute() else (index_path.parent / prior_root_value).resolve()
    if prior_dir.name != prior_entry.get("capture_id"):
        raise ManualUpdateError("La ruta de la captura anterior no coincide con su capture_id publicado.")
    changes: list[str] = []
    candidate_files = {
        path.relative_to(candidate_dir).as_posix(): path
        for path in (candidate_dir / "normalized").glob("*.json")
        if path.is_file()
    }
    prior_files = {
        path.relative_to(prior_dir).as_posix(): path
        for path in (prior_dir / "normalized").glob("*.json")
        if path.is_file()
    }
    for relative in sorted(set(candidate_files) | set(old_hashes) | set(prior_files)):
        new_path = candidate_files.get(relative)
        old_path = prior_dir / relative
        old_exists = old_path.is_file()
        expected_hash = old_hashes.get(relative)
        if old_exists and expected_hash is None:
            raise ManualUpdateError(f"La captura publicada no tiene un hash verificable para {relative}.")
        if not old_exists and expected_hash is not None:
            raise ManualUpdateError(f"El índice declara una vista publicada ausente: {relative}.")
        if old_exists:
            actual_hash = hashlib.sha256(old_path.read_bytes()).hexdigest()
            if not hmac.compare_digest(actual_hash, expected_hash or ""):
                raise ManualUpdateError(f"La captura publicada del equipo no supera la comprobación de integridad: {relative}.")
        if new_path is None or not old_exists:
            changes.append(relative)
            continue
        try:
            new_payload = _team_comparison_value(relative, json.loads(new_path.read_text(encoding="utf-8")))
            old_payload = _team_comparison_value(relative, json.loads(old_path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError) as exc:
            raise ManualUpdateError(f"No se pudo comparar la vista normalizada {relative}.") from exc
        if json.dumps(new_payload, ensure_ascii=False, sort_keys=True) != json.dumps(old_payload, ensure_ascii=False, sort_keys=True):
            changes.append(relative)
    return changes


class ManualUpdateManager:
    """Run a single scoped refresh at a time and keep durable job receipts."""

    def __init__(
        self,
        *,
        project_root: Path,
        data_root: Path | None,
        profile_dir: Path,
        browser_executable: Path | None,
        group_match_paths: dict[str, Path],
        group_classification_paths: dict[str, Path],
        group_progress_paths: dict[str, Path],
        team_profiles_index: Path | None,
        match_generation_root: Path | None,
        match_details_store_root: Path | None,
        player_inventory_root: Path | None,
        player_compact_root: Path | None,
        player_team_captures_root: Path | None,
        player_published_index_path: Path | None,
        match_details_published_root: Path | None = None,
        group_related_settings: dict[str, GroupDatasetSettings] | None = None,
        referees_root: Path | None = None,
        api_settings: Any | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.data_root = data_root.resolve() if data_root else None
        self.profile_dir = profile_dir.expanduser().resolve()
        self.browser_executable = browser_executable.expanduser().resolve() if browser_executable else None
        self.group_match_paths = {key: value.resolve() for key, value in group_match_paths.items()}
        self.group_classification_paths = {key: value.resolve() for key, value in group_classification_paths.items()}
        self.group_progress_paths = {key: value.resolve() for key, value in group_progress_paths.items()}
        self.team_profiles_index = team_profiles_index.resolve() if team_profiles_index else None
        self.match_generation_root = match_generation_root.resolve() if match_generation_root else None
        self.match_details_store_root = match_details_store_root.resolve() if match_details_store_root else None
        self.player_inventory_root = player_inventory_root.resolve() if player_inventory_root else None
        self.player_compact_root = player_compact_root.resolve() if player_compact_root else None
        self.player_team_captures_root = player_team_captures_root.resolve() if player_team_captures_root else None
        self.player_published_index_path = player_published_index_path.resolve() if player_published_index_path else None
        self.match_details_published_root = match_details_published_root.resolve() if match_details_published_root else None
        self.group_related_settings = dict(group_related_settings or {})
        self.referees_root = referees_root.resolve() if referees_root else None
        self.api_settings = api_settings
        self.root = (self.data_root / "operations" / "manual-updates") if self.data_root else None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fdh-manual-update")
        self._mutex = threading.RLock()
        self._leases: dict[str, tuple[int, int]] = {}
        self._active_processes: set[subprocess.Popen[bytes]] = set()
        self.on_competition_applied: Callable[[dict[str, Any]], None] | None = None
        self.on_match_details_published: Callable[[dict[str, Any]], None] | None = None
        self._recover_interrupted_jobs()

    def close(self) -> None:
        """Stop owned acquisition process groups when the API is shutting down."""
        with self._mutex:
            processes = tuple(self._active_processes)
        for process in processes:
            if process.poll() is not None:
                continue
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=8)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        self._executor.shutdown(wait=False, cancel_futures=False)

    @property
    def enabled(self) -> bool:
        return bool(
            self.root and self.data_root
            and not self.data_root.is_relative_to(self.project_root)
        )

    def scope_enabled(self, scope: str) -> bool:
        if not self.enabled:
            return False
        pending_path = self.root / "activation-pending.json"  # type: ignore[operator]
        if pending_path.exists():
            if scope != "competition":
                return False
            try:
                journal = json.loads(pending_path.read_text(encoding="utf-8"))
                pending_job = self._read(str(journal.get("job_id") or ""))
            except (OSError, ValueError):
                return False
            return bool(
                pending_job
                and pending_job.get("scope") == "competition"
                and pending_job.get("status") == "review_required"
                and isinstance(pending_job.get("candidate"), dict)
            )
        if scope == "competition":
            return bool(
                self.match_generation_root and self.match_generation_root.is_dir()
                and not self.match_generation_root.is_relative_to(self.project_root)
                and self.match_details_store_root and self.match_details_store_root.is_dir()
                and not self.match_details_store_root.is_relative_to(self.project_root)
                and self.match_details_published_root and self.match_details_published_root.is_dir()
                and not self.match_details_published_root.is_relative_to(self.project_root)
                and self.player_inventory_root and self.player_inventory_root.is_dir()
                and not self.player_inventory_root.is_relative_to(self.project_root)
                and self.player_compact_root and self.player_compact_root.is_dir()
                and not self.player_compact_root.is_relative_to(self.project_root)
                and self.player_team_captures_root and self.player_team_captures_root.is_dir()
                and not self.player_team_captures_root.is_relative_to(self.project_root)
                and self.player_published_index_path and self.player_published_index_path.is_file()
                and not self.player_published_index_path.is_relative_to(self.project_root)
                and set(self.group_match_paths) == {"I", "II"}
                and set(self.group_classification_paths) == {"I", "II"}
                and set(self.group_progress_paths) == {"I", "II"}
                and all(path.is_file() for path in self.group_match_paths.values())
                and all(path.is_file() for path in self.group_classification_paths.values())
                and all(path.is_file() for path in self.group_progress_paths.values())
            )
        if scope == "team":
            return bool(
                self.team_profiles_index and self.team_profiles_index.is_file()
                and not self.team_profiles_index.is_relative_to(self.project_root)
                and self.player_team_captures_root and self.player_team_captures_root.is_dir()
                and not self.player_team_captures_root.is_relative_to(self.project_root)
                and set(self.group_match_paths) == {"I", "II"}
                and all(path.is_file() for path in self.group_match_paths.values())
            )
        return False

    def _jobs_dir(self) -> Path:
        if self.root is None:
            raise ManualUpdateError("Configura FDH_LOCAL_DATA_ROOT para habilitar actualizaciones.")
        return self.root / "jobs"

    def _read(self, job_id: str) -> dict[str, Any] | None:
        if not job_id or any(character not in "0123456789abcdef-" for character in job_id.lower()):
            return None
        path = self._jobs_dir() / f"{job_id}.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return value if isinstance(value, dict) else None

    def _recover_interrupted_jobs(self) -> None:
        if self.root is None:
            return
        lock_dir = self.root / "locks"
        lock_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            global_fd = self._lock(lock_dir / "browser.lock")
        except UpdateAlreadyRunning:
            # A sibling API process owns a live update; never mislabel it on startup.
            return
        try:
            jobs = self._jobs_dir()
            if not jobs.is_dir():
                return
            for path in jobs.glob("*.json"):
                try:
                    item = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if isinstance(item, dict) and item.get("status") in {"queued", "running"}:
                    item.update({
                        "status": "interrupted",
                        "stage": "interrupted",
                        "updated_at": utc_now(),
                        "finished_at": utc_now(),
                        "error": "El proceso de API terminó durante la actualización. No se reanudó ni repitió ninguna navegación.",
                    })
                    _atomic_json(path, item)
        finally:
            fcntl.flock(global_fd, fcntl.LOCK_UN)
            os.close(global_fd)

    def latest(self, scope: str, team_id: int | None = None) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        latest: dict[str, Any] | None = None
        for path in self._jobs_dir().glob("*.json"):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if (
                item.get("scope") == scope
                and (scope != "team" or item.get("team_id") == team_id)
                and isinstance(item.get("created_at"), str)
            ):
                if latest is None or item["created_at"] > latest["created_at"]:
                    latest = item
        return latest

    def public_status(self, scope: str, team_id: int | None = None) -> dict[str, Any]:
        """Return timestamps only; never expose candidate data or diagnostics."""
        if not self.enabled or scope not in {"competition", "team"}:
            return {
                "scope": scope, "team_id": team_id, "last_updated_at": None,
                "last_unchanged_check_at": None, "last_checked_at": None,
            }
        published: list[dict[str, Any]] = []
        unchanged: list[dict[str, Any]] = []
        all_jobs: list[dict[str, Any]] = []
        for path in self._jobs_dir().glob("*.json"):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if item.get("scope") != scope or (scope == "team" and item.get("team_id") != team_id):
                continue
            all_jobs.append(item)
            if item.get("status") in {"applied", "applied_reload_failed"}:
                published.append(item)
            if item.get("status") == "completed":
                unchanged.append(item)
        def by_created(item: dict[str, Any]) -> str:
            return str(item.get("created_at") or "")
        latest_published = max(published, key=by_created, default=None)
        latest_unchanged = max(unchanged, key=by_created, default=None)
        latest_finished = max(
            (item for item in all_jobs if item.get("finished_at")),
            key=lambda item: str(item.get("finished_at") or ""),
            default=None,
        )
        return {
            "scope": scope,
            "team_id": team_id,
            "last_updated_at": latest_published.get("finished_at") if latest_published else None,
            "last_unchanged_check_at": latest_unchanged.get("finished_at") if latest_unchanged else None,
            "last_checked_at": latest_finished.get("finished_at") if latest_finished else None,
        }

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        return self._read(job_id)

    def start(self, *, scope: str, team_id: int | None = None, group: str | None = None) -> dict[str, Any]:
        if not self.scope_enabled(scope):
            raise ManualUpdateError(f"Actualizaciones del ámbito {scope} deshabilitadas o sin sus catálogos/índices externos necesarios.")
        if scope not in {"competition", "team"}:
            raise ValueError("Ámbito de actualización no válido")
        if (self.root / "activation-pending.json").exists():  # type: ignore[operator]
            raise ManualUpdateError("Hay una activación de competición pendiente; revisa y confirma ese mismo candidato antes de iniciar otra.")
        if scope == "team" and (team_id is None or team_id <= 0 or group not in {"I", "II"}):
            raise ValueError("El equipo debe tener ID y grupo verificados")
        if scope == "competition" and (
            self.match_generation_root is None
            or set(self.group_match_paths) != {"I", "II"}
            or set(self.group_classification_paths) != {"I", "II"}
            or set(self.group_progress_paths) != {"I", "II"}
        ):
            raise ManualUpdateError("No están configuradas las fuentes locales de ambos grupos.")

        scope_key = f"team-{team_id}" if scope == "team" else "competition-2026-27"
        lock_dir = self.root / "locks"  # type: ignore[operator]
        lock_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        global_fd = self._lock(lock_dir / "browser.lock")
        try:
            scope_fd = self._lock(lock_dir / f"{scope_key}.lock")
        except BaseException:
            fcntl.flock(global_fd, fcntl.LOCK_UN)
            os.close(global_fd)
            raise

        job_id = str(uuid.uuid4())
        job_dir = self._jobs_dir()
        try:
            job_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            job = {
            "schema_version": 1,
            "job_id": job_id,
            "scope": scope,
            "scope_key": scope_key,
            "team_id": team_id,
            "group": group,
            "season": "2026-27",
            "status": "queued",
            "stage": "queued",
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "finished_at": None,
            "summary": None,
            "candidate": None,
            "error": None,
            "log_tail": None,
            }
            _atomic_json(job_dir / f"{job_id}.json", job)
            with self._mutex:
                self._leases[job_id] = (global_fd, scope_fd)
            self._executor.submit(self._run, job)
            return job
        except BaseException:
            for descriptor in (scope_fd, global_fd):
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                finally:
                    os.close(descriptor)
            raise

    @staticmethod
    def _lock(path: Path) -> int:
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(descriptor)
            raise UpdateAlreadyRunning("Ya hay una adquisición en curso; no se inició otra navegación.") from exc
        return descriptor

    def _save(self, job: dict[str, Any]) -> None:
        job["updated_at"] = utc_now()
        _atomic_json(self._jobs_dir() / f"{job['job_id']}.json", job)

    def _run(self, job: dict[str, Any]) -> None:
        job_id = str(job["job_id"])
        log_path = self._jobs_dir() / job_id / "worker.log"
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            job.update({"status": "running", "stage": "preflight"})
            self._save(job)
            self._preflight()
            if job["scope"] == "competition":
                job["candidate"] = self._update_competition(job, log_path)
            else:
                job["candidate"] = self._update_team(job, log_path)
            job["candidate_sha256"] = _candidate_sha256(job["candidate"])
            job["candidate"]["candidate_sha256"] = job["candidate_sha256"]
            no_changes = bool(job["candidate"].get("no_changes"))
            if job["scope"] == "competition":
                self._finish_competition_update(job, log_path, no_changes=no_changes)
            else:
                # Preserve the old team-capture job contract for recovery of
                # existing records. No team-update route is exposed by the API.
                job.update({
                    "status": "completed" if no_changes else "review_required",
                    "stage": "no_changes" if no_changes else "candidate_validated",
                    "finished_at": utc_now(),
                })
                self._save(job)
        except Exception as exc:  # errors are stored for the local update panel
            failed_stage = job.get("stage")
            job.update({
                "status": "failed",
                "stage": "failed",
                "failed_stage": failed_stage,
                "finished_at": utc_now(),
                "error": f"{type(exc).__name__}: {exc}",
                "log_tail": _tail(log_path),
            })
            self._save(job)
        finally:
            with self._mutex:
                lease = self._leases.pop(job_id, None)
            if lease:
                for descriptor in lease:
                    try:
                        fcntl.flock(descriptor, fcntl.LOCK_UN)
                    finally:
                        os.close(descriptor)

    def _publish_team_follow_profiles(
        self,
        job: dict[str, Any],
        candidate: dict[str, Any],
        log_path: Path,
    ) -> dict[str, Any] | None:
        """Atomically publish validated team captures under the named local policy."""
        updates = candidate.get("team_profile_candidates")
        if not isinstance(updates, list) or not updates:
            return None
        if self.team_profiles_index is None or self.player_team_captures_root is None:
            raise ManualUpdateError("No se configuró el índice externo para publicar Seguimiento.")
        if self.team_profiles_index.is_symlink() or self.team_profiles_index.is_relative_to(self.project_root):
            raise ManualUpdateError("El índice de equipos no es un archivo externo seguro.")
        original_bytes = self.team_profiles_index.read_bytes()
        original_sha = _sha256(original_bytes)
        if original_sha != candidate.get("team_profiles_index_sha256"):
            raise ManualUpdateError("El índice de equipos cambió durante la actualización; no se publicaron capturas.")
        index = json.loads(original_bytes)
        profiles = index.get("profiles")
        if index.get("schema_version") != 1 or index.get("season") != "2026-27" or not isinstance(profiles, dict):
            raise ManualUpdateError("El índice de equipo cambió de contrato durante la actualización.")
        catalogs: dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]] = {}
        for group in ("I", "II"):
            capture_root = Path(candidate["source_captures"][group])
            matches_path = Path(candidate["normalized_matches"][group])
            _reject_symlink_components(capture_root)
            _reject_symlink_components(matches_path)
            if _tree_sha256(capture_root) != candidate.get("source_capture_sha256", {}).get(group):
                raise ManualUpdateError(f"La captura del Grupo {group} cambió antes de publicar Seguimiento.")
            if _sha256(matches_path.read_bytes()) != candidate.get("normalized_match_sha256", {}).get(group):
                raise ManualUpdateError(f"El catálogo del Grupo {group} cambió antes de publicar Seguimiento.")
            from football_data_hub.providers.bdfutbol.context import get_competition_context
            from football_data_hub.providers.bdfutbol.teams.catalog import load_team_catalog
            catalogs[group] = load_team_catalog(
                matches_path, competition=get_competition_context("2026-27", 1 if group == "I" else 2)
            )
        catalog_by_id: dict[int, tuple[str, str]] = {}
        for group in ("I", "II"):
            for team in catalogs[group][0]:
                team_id = int(team["team_id"])
                if team_id in catalog_by_id:
                    raise ManualUpdateError(f"team_id duplicado en los catálogos de publicación: {team_id}.")
                catalog_by_id[team_id] = (group, str(team.get("name") or team.get("team_name") or ""))
        if len(catalog_by_id) != 40 or set(map(int, profiles)) != set(catalog_by_id):
            raise ManualUpdateError("El índice y los catálogos de publicación no conservan los mismos 40 IDs.")

        by_team: dict[int, dict[str, Any]] = {}
        for update in updates:
            if not isinstance(update, dict):
                raise ManualUpdateError("El candidato de Seguimiento contiene una entrada inválida.")
            team_id = int(update["team_id"])
            if team_id in by_team or team_id not in catalog_by_id:
                raise ManualUpdateError(f"El candidato de Seguimiento duplica o desconoce team_id={team_id}.")
            capture_dir = Path(str(update["capture_directory"])).resolve()
            if (
                not capture_dir.is_relative_to(self.player_team_captures_root)
                or capture_dir.name != update.get("capture_id")
                or _tree_sha256(capture_dir) != update.get("capture_tree_sha256")
            ):
                raise ManualUpdateError(f"La captura incremental de team_id={team_id} cambió o sale del almacén autorizado.")
            profile = profiles[str(team_id)]
            if profile.get("capture_id") != update.get("previous_capture_id"):
                raise ManualUpdateError(f"La captura publicada de team_id={team_id} cambió durante la actualización.")
            by_team[team_id] = update

        manifest_teams = []
        for team_id, (group, name) in sorted(catalog_by_id.items()):
            current_profile = profiles[str(team_id)]
            update = by_team.get(team_id)
            selected_capture = str(update["capture_id"]) if update else current_profile.get("capture_id")
            selected_directory = str(update["capture_directory"]) if update else current_profile.get("directory")
            if not selected_capture or not selected_directory:
                raise ManualUpdateError(f"El perfil {team_id} no tiene una ruta de captura verificable.")
            resolved = Path(str(selected_directory)).expanduser().resolve()
            if not resolved.is_relative_to(self.player_team_captures_root) or resolved.name != selected_capture:
                raise ManualUpdateError(f"El manifiesto de publicación contiene una ruta no autorizada para {team_id}.")
            manifest_teams.append({
                "group": group, "team_id": team_id, "team_name": name,
                "status": "complete", "capture_id": selected_capture,
                "coverage": {"capture_path": str(resolved)},
            })
        manifest = {
            "schema_version": 1,
            "season": "2026-27",
            "run_id": f"competition-update-team-profiles-{job['job_id']}",
            "batch_complete": True,
            "stopped_on_access_denial": False,
            "stop_reason": None,
            "requested_views": ["alignment", "squad", "statistics", "follow", "transfers", "matches"],
            "required_follow_states": ["p", "t", "go", "tot"],
            "teams": manifest_teams,
        }
        manifest_path = self._jobs_dir() / str(job["job_id"]) / "team-profiles-publish-manifest.json"
        manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if manifest_path.exists():
            if manifest_path.read_bytes() != manifest_bytes:
                raise ManualUpdateError("El manifiesto de perfiles ya existe con contenido distinto; no se sobrescribirá.")
        else:
            descriptor = os.open(manifest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(manifest_bytes)
                stream.flush()
                os.fsync(stream.fileno())

        event_root = self.root / "reviews"  # type: ignore[operator]
        event_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        event_id = str(job["job_id"])
        event_base = {
            "schema_version": 1,
            "event_id": event_id,
            "policy_id": TEAM_FOLLOW_AUTO_POLICY_ID,
            "actor": "football-data-hub-local-update-service",
            "source_candidate_sha256": job.get("candidate_sha256"),
            "manifest_sha256": _sha256(manifest_bytes),
            "previous_index_sha256": original_sha,
            "team_captures": [
                {
                    "team_id": item["team_id"], "group": item["group"],
                    "previous_capture_id": item["previous_capture_id"],
                    "capture_id": item["capture_id"],
                    "capture_tree_sha256": item["capture_tree_sha256"],
                    "match_ids_added_to_follow": item["missing_match_ids"],
                    "reused_existing_capture": item["reused_existing_capture"],
                }
                for item in updates
            ],
        }
        _create_once(
            event_root / f"{event_id}-team-follow-auto-apply-started.json",
            (json.dumps({**event_base, "event": "TEAM_FOLLOW_AUTO_APPLY_STARTED", "started_at": utc_now()}, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(),
        )
        job["stage"] = "publishing_team_follow"
        self._save(job)
        output = self._command([
            sys.executable, "scripts/publish_bdfutbol_team_profiles.py",
            "--store-root", str(self.player_team_captures_root),
            "--manifest", str(manifest_path),
            "--group1-catalog", str(candidate["normalized_matches"]["I"]),
            "--group2-catalog", str(candidate["normalized_matches"]["II"]),
            "--output", str(self.team_profiles_index),
        ], log_path, timeout=1800)
        receipt = _last_json_object(output)
        new_bytes = self.team_profiles_index.read_bytes()
        new_index = json.loads(new_bytes)
        new_profiles = new_index.get("profiles")
        if not isinstance(new_profiles, dict) or set(new_profiles) != set(profiles):
            raise ManualUpdateError("La publicación incremental no conservó los 40 perfiles.")
        for team_id, (group, _name) in catalog_by_id.items():
            expected_capture = by_team[team_id]["capture_id"] if team_id in by_team else profiles[str(team_id)]["capture_id"]
            if new_profiles[str(team_id)].get("capture_id") != expected_capture:
                raise ManualUpdateError(f"La publicación no conservó la captura esperada para team_id={team_id} ({group}).")
        event = {
            **event_base,
            "event": "TEAM_FOLLOW_AUTO_APPLIED",
            "applied_at": utc_now(),
            "new_index_sha256": _sha256(new_bytes),
            "publisher_receipt": receipt,
            "unchanged_team_count": 40 - len(by_team),
        }
        _create_once(
            event_root / f"{event_id}-team-follow-auto-applied.json",
            (json.dumps(event, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(),
        )
        return {
            "status": "published",
            "policy_id": TEAM_FOLLOW_AUTO_POLICY_ID,
            "team_count": len(by_team),
            "unchanged_team_count": 40 - len(by_team),
            "index_sha256": _sha256(new_bytes),
            "publisher_receipt": receipt,
        }

    def _finish_competition_update(
        self, job: dict[str, Any], log_path: Path, *, no_changes: bool
    ) -> None:
        candidate = job.get("candidate")
        if not isinstance(candidate, dict):
            raise ManualUpdateError("La actualización no produjo un candidato verificable.")
        self._verify_candidate_fingerprint(job, candidate)
        if no_changes:
            related_changed = _has_related_section_changes(candidate.get("related_sections"))
            team_follow_publication: dict[str, Any] | None = None
            team_follow_error: str | None = None
            try:
                team_follow_publication = self._publish_team_follow_profiles(job, candidate, log_path)
            except Exception as exc:
                team_follow_error = f"{type(exc).__name__}: {str(exc)[:240]}"
                team_follow_publication = {"status": "error", "reason": team_follow_error}
            team_follow_changed = bool(team_follow_publication and team_follow_publication.get("status") == "published")
            if related_changed:
                event_root = self.root / "reviews"  # type: ignore[operator]
                event_root.mkdir(parents=True, exist_ok=True, mode=0o700)
                event_id = str(job["job_id"])
                event_base = {
                    "schema_version": 1,
                    "job_id": event_id,
                    "scope": "competition_related_sections",
                    "candidate_sha256": job["candidate_sha256"],
                    "related_section_status": candidate.get("related_section_status", {}),
                }
                _create_once(
                    event_root / f"{event_id}-sections-apply-started.json",
                    (json.dumps({**event_base, "event": "RELATED_SECTIONS_APPLY_STARTED", "started_at": utc_now()}, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(),
                )
                job.update({"status": "running", "stage": "activating_related_sections"})
                self._save(job)
                assert self.data_root is not None
                pointer_sha256 = _activate_group_data_pointer(self.data_root, candidate)
                publication = {"status": "activated", "active_pointer_sha256": pointer_sha256}
                _create_once(
                    event_root / f"{event_id}-sections-applied.json",
                    (json.dumps({
                        **event_base,
                        "event": "RELATED_SECTIONS_APPLIED",
                        "actor": "football-data-hub-local-update-service",
                        "applied_at": utc_now(),
                        "publication": publication,
                    }, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(),
                )
                job["publication"] = publication
            if (related_changed or team_follow_changed) and self.on_competition_applied is not None:
                try:
                    job["team_follow_publication"] = team_follow_publication
                    self.on_competition_applied(job)
                except Exception as exc:
                    job.update({
                        "status": "applied_reload_failed",
                        "stage": "refresh_failed",
                        "error": f"Los datos verificados quedaron activados, pero FastAPI no pudo recargarlos: {type(exc).__name__}: {exc}",
                        "summary": {
                            "outcome": "partial",
                            "message": "Las secciones cambiadas están activadas, pero la API necesita recargarse.",
                            "related_section_status": candidate.get("related_section_status", {}),
                            "team_follow_publication": team_follow_publication,
                        },
                        "finished_at": utc_now(),
                    })
                    self._save(job)
                    return
            job.update({"status": "running", "stage": "checking_match_details"})
            self._save(job)
            detail_summary = self._safe_process_new_match_details(job)
            detail_summary["team_follow_update_published"] = team_follow_changed
            summary = {
                "message": self._related_sections_message(candidate, detail_summary),
                "changed_groups": candidate.get("changed_groups", {}),
                "related_section_status": candidate.get("related_section_status", {}),
                **({"team_follow_publication": team_follow_publication} if team_follow_publication else {}),
                **({"team_follow_update_error": team_follow_error} if team_follow_error else {}),
                **detail_summary,
            }
            outcome = self._update_outcome(candidate, detail_summary, core_applied=False)
            summary["outcome"] = outcome
            if outcome == "partial" and not str(summary["message"]).startswith("Actualización parcial"):
                summary["message"] = f"Actualización parcial: {summary['message']}"
            elif outcome == "failed":
                summary["message"] = self._failure_message(candidate, detail_summary)
            terminal_status = (
                "applied"
                if related_changed or team_follow_changed or detail_summary.get("match_details_published_count")
                else "failed" if outcome == "failed" else "completed"
            )
            job.update({
                "status": terminal_status,
                "stage": "completed",
                "finished_at": utc_now(),
                "summary": summary,
                **({"error": summary["message"]} if terminal_status == "failed" else {}),
            })
            self._save(job)
            return

        if candidate.get("kind") != "competition_generation":
            raise ManualUpdateError("El resultado no es una generación de Primera Federación.")
        self._assert_automatic_competition_candidate(candidate)

        event_root = self.root / "reviews"  # type: ignore[operator]
        event_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        event_id = str(job["job_id"])
        event_base = {
            "schema_version": 1,
            "job_id": event_id,
            "scope": "competition",
            "candidate_sha256": job["candidate_sha256"],
            "candidate_generation_id": candidate.get("candidate_generation_id"),
            "report_sha256": candidate.get("report_sha256"),
        }
        _create_once(
            event_root / f"{event_id}-auto-apply-started.json",
            (json.dumps({**event_base, "event": "COMPETITION_AUTO_APPLY_STARTED", "started_at": utc_now()}, sort_keys=True, indent=2) + "\n").encode(),
        )
        job.update({"status": "running", "stage": "activating_generation"})
        self._save(job)
        actor = "football-data-hub-local-update-service"
        publication = self._activate_competition(job, actor, log_path)
        team_follow_publication: dict[str, Any] | None = None
        team_follow_error: str | None = None
        try:
            team_follow_publication = self._publish_team_follow_profiles(job, candidate, log_path)
        except Exception as exc:
            team_follow_error = f"{type(exc).__name__}: {str(exc)[:240]}"
            team_follow_publication = {"status": "error", "reason": team_follow_error}
        _create_once(
            event_root / f"{event_id}-auto-applied.json",
            (json.dumps({
                **event_base,
                "event": "COMPETITION_AUTO_APPLIED",
                "actor": actor,
                "applied_at": utc_now(),
                "publication": publication,
            }, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(),
        )
        summary = self._competition_result_summary(candidate)
        if team_follow_publication:
            summary["team_follow_publication"] = team_follow_publication
        job.update({
            "status": "applied",
            "stage": "refreshing_api",
            "finished_at": utc_now(),
            "summary": summary,
            "publication": publication,
            "auto_apply_event_id": event_id,
            **({"team_follow_publication": team_follow_publication} if team_follow_publication else {}),
        })
        self._save(job)
        if self.on_competition_applied is not None:
            try:
                self.on_competition_applied(job)
            except Exception as exc:
                job.update({
                    "status": "applied_reload_failed",
                    "stage": "refresh_failed",
                    "error": f"La generación quedó aplicada, pero FastAPI no pudo recargarla: {type(exc).__name__}: {exc}",
                    "summary": {**summary, "outcome": "partial"},
                    "finished_at": utc_now(),
                })
                self._save(job)
                return
        job.update({"status": "running", "stage": "checking_match_details"})
        self._save(job)
        detail_summary = self._safe_process_new_match_details(job)
        detail_summary["team_follow_update_published"] = bool(
            team_follow_publication and team_follow_publication.get("status") == "published"
        )
        if team_follow_error:
            detail_summary["team_follow_update_error"] = team_follow_error
        summary.update(detail_summary)
        outcome = self._update_outcome(candidate, detail_summary, core_applied=True)
        summary["outcome"] = outcome
        if outcome == "partial" and not str(summary.get("message", "")).startswith("Actualización parcial"):
            summary["message"] = f"Actualización parcial: {summary.get('message') or 'algunas fuentes quedaron pendientes.'}"
        elif outcome == "failed":
            summary["message"] = self._failure_message(candidate, detail_summary)
        job["summary"] = summary
        job["status"] = "applied" if outcome != "failed" else "failed"
        if outcome == "failed":
            job["error"] = summary["message"]
        self._save(job)
        job.update({"stage": "completed", "finished_at": utc_now()})
        self._save(job)

    @staticmethod
    def _verify_candidate_fingerprint(job: dict[str, Any], candidate: dict[str, Any]) -> None:
        stored_hash = job.get("candidate_sha256")
        candidate_hash = candidate.get("candidate_sha256")
        candidate_body = {key: value for key, value in candidate.items() if key != "candidate_sha256"}
        if (
            not isinstance(stored_hash, str)
            or candidate_hash != stored_hash
            or not hmac.compare_digest(stored_hash, _candidate_sha256(candidate_body))
        ):
            raise ManualUpdateError("La huella interna del candidato no coincide.")

    @staticmethod
    def _related_sections_message(candidate: dict[str, Any], details: dict[str, Any]) -> str:
        status = candidate.get("related_section_status", {})
        statuses = [
            item.get("status")
            for groups in (status.get("groups", {}) if isinstance(status, dict) else {}).values()
            for item in groups.values()
            if isinstance(item, dict)
        ]
        if isinstance(status, dict) and isinstance(status.get("referees"), dict):
            statuses.append(status["referees"].get("status"))
        team_follow = status.get("team_follow") if isinstance(status, dict) else None
        if isinstance(team_follow, dict):
            statuses.append(team_follow.get("status"))
        if "error" in statuses or "partial" in statuses:
            return "Actualización parcial: una fuente relacionada dio error; se conservaron sus datos anteriores."
        changed_groups = candidate.get("changed_groups", {})
        if isinstance(changed_groups, dict) and any(changed_groups.values()):
            return "Actualización aplicada"
        if candidate.get("related_sections_changed"):
            return "Secciones relacionadas actualizadas."
        if details.get("match_details_published_count"):
            return "Informes de partidos añadidos."
        return "Sin cambios"

    @staticmethod
    def _update_outcome(
        candidate: dict[str, Any], details: dict[str, Any], *, core_applied: bool
    ) -> str:
        """Separate complete, partial and failed outcomes from job lifecycle."""
        related = candidate.get("related_section_status", {})
        section_states: list[str] = []
        if isinstance(related, dict):
            groups = related.get("groups", {})
            if isinstance(groups, dict):
                for group_sections in groups.values():
                    if isinstance(group_sections, dict):
                        section_states.extend(
                            item["status"]
                            for item in group_sections.values()
                            if isinstance(item, dict) and isinstance(item.get("status"), str)
                        )
            referees = related.get("referees")
            if isinstance(referees, dict) and isinstance(referees.get("status"), str):
                section_states.append(referees["status"])
            team_follow = related.get("team_follow")
            if isinstance(team_follow, dict):
                team_status = team_follow.get("status")
                if isinstance(team_status, str):
                    section_states.append(team_status)

        has_error = any(state in {"error", "not_attempted"} for state in section_states)
        team_follow = related.get("team_follow") if isinstance(related, dict) else None
        if isinstance(team_follow, dict):
            has_error = has_error or int(team_follow.get("error_team_count", 0) or 0) > 0
        has_error = has_error or any(
            isinstance(details.get(key), str) and bool(details.get(key))
            for key in (
                "match_details_error",
                "match_details_reload_error",
                "match_details_recovery_error",
            )
        )
        has_error = has_error or details.get("match_details_stopped") is True
        has_error = has_error or int(details.get("match_details_error_count", 0) or 0) > 0
        has_error = has_error or int(details.get("match_details_validation_failed_count", 0) or 0) > 0
        has_pending = int(details.get("match_details_pending_count", 0) or 0) > 0
        has_pending = has_pending or bool(
            isinstance(related, dict)
            and isinstance(related.get("team_follow"), dict)
            and int(related["team_follow"].get("pending_team_count", 0) or 0) > 0
        )
        has_error = has_error or bool(details.get("team_follow_update_error"))

        changed_groups = candidate.get("changed_groups", {})
        core_changed = isinstance(changed_groups, dict) and any(
            bool(value) for value in changed_groups.values()
        )
        related_changed = _has_related_section_changes(candidate.get("related_sections")) or any(
            state == "changed" for state in section_states
        ) or details.get("team_follow_update_published") is True
        any_applied = (
            core_applied
            or core_changed
            or related_changed
            or int(details.get("match_details_published_count", 0) or 0) > 0
        )
        if has_pending:
            return "partial"
        if has_error:
            return "partial" if any_applied else "failed"
        return "full"

    @staticmethod
    def _failure_message(candidate: dict[str, Any], details: dict[str, Any]) -> str:
        related = candidate.get("related_section_status", {})
        reasons: list[str] = []
        if isinstance(related, dict):
            groups = related.get("groups", {})
            if isinstance(groups, dict):
                for group, sections in groups.items():
                    if not isinstance(sections, dict):
                        continue
                    for name, item in sections.items():
                        if isinstance(item, dict) and item.get("status") == "error":
                            reasons.append(f"{name} Grupo {group}: {item.get('reason') or 'falló'}")
            referees = related.get("referees")
            if isinstance(referees, dict) and referees.get("status") == "error":
                reasons.append(f"Árbitros: {referees.get('reason') or 'falló'}")
            team_follow = related.get("team_follow")
            if isinstance(team_follow, dict) and team_follow.get("status") in {"error", "partial"}:
                team_errors = [
                    f"equipo {team_id}: {item.get('reason') or item.get('status')}"
                    for team_id, item in (team_follow.get("teams") or {}).items()
                    if isinstance(item, dict) and item.get("status") in {"error", "not_attempted", "pending"}
                ]
                if team_follow.get("reason"):
                    reasons.append(f"Seguimiento: {team_follow['reason']}")
                elif team_errors:
                    reasons.append("Seguimiento: " + "; ".join(team_errors[:3]))
                else:
                    reasons.append("Seguimiento: hay equipos con cobertura pendiente")
        detail_error = details.get("match_details_error")
        if isinstance(detail_error, str) and detail_error:
            reasons.append(f"informes: {detail_error}")
        return "Actualización fallida: " + (
            "; ".join(reasons) if reasons else "ninguna sección pudo actualizarse."
        )

    def _safe_process_new_match_details(self, job: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._process_new_match_details(job)
        except Exception as exc:
            candidate = job.get("candidate") if isinstance(job.get("candidate"), dict) else {}
            candidate_summary = candidate.get("summary") if isinstance(candidate.get("summary"), dict) else {}
            pending = int(candidate_summary.get("played_without_approved_details", 0) or 0)
            return {
                "match_details_candidate_count": pending,
                "match_details_captured_count": 0,
                "match_details_navigation_count": 0,
                "match_details_published_count": 0,
                "match_details_pending_count": pending,
                "match_details_policy_review_count": 0,
                "match_details_stopped": True,
                "match_details_error": f"{type(exc).__name__}: {str(exc)[:300]}",
                "match_details_message": "No se pudo completar el procesamiento de informes; se conservan los datos anteriores y los informes siguen pendientes.",
            }

    def _process_new_match_details(self, job: dict[str, Any]) -> dict[str, Any]:
        """Acquire only unpublished played fixtures and apply the strict policy."""

        paths = (
            self.match_generation_root,
            self.match_details_store_root,
            self.match_details_published_root,
            self.player_inventory_root,
            self.player_compact_root,
            self.player_team_captures_root,
            self.player_published_index_path,
        )
        if self.data_root is None or any(path is None for path in paths):
            return {
                "match_details_candidate_count": 0,
                "match_details_captured_count": 0,
                "match_details_navigation_count": 0,
                "match_details_published_count": 0,
                "match_details_pending_count": 0,
                "match_details_policy_review_count": 0,
                "match_details_stopped": False,
                "match_details_message": "No se ejecutó la adquisición de informes: faltan almacenes configurados.",
            }

        from types import SimpleNamespace

        from football_data_hub.providers.bdfutbol.match_details.campaign_operations import run_offline_batch
        from .match_details_dataset import publish_legacy_recovery_match_detail_by_policy
        from football_data_hub.providers.bdfutbol.match_details.operational_campaign import (
            OperationalMatchCampaignLedger,
        )
        from football_data_hub.providers.bdfutbol.match_details.scalable_campaign_cli import _load_report
        from football_data_hub.providers.bdfutbol.match_details.scalable_campaigns import (
            build_match_campaign_proposal,
            write_match_campaign_proposal,
        )
        from football_data_hub.providers.bdfutbol.match_details.supervised_acquisition import (
            run_competition_update_detail_acquisition,
        )

        args = SimpleNamespace(
            data_root=self.data_root,
            generation_root=self.match_generation_root,
            previous_generation_root=None,
            store_root=self.match_details_store_root,
            published_root=self.match_details_published_root,
            player_inventory_root=self.player_inventory_root,
            player_compact_root=self.player_compact_root,
            player_team_captures_root=self.player_team_captures_root,
            player_published_index=self.player_published_index_path,
        )
        job["stage"] = "scanning_unpublished_matches"
        self._save(job)
        status_report, existing_proposals, context = _load_report(args)
        if context.get("pending_played_ids") == []:
            # _load_report verifies every package in the published index against
            # the active fixture and source. If there are no played IDs left,
            # skip all campaign traversal and report acquisition/processing.
            verified_count = len(context.get("published_ids", set()))
            return {
                "match_details_candidate_count": 0,
                "match_details_captured_count": 0,
                "match_details_navigation_count": 0,
                "match_details_published_count": 0,
                "match_details_pending_count": 0,
                "match_details_policy_review_count": 0,
                "match_details_validation_failed_count": 0,
                "match_details_error_count": 0,
                "match_details_stopped": False,
                "match_details_verified_published_count": verified_count,
                "match_details_message": (
                    f"No se procesaron informes: los {verified_count} informes publicados "
                    "cubren todos los partidos disputados y superaron la verificación."
                ),
            }
        ledger = OperationalMatchCampaignLedger(self.match_details_store_root / "campaigns")
        offline_reports: list[dict[str, Any]] = []
        saved_capture_count = 0
        saved_policy_pending = 0
        saved_validation_failed = 0
        saved_error_count = 0
        saved_terminal_policy_pending = 0
        processed_campaign_ids: list[str] = []

        # The global button first consumes already-authorized, hash-checked
        # campaign artifacts offline. It never turns a previous STARTED event
        # into another navigation.
        for proposal in existing_proposals:
            campaign_id = proposal.get("campaign_id")
            if not isinstance(campaign_id, str) or not re.fullmatch(
                r"match-detail-campaign-v2-[0-9a-f]{16}", campaign_id
            ):
                continue
            campaign_dir = ledger.root / campaign_id
            if campaign_dir.is_symlink():
                saved_error_count += 1
                continue
            if not campaign_dir.is_dir():
                # Old proposals without an initialized v2 ledger have no
                # consumed authorization or captured artifact to process.
                continue
            try:
                preflight = ledger.preflight(campaign_id)
            except Exception:
                # _load_report has already performed a global integrity pass;
                # keep a campaign-local diagnostic and continue independent IDs.
                saved_error_count += 1
                continue
            if (
                preflight.get("source_generation_id") != context.get("active_generation_id")
                or preflight.get("source_generation_manifest_sha256")
                != context.get("active_generation_manifest_sha256")
            ):
                continue
            auto_pending_ids = {
                item["internal_id"]
                for item in preflight.get("candidates", [])
                if item.get("authorization_mode") == "competition_update_auto_policy"
                and item.get("state") in {
                    "DISCOVERY_REVIEW_REQUIRED", "VALIDATION_FAILED", "REVALIDATION_FAILED",
                    "VALIDATED", "REVALIDATED", "AUTO_POLICY_REVALIDATED", "DRAFT_PREPARED",
                    "AUTO_POLICY_APPROVED",
                }
                and isinstance(item.get("artifact"), dict)
            }
            if not auto_pending_ids:
                saved_terminal_policy_pending += sum(
                    1
                    for item in preflight.get("candidates", [])
                    if item.get("authorization_mode") == "competition_update_auto_policy"
                    and item.get("state") == "AUTO_POLICY_REVALIDATION_FAILED"
                    and isinstance(item.get("artifact"), dict)
                )
                continue
            saved_terminal_policy_pending += sum(
                1
                for item in preflight.get("candidates", [])
                if item.get("authorization_mode") == "competition_update_auto_policy"
                and item.get("state") == "AUTO_POLICY_REVALIDATION_FAILED"
                and isinstance(item.get("artifact"), dict)
            )
            job["stage"] = "validating_saved_match_details"
            job["match_details_progress"] = {
                "phase": "offline_validation",
                "completed": 0,
                "total": len(auto_pending_ids),
                "campaign_id": campaign_id,
            }
            self._save(job)
            offline_report = run_offline_batch(
                ledger=ledger,
                campaign_id=campaign_id,
                data_root=self.data_root,
                player_inventory_root=self.player_inventory_root,
                player_compact_root=self.player_compact_root,
                player_team_captures_root=self.player_team_captures_root,
                player_published_index_path=self.player_published_index_path,
                auto_publish_policy=True,
                published_root=self.match_details_published_root,
                internal_ids=auto_pending_ids,
            )
            offline_reports.append(offline_report)
            saved_capture_count += len(auto_pending_ids)
            saved_policy_pending += int(offline_report.get("policy_pending_count", 0))
            saved_validation_failed += int(offline_report.get("validation_failed_count", 0))
            saved_error_count += int(offline_report.get("error_count", 0))
            processed_campaign_ids.append(campaign_id)

        legacy_recovery_result: dict[str, Any] | None = None
        legacy_recovery_error: str | None = None
        legacy_recovery_id = "legacy-recovery-272582-812c3e44fbbc6941"
        legacy_internal_id = "pf-2026-27-group-ii-bdfutbol-272582"
        recovery_report = status_report.get("historical_recovery")
        recovery_candidate_pending = bool(
            legacy_internal_id not in context["published_ids"]
            and isinstance(recovery_report, dict)
            and recovery_report.get("recovery_id") == legacy_recovery_id
        )
        if (
            legacy_internal_id not in context["published_ids"]
            and context.get("match_bundle") is not None
            and context.get("active_generation_id")
        ):
            if isinstance(recovery_report, dict) and recovery_report.get("recovery_id") == legacy_recovery_id:
                try:
                    job["stage"] = "validating_legacy_recovery"
                    self._save(job)
                    legacy_recovery_result = publish_legacy_recovery_match_detail_by_policy(
                        recovery_id=legacy_recovery_id,
                        update_job_id=str(job["job_id"]),
                        published_root=self.match_details_published_root,
                        store_root=self.match_details_store_root,
                        generation_root=self.match_generation_root,
                        data_root=self.data_root,
                        match_bundle=context["match_bundle"],
                        player_ids=set(context["player_ids"]),
                    )
                except Exception as exc:
                    legacy_recovery_error = f"{type(exc).__name__}: {str(exc)[:300]}"

        offline_published_count = sum(int(report.get("published_count", 0)) for report in offline_reports)
        recovery_published_count = int(
            legacy_recovery_result is not None
            and legacy_recovery_result.get("status") in {"PUBLISHED_VERIFIED", "ALREADY_PUBLISHED_VERIFIED"}
            and legacy_internal_id not in context["published_ids"]
        )
        saved_published_count = offline_published_count + recovery_published_count
        for offline_report in offline_reports:
            context["published_ids"].update(
                item.get("internal_id")
                for item in offline_report.get("candidates", [])
                if item.get("status") == "PUBLISHED_VERIFIED"
            )
        if recovery_published_count:
            context["published_ids"].add(legacy_internal_id)

        rows = status_report.get("matches", [])
        eligible = [
            row for row in rows
            if row.get("status") == "played"
            and row.get("source_match_url")
            and row.get("detail_status") in {"played_pending_acquisition", "included_in_existing_campaign"}
            and row.get("internal_id") not in context["published_ids"]
            and row.get("internal_id") not in context["captured_ids"]
            and row.get("internal_id") not in context["blocked_ids"]
            and not row.get("blocked_reasons")
        ]
        blocked_excluded = sum(
            1 for row in rows
            if row.get("status") == "played"
            and row.get("detail_status") == "blocked_requires_human_review"
            and row.get("internal_id") not in context["published_ids"]
            and row.get("internal_id") not in context["captured_ids"]
        )

        selected_ids = [row["internal_id"] for row in eligible]
        selected_id_set = set(selected_ids)
        if not selected_ids:
            saved_published_ids = {
                item.get("internal_id")
                for report in offline_reports
                for item in report.get("candidates", [])
                if item.get("status") == "PUBLISHED_VERIFIED"
            }
            published_ids_from_saved = set(saved_published_ids)
            if recovery_published_count:
                published_ids_from_saved.add(legacy_internal_id)
            job["_match_details_published_internal_ids"] = sorted(
                item for item in published_ids_from_saved if isinstance(item, str)
            )
            saved_pending_count = max(0, saved_capture_count - len(saved_published_ids))
            reload_error = None
            if saved_published_count and self.on_match_details_published is not None:
                job["stage"] = "refreshing_match_details"
                self._save(job)
                try:
                    self.on_match_details_published(job)
                except Exception as exc:
                    reload_error = f"{type(exc).__name__}: {str(exc)[:300]}"
            pending_count = (
                saved_pending_count
                + saved_terminal_policy_pending
                + int(recovery_candidate_pending and not recovery_published_count)
            )
            return {
                "match_details_candidate_count": saved_capture_count + saved_terminal_policy_pending + int(recovery_candidate_pending),
                "match_details_captured_count": saved_capture_count + saved_terminal_policy_pending,
                "match_details_navigation_count": 0,
                "match_details_published_count": saved_published_count,
                "match_details_pending_count": pending_count,
                "match_details_policy_review_count": saved_policy_pending + saved_terminal_policy_pending,
                "match_details_validation_failed_count": saved_validation_failed,
                "match_details_error_count": saved_error_count,
                "match_details_campaigns_processed": processed_campaign_ids,
                "match_details_recovery_status": (
                    legacy_recovery_result.get("status") if legacy_recovery_result else None
                ),
                "match_details_recovery_error": legacy_recovery_error,
                "match_details_recovery_published_count": recovery_published_count,
                "match_details_recovery_pending_count": int(
                    recovery_candidate_pending and not recovery_published_count
                ),
                "match_details_stopped": False,
                "match_details_blocked_excluded_count": blocked_excluded,
                "match_details_reload_error": reload_error,
                "match_details_message": (
                    f"Informes publicados con política estricta: {saved_published_count}. "
                    f"Pendientes: {pending_count}."
                    if saved_published_count
                    else "Los informes dudosos o no disponibles permanecen pendientes."
                ),
            }
        source_generation_id = context["generation_root"].name
        matching_proposals = [
            proposal
            for proposal in existing_proposals
            if proposal.get("source", {}).get("generation_id") == source_generation_id
            and {
                item.get("internal_id")
                for item in proposal.get("candidates", [])
                if isinstance(item, dict)
            } == selected_id_set
        ]
        if len(matching_proposals) > 1:
            raise ManualUpdateError(
                "Hay varias propuestas íntegras para el mismo conjunto de partidos; "
                "se requiere resolver el duplicado antes de continuar."
            )
        if matching_proposals:
            plan = matching_proposals[0]
            authorization = plan.get("authorization")
            if (
                not isinstance(authorization, dict)
                or authorization.get("is_authorization") is not False
                or authorization.get("status") not in {"NOT_AUTHORIZED", "PROPOSED_NOT_AUTHORIZED"}
            ):
                raise ManualUpdateError(
                    "La propuesta coincidente no está en estado íntegro y no autorizado."
                )
            proposal_dir = (
                self.match_details_store_root
                / "campaign-proposals"
                / "plans"
                / str(plan["proposal_id"])
            )
        else:
            overlapping_proposals = [
                proposal
                for proposal in existing_proposals
                if selected_id_set.intersection(
                    item.get("internal_id")
                    for item in proposal.get("candidates", [])
                    if isinstance(item, dict)
                )
            ]
            if overlapping_proposals:
                raise ManualUpdateError(
                    "Existe una propuesta anterior que solo cubre parte de los partidos "
                    "pendientes; no se creará una campaña duplicada ni se alterará su plan."
                )
            plan = build_match_campaign_proposal(status_report, internal_ids=selected_ids)
            proposal_dir = write_match_campaign_proposal(
                self.match_details_store_root / "campaign-proposals", plan
            )
        ledger.initialize(
            proposal_dir=proposal_dir,
            # _load_report resolves an active-generation.json store pointer
            # and returns the exact verified immutable generation. The ledger
            # initializer accepts only that concrete generation directory.
            generation_root=context["generation_root"],
            data_root=self.data_root,
            published_ids=context["published_ids"],
            captured_ids=context["captured_ids"],
            blocked_ids=context["blocked_ids"],
        )
        campaign_id = str(plan["campaign_id"])
        source_inventory = ledger.source_inventory(campaign_id)
        completed_count = 0

        def progress(event: dict[str, Any]) -> None:
            nonlocal completed_count
            if event.get("event") == "candidate_finished":
                completed_count = int(event.get("index", completed_count))
            job["match_details_progress"] = {"completed": completed_count, "total": len(selected_ids)}
            job["stage"] = "acquiring_match_details"
            self._save(job)

        def execute_candidate(candidate: dict[str, Any], authorization_id: str, current: dict[str, Any]) -> dict[str, Any]:
            internal_id = candidate["internal_id"]
            return ledger.execute_for_competition_update(
                campaign_id=campaign_id,
                internal_id=internal_id,
                authorization_id=authorization_id,
                confirmed_url=candidate["source_match_url"],
                update_job_id=str(job["job_id"]),
                data_root=self.data_root,
                profile_dir=self.data_root / "browser-profiles" / f"match-detail-v2-{candidate['source_match_id']}",
                store_root=self.match_details_store_root,
                store_inventory=source_inventory,
                current_status=current,
                published=internal_id in context["published_ids"],
                captured=internal_id in context["captured_ids"],
                blocked=internal_id in context["blocked_ids"],
            )

        acquisition = run_competition_update_detail_acquisition(
            ledger=ledger,
            campaign_id=campaign_id,
            update_job_id=str(job["job_id"]),
            data_root=self.data_root,
            player_capture_root=self.player_team_captures_root,
            status_report=status_report,
            context=context,
            execute_candidate=execute_candidate,
            progress_callback=progress,
        )
        offline: dict[str, Any] = {"published_count": 0, "policy_pending_count": 0}
        if acquisition.get("captured_count"):
            job["stage"] = "validating_match_details"
            self._save(job)
            offline = run_offline_batch(
                ledger=ledger,
                campaign_id=campaign_id,
                data_root=self.data_root,
                player_inventory_root=self.player_inventory_root,
                player_compact_root=self.player_compact_root,
                player_team_captures_root=self.player_team_captures_root,
                player_published_index_path=self.player_published_index_path,
                auto_publish_policy=True,
                published_root=self.match_details_published_root,
                internal_ids=selected_id_set,
            )
        published_count = saved_published_count + int(offline.get("published_count", 0))
        newly_published_ids = {
            item.get("internal_id")
            for report in offline_reports
            for item in report.get("candidates", [])
            if item.get("status") == "PUBLISHED_VERIFIED"
        }
        newly_published_ids.update(
            item.get("internal_id")
            for item in offline.get("candidates", [])
            if item.get("status") == "PUBLISHED_VERIFIED"
        )
        if recovery_published_count:
            newly_published_ids.add(legacy_internal_id)
        job["_match_details_published_internal_ids"] = sorted(
            item for item in newly_published_ids if isinstance(item, str)
        )
        reload_error = None
        if published_count and self.on_match_details_published is not None:
            job["stage"] = "refreshing_match_details"
            self._save(job)
            try:
                self.on_match_details_published(job)
            except Exception as exc:
                reload_error = f"{type(exc).__name__}: {str(exc)[:300]}"
        return {
            "match_details_candidate_count": saved_capture_count + saved_terminal_policy_pending + len(selected_ids) + int(recovery_candidate_pending),
            "match_details_captured_count": saved_capture_count + saved_terminal_policy_pending + int(acquisition.get("captured_count", 0)),
            "match_details_navigation_count": int(acquisition.get("navigation_requests", 0)),
            "match_details_published_count": published_count,
            "match_details_pending_count": max(
                0,
                saved_capture_count + saved_terminal_policy_pending + len(selected_ids) + int(recovery_candidate_pending) - published_count,
            ),
            "match_details_policy_review_count": saved_policy_pending + saved_terminal_policy_pending + int(offline.get("policy_pending_count", 0)),
            "match_details_validation_failed_count": saved_validation_failed + int(offline.get("validation_failed_count", 0)),
            "match_details_error_count": saved_error_count + int(offline.get("error_count", 0)),
            "match_details_campaigns_processed": processed_campaign_ids,
            "match_details_recovery_status": (
                legacy_recovery_result.get("status") if legacy_recovery_result else None
            ),
            "match_details_recovery_error": legacy_recovery_error,
            "match_details_recovery_published_count": recovery_published_count,
            "match_details_recovery_pending_count": int(
                legacy_internal_id not in context["published_ids"] and recovery_published_count == 0
            ),
            "match_details_stopped": acquisition.get("stop_acquisition") is True,
            "match_details_blocked_excluded_count": blocked_excluded,
            "match_details_reload_error": reload_error,
            "match_details_message": (
                f"Informes publicados con política estricta: {published_count}. "
                f"Pendientes: {max(0, saved_capture_count + saved_terminal_policy_pending + len(selected_ids) + int(recovery_candidate_pending) - published_count)}."
                if published_count else "Los informes dudosos o no disponibles permanecen pendientes."
            ),
        }

    @staticmethod
    def _assert_automatic_competition_candidate(candidate: dict[str, Any]) -> None:
        summary = candidate.get("summary")
        if not isinstance(summary, dict):
            raise ManualUpdateError("La comparación no contiene un resumen validable.")
        if summary.get("hard_conflicts") != 0:
            raise ManualUpdateError("La comparación encontró conflictos de identidad o de calendario; no se aplicó.")
        if summary.get("played_to_unplayed_conflicts") != 0:
            raise ManualUpdateError("La comparación contiene partidos disputados que vuelven a pendientes; no se aplicó.")
        changed_groups = candidate.get("changed_groups")
        if not isinstance(changed_groups, dict) or set(changed_groups) != {"I", "II"}:
            raise ManualUpdateError("La comparación no cubre ambos grupos.")
        if not any(changed_groups.values()):
            raise ManualUpdateError("El candidato afirma tener cambios, pero no identifica ningún grupo modificado.")

    @staticmethod
    def _competition_result_summary(candidate: dict[str, Any]) -> dict[str, Any]:
        source = candidate.get("summary") or {}
        return {
            "message": ManualUpdateManager._related_sections_message(candidate, {}),
            "changed_groups": candidate.get("changed_groups", {}),
            "related_section_status": candidate.get("related_section_status", {}),
            "related_sections_changed": candidate.get("related_sections_changed", False),
            "newly_played": source.get("newly_played", 0),
            "result_corrected": source.get("result_corrected", 0),
            "fixture_updated": source.get("fixture_updated", 0),
            "played_without_approved_details": source.get("played_without_approved_details", 0),
        }

    def _preflight(self) -> None:
        if self.data_root is None or not self.data_root.is_dir():
            raise ManualUpdateError("FDH_LOCAL_DATA_ROOT debe existir y ser accesible antes de adquirir.")
        if (self.root / "activation-pending.json").exists():  # type: ignore[operator]
            raise ManualUpdateError("Hay una activación interrumpida; resuélvela antes de iniciar otra actualización.")
        if not shutil.which("xvfb-run") or not shutil.which("Xvfb"):
            raise ManualUpdateError("No se encontró Xvfb aislado; se detuvo antes de navegar.")
        if self.profile_dir.is_symlink() or not self.profile_dir.is_dir():
            raise ManualUpdateError("El perfil Pure CDP persistente autorizado debe existir y no ser un symlink.")
        if self.browser_executable is not None and not self.browser_executable.is_file():
            raise ManualUpdateError("FDH_BDFUTBOL_BROWSER_EXECUTABLE no existe.")
        if not self.group_match_paths or any(not path.is_file() for path in self.group_match_paths.values()):
            raise ManualUpdateError("Faltan catálogos locales verificados para el ámbito solicitado.")

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        python_paths = [str(self.project_root / "src"), str(self.project_root / "apps" / "api")]
        if env.get("PYTHONPATH"):
            python_paths.append(env["PYTHONPATH"])
        env["PYTHONPATH"] = os.pathsep.join(python_paths)
        env["FDH_BDFUTBOL_PROFILE"] = str(self.profile_dir)
        env.pop("DISPLAY", None)
        env.pop("WAYLAND_DISPLAY", None)
        env.pop("WAYLAND_SOCKET", None)
        return env

    def _command(self, args: list[str], log_path: Path, *, timeout: int) -> str:
        with log_path.open("ab") as log:
            log.write(("\n$ " + " ".join(args) + "\n").encode())
            log.flush()
            process = subprocess.Popen(
                args,
                cwd=self.project_root,
                env=self._env(),
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            with self._mutex:
                self._active_processes.add(process)
            try:
                return_code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=10)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=5)
                raise ManualUpdateError("La adquisición superó el límite de tiempo y se detuvo; no se reintentó.") from exc
            finally:
                with self._mutex:
                    self._active_processes.discard(process)
        if return_code != 0:
            raise ManualUpdateError(
                _friendly_process_failure(
                    _tail(log_path, 20000),
                    f"El proceso terminó con código {return_code}; no se reintentó.",
                )
            )
        return _tail(log_path, 20000)

    def _update_competition(self, job: dict[str, Any], log_path: Path) -> dict[str, Any]:
        assert self.data_root and self.match_generation_root
        base = self._jobs_dir() / str(job["job_id"])
        captures = base / "captures" / "classification"
        captures.mkdir(parents=True, exist_ok=False, mode=0o700)
        roots: dict[str, Path] = {}
        normalized: dict[str, Path] = {}
        changed_groups: dict[str, list[str]] = {}
        standings_changes: dict[str, list[dict[str, Any]]] = {}
        progress_changes: dict[str, list[dict[str, Any]]] = {}
        for group, group_number in (("I", "1"), ("II", "2")):
            if group == "II":
                time.sleep(5)
            group_root = captures / f"group-{group.lower()}"
            group_root.mkdir()
            job["stage"] = f"capturing_group_{group.lower()}"
            self._save(job)
            args = [sys.executable, "scripts/scrape_bdfutbol_classification.py", "--group", group_number,
                    "--output-root", str(group_root), "--profile", str(self.profile_dir)]
            if self.browser_executable:
                args.extend(["--browser-executable", str(self.browser_executable)])
            self._command(args, log_path, timeout=900)
            run_dirs = [path for path in group_root.iterdir() if path.is_dir() and not path.name.startswith(".")]
            if len(run_dirs) != 1:
                raise ManualUpdateError(f"No hay exactamente una captura nueva validable para Grupo {group}.")
            roots[group] = run_dirs[0]
            job["stage"] = f"normalizing_matches_group_{group.lower()}"
            self._save(job)
            normalized[group] = base / "normalized" / f"group-{group.lower()}" / "matches.json"
            normalized[group].parent.mkdir(parents=True, exist_ok=False, mode=0o700)
            validation_path = base / "normalized" / "validation" / f"group-{group.lower()}-matches.json"
            validation_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._command([
                sys.executable, "scripts/extract_bdfutbol_matches.py",
                "--snapshot", str(roots[group] / "raw/source.html"),
                "--capture", str(roots[group] / "metadata/capture.json"),
                "--output", str(normalized[group]),
                "--validation-output", str(validation_path),
            ], log_path, timeout=300)
            validation = json.loads(validation_path.read_text(encoding="utf-8"))
            if validation.get("valid") is not True:
                raise ManualUpdateError(f"La captura del Grupo {group} no superó la validación existente.")

            standings_changes[group] = _classification_changes(
                roots[group] / "normalized/classification.json",
                self.group_classification_paths[group],
            )
            progress_changes[group] = _progress_changes(
                roots[group] / "normalized/progress.json",
                self.group_progress_paths[group],
            )
            classification_changed = bool(standings_changes[group])
            progress_changed = bool(progress_changes[group])
            matches_changed = _sports_section_changed(
                normalized[group], self.group_match_paths[group], kind="matches"
            )
            changed_groups[group] = [
                name for name, changed in (
                    ("classification", classification_changed),
                    ("progress", progress_changed),
                    ("results_calendar", matches_changed),
                ) if changed
            ]

        related_sections, related_section_status = self._capture_related_sections(
            job, log_path, roots=roots, normalized=normalized
        )
        related_acquisition_stopped = related_section_status.get("acquisition_stopped") is True
        team_follow_status = self._update_team_follow(
            job,
            log_path,
            normalized=normalized,
            stop_before_acquisition=(
                str(related_section_status.get("stop_reason") or "Otra sección recibió una denegación o un error de validación; se detuvieron las adquisiciones posteriores.")
                if related_acquisition_stopped else None
            ),
        )
        team_profile_candidates = team_follow_status.pop("candidate_profiles", [])
        team_profiles_index_sha256 = team_follow_status.pop("source_index_sha256", None)
        related_section_status["team_follow"] = team_follow_status
        core_no_changes = not any(changed_groups.values())
        has_related_changes = any(
            item.get("status") == "changed"
            for group_sections in related_section_status.get("groups", {}).values()
            for item in group_sections.values()
        ) or related_section_status.get("referees", {}).get("status") == "changed" or bool(team_profile_candidates)
        if not any(changed_groups.values()):
            return {
                "kind": "competition_generation",
                "no_changes": True,
                "no_competition_changes": True,
                "related_sections_changed": has_related_changes,
                "related_sections": related_sections,
                "related_section_status": related_section_status,
                "changed_groups": changed_groups,
                "standings_changes": standings_changes,
                "progress_changes": progress_changes,
                "source_captures": {group: str(path) for group, path in roots.items()},
                "normalized_matches": {group: str(path) for group, path in normalized.items()},
                "source_capture_sha256": {group: _tree_sha256(path) for group, path in roots.items()},
                "normalized_match_sha256": {group: _sha256(path.read_bytes()) for group, path in normalized.items()},
                "team_profiles_index_sha256": team_profiles_index_sha256,
                "team_profile_candidates": team_profile_candidates,
                "activated": False,
                "published_match_details": False,
            }

        job["stage"] = "building_generation"
        self._save(job)
        build_output = self._command([
            sys.executable, "scripts/build_bdfutbol_match_generation.py",
            "--group-i-root", str(roots["I"]), "--group-i-matches", str(normalized["I"]),
            "--group-ii-root", str(roots["II"]), "--group-ii-matches", str(normalized["II"]),
            "--data-root", str(self.data_root), "--output-root", str(self.data_root / "matches"),
        ], log_path, timeout=600)
        candidate_path = Path(build_output.strip().splitlines()[-1]).resolve()
        if not candidate_path.is_dir():
            raise ManualUpdateError("El constructor no devolvió una generación candidata verificable.")
        if self.match_details_store_root is None:
            raise ManualUpdateError("No se configuró el almacén de detalles para proteger las publicaciones existentes.")
        compare_args = [
            sys.executable, "scripts/manage_bdfutbol_match_generations.py", "compare",
            "--data-root", str(self.data_root), "--store-root", str(self.match_details_store_root.parent),
            "--before", str(self.match_generation_root), "--after", str(candidate_path),
            "--output", str(base / "diff.json"),
        ]
        for flag, path in (
            ("--player-inventory-root", self.player_inventory_root),
            ("--player-compact-root", self.player_compact_root),
            ("--team-captures-root", self.player_team_captures_root),
            ("--team-profiles-index", self.player_published_index_path),
        ):
            if path:
                compare_args.extend([flag, str(path)])
        job["stage"] = "comparing_candidate"
        self._save(job)
        self._command(compare_args, log_path, timeout=900)
        diff = json.loads((base / "diff.json").read_text(encoding="utf-8"))
        return {
            "kind": "competition_generation",
            "candidate_generation_id": diff.get("after_generation_id"),
            "candidate_directory": str(candidate_path),
            "diff_report": str(base / "diff.json"),
            "diff_artifact_sha256": _sha256((base / "diff.json").read_bytes()),
            "report_sha256": diff.get("report_sha256"),
            "summary": diff.get("summary", {}),
            "changed_groups": changed_groups,
            "no_competition_changes": core_no_changes,
            "related_sections_changed": has_related_changes,
            "related_sections": related_sections,
            "related_section_status": related_section_status,
            "standings_changes": standings_changes,
            "progress_changes": progress_changes,
            "changed_fixtures": [
                item for item in diff.get("fixtures", [])
                if item.get("change_type") != "unchanged"
            ],
            "source_captures": {group: str(path) for group, path in roots.items()},
            "normalized_matches": {group: str(path) for group, path in normalized.items()},
            "source_capture_sha256": {group: _tree_sha256(path) for group, path in roots.items()},
            "normalized_match_sha256": {group: _sha256(path.read_bytes()) for group, path in normalized.items()},
            "team_profiles_index_sha256": team_profiles_index_sha256,
            "team_profile_candidates": team_profile_candidates,
            "candidate_generation_sha256": _tree_sha256(candidate_path),
            "activated": False,
            "published_match_details": False,
        }

    def _capture_related_sections(
        self,
        job: dict[str, Any],
        log_path: Path,
        *,
        roots: dict[str, Path],
        normalized: dict[str, Path],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Capture supported competition sections in order, stopping at access errors.

        Each provider CLI validates and exports its own immutable capture. These
        captures are only added to the active pointer when their normalized
        semantic data differs from the currently active snapshot.
        """
        related: dict[str, Any] = {"groups": {}}
        status: dict[str, Any] = {"groups": {"I": {}, "II": {}}, "referees": {"status": "not_attempted"}}
        base = self._jobs_dir() / str(job["job_id"]) / "captures" / "related"
        base.mkdir(parents=True, exist_ok=False, mode=0o700)
        stop_reason: str | None = None
        # The competition core capture ends immediately before this helper is
        # called. Treat it as the previous browser navigation so the first
        # related acquisition also respects the configured five-second gap.
        last_browser_finished: float | None = time.monotonic()

        def command_before_navigation() -> None:
            nonlocal last_browser_finished
            if last_browser_finished is not None:
                remaining = 5.0 - (time.monotonic() - last_browser_finished)
                if remaining > 0:
                    time.sleep(remaining)

        def capture(
            *, section: str, group: str | None, args: list[str], output: Path, timeout: int
        ) -> Path:
            nonlocal last_browser_finished
            output.mkdir(parents=True, exist_ok=False, mode=0o700)
            command_before_navigation()
            self._command(args, log_path, timeout=timeout)
            last_browser_finished = time.monotonic()
            captures = [path for path in output.iterdir() if path.is_dir() and not path.name.startswith(".")]
            if len(captures) != 1:
                raise ManualUpdateError(f"{section} {group or ''} no produjo exactamente una captura versionada.")
            return captures[0]

        for group, number in (("I", "1"), ("II", "2")):
            for section in ("top", "statistics"):
                if stop_reason:
                    status["groups"][group][section] = {
                        "status": "not_attempted", "reason": stop_reason,
                    }
                    continue
                job["stage"] = f"capturing_{section}_group_{group.lower()}"
                self._save(job)
                output = base / f"group-{group.lower()}-{section}"
                if section == "top":
                    args = [
                        sys.executable, "scripts/scrape_bdfutbol_top.py",
                        "--season", "2026-27", "--group", number,
                        "--team-catalog", str(normalized[group]),
                        "--output-root", str(output), "--profile", str(self.profile_dir),
                    ]
                    timeout = 900
                else:
                    args = [
                        sys.executable, "scripts/scrape_bdfutbol_statistics.py",
                        "--season", "2026-27", "--group", number,
                        "--matches", str(normalized[group]),
                        "--match-source-snapshot", str(roots[group] / "raw/source.html"),
                        "--output-root", str(output), "--profile", str(self.profile_dir),
                    ]
                    timeout = 900
                if self.browser_executable:
                    args.extend(["--browser-executable", str(self.browser_executable)])
                try:
                    capture_root = capture(
                        section=section, group=group, args=args, output=output, timeout=timeout
                    )
                    capture_metadata = json.loads((capture_root / "metadata/capture.json").read_text())
                    validation = json.loads((capture_root / "validation/results.json").read_text())
                    section_identity_valid = capture_metadata.get("section") == section
                    if section == "statistics" and not section_identity_valid:
                        section_identity_valid = _legacy_statistics_section_identity(
                            capture_root, capture_metadata, validation, group
                        )
                    if (
                        capture_metadata.get("source") != "BDFutbol"
                        or capture_metadata.get("season") != "2026-27"
                        or capture_metadata.get("group") != group
                        or not section_identity_valid
                        or validation.get("valid") is not True
                    ):
                        raise ManualUpdateError(f"La captura {section} del Grupo {group} no acredita identidad y validación.")
                    self._validate_related_capture(section, group, capture_root, roots, normalized)
                    content_sha256 = _related_section_content_sha256(capture_root, section)
                    old_root = self._active_related_root(group, section)
                    old_digest = _related_section_content_sha256(old_root, section) if old_root else None
                    changed = old_digest != content_sha256
                    status["groups"][group][section] = {
                        "status": "changed" if changed else "unchanged",
                        "capture_id": capture_metadata.get("capture_id"),
                    }
                    if changed:
                        related["groups"].setdefault(group, {})[section] = {
                            "path": str(capture_root),
                            "sha256": _tree_sha256(capture_root),
                            "content_sha256": content_sha256,
                            "capture_id": capture_metadata["capture_id"],
                        }
                except Exception as exc:
                    reason = f"{type(exc).__name__}: {str(exc)[:240]}"
                    status["groups"][group][section] = {"status": "error", "reason": reason}
                    stop_reason = f"La actualización de {section} del Grupo {group} terminó con error; no se iniciaron más adquisiciones."

        if not stop_reason:
            job["stage"] = "capturing_referees"
            self._save(job)
            output = base / "referees"
            args = [
                sys.executable, "scripts/scrape_bdfutbol_group2_referees.py",
                "--matches", str(normalized["II"]),
                "--output-root", str(output), "--profile", str(self.profile_dir),
                "--pause-seconds", "5",
            ]
            if self.browser_executable:
                args.extend(["--browser-executable", str(self.browser_executable)])
            try:
                capture_root = capture(
                    section="referees", group=None, args=args, output=output, timeout=1200
                )
                metadata = json.loads((capture_root / "metadata/capture.json").read_text())
                if (
                    metadata.get("source") != "BDFutbol"
                    or metadata.get("season") != "2026-27"
                    or metadata.get("section") != "referees"
                    or json.loads((capture_root / "validation/results.json").read_text()).get("valid") is not True
                ):
                    raise ManualUpdateError("La captura de Árbitros no acredita identidad y validación.")
                self._validate_related_capture("referees", None, capture_root, roots, normalized)
                content_sha256 = _related_section_content_sha256(capture_root, "referees")
                old_digest = (
                    _related_section_content_sha256(self.referees_root, "referees")
                    if self.referees_root else None
                )
                changed = old_digest != content_sha256
                status["referees"] = {
                    "status": "changed" if changed else "unchanged",
                    "capture_id": metadata.get("capture_id"),
                }
                if changed:
                    related["referees"] = {
                        "path": str(capture_root),
                        "sha256": _tree_sha256(capture_root),
                        "content_sha256": content_sha256,
                        "capture_id": metadata["capture_id"],
                    }
            except Exception as exc:
                status["referees"] = {
                    "status": "error", "reason": f"{type(exc).__name__}: {str(exc)[:240]}",
                }
        else:
            status["referees"] = {"status": "not_attempted", "reason": stop_reason}
        status["acquisition_stopped"] = stop_reason is not None
        if stop_reason:
            status["stop_reason"] = stop_reason
        return related, status

    def _active_related_root(self, group: str, section: str) -> Path | None:
        settings = self.group_related_settings.get(group)
        if settings is None:
            return None
        if section == "statistics":
            root = settings.statistics_root
        else:
            metadata = settings.top_capture_metadata_path
            root = metadata.parent.parent if metadata is not None else None
        return root.resolve() if root is not None and root.is_dir() else None

    def _validate_related_capture(
        self,
        section: str,
        group: str | None,
        capture_root: Path,
        roots: dict[str, Path],
        normalized: dict[str, Path],
    ) -> None:
        from football_data_hub_api.dataset import load_dataset
        from football_data_hub_api.referee_dataset import load_referee_dataset
        from football_data_hub_api.statistics_dataset import load_statistics_dataset
        from football_data_hub_api.top_dataset import load_top_dataset

        if section in {"top", "statistics"}:
            assert group is not None
            prior = self.group_related_settings.get(group)
            if prior is None:
                raise ManualUpdateError(f"No se configuró el contrato API del Grupo {group}.")
            core = replace(
                prior,
                matches_path=normalized[group],
                classification_path=roots[group] / "normalized/classification.json",
                progress_path=roots[group] / "normalized/progress.json",
                capture_metadata_path=roots[group] / "metadata/capture.json",
            )
            active = load_dataset(core)
            if section == "top":
                top = replace(
                    core,
                    top_players_path=capture_root / "normalized/players.json",
                    top_rankings_path=capture_root / "normalized/rankings.json",
                    top_progress_path=capture_root / "normalized/progress.json",
                    top_foreigners_path=capture_root / "normalized/foreigners.json",
                    top_capture_metadata_path=capture_root / "metadata/capture.json",
                    top_validation_path=capture_root / "validation/results.json",
                    top_source_html_path=capture_root / "raw/source.html",
                    top_team_catalog_path=normalized[group],
                )
                load_top_dataset(
                    top,
                    active_teams=active.bootstrap.teams,
                    active_team_capture_id=active.bootstrap.metadata.capture_id,
                )
            else:
                load_statistics_dataset(replace(core, statistics_root=capture_root), active)
            return
        if self.api_settings is None:
            raise ManualUpdateError("No se configuró ApiSettings para validar Árbitros.")
        referee_settings = replace(self.api_settings, referees_root=capture_root)
        match_sources = {
            "I": (normalized["I"], roots["I"] / "validation/referee_reference.json"),
            "II": (normalized["II"], capture_root / "validation/match_reference.json"),
        }
        load_referee_dataset(referee_settings, group_match_sources=match_sources)

    def _read_team_follow_profile(
        self,
        entry: dict[str, Any],
        *,
        team_id: int,
        group: str,
        catalog_matches: dict[str, dict[str, Any]],
    ) -> tuple[Path, set[str]]:
        """Verify the active profile's Follow evidence before calculating gaps."""
        if self.team_profiles_index is None or self.player_team_captures_root is None:
            raise ManualUpdateError("No están configurados el índice externo y el almacén de capturas de equipos.")
        capture_id = entry.get("capture_id")
        directory_value = entry.get("directory")
        file_hashes = entry.get("files_sha256")
        follow_hashes = entry.get("follow_files_sha256")
        if not isinstance(capture_id, str) or not isinstance(directory_value, str):
            raise ManualUpdateError(f"El índice no fija captura/directorio para team_id={team_id}.")
        if not isinstance(file_hashes, dict) or not isinstance(follow_hashes, dict):
            raise ManualUpdateError(f"El índice no fija los hashes necesarios para team_id={team_id}.")
        configured = Path(directory_value).expanduser()
        if ".." in configured.parts:
            raise ManualUpdateError(f"La ruta seleccionada de team_id={team_id} contiene traversal.")
        unresolved_capture_dir = configured if configured.is_absolute() else self.team_profiles_index.parent / configured
        _reject_symlink_components(unresolved_capture_dir)
        capture_dir = unresolved_capture_dir.resolve()
        root = self.player_team_captures_root.resolve()
        if (
            capture_dir.name != capture_id
            or not capture_dir.is_relative_to(root)
            or capture_dir.is_symlink()
        ):
            raise ManualUpdateError(f"La ruta seleccionada de team_id={team_id} no es una captura externa versionada.")
        for relative in (
            "metadata/capture.json", "validation/results.json", "raw/access.json",
            "normalized/team_identity.json", "normalized/team_season.json",
            "normalized/players.json", "normalized/memberships.json",
        ):
            path = capture_dir / relative
            if path.is_symlink() or not path.is_file() or _sha256(path.read_bytes()) != file_hashes.get(relative):
                raise ManualUpdateError(f"La captura activa del equipo no supera SHA-256 en {relative}.")
        for relative, expected in follow_hashes.items():
            relative_path = Path(relative)
            if relative_path.is_absolute() or ".." in relative_path.parts:
                raise ManualUpdateError(f"La captura activa de Seguimiento tiene una ruta inválida: {relative}.")
            unresolved_path = capture_dir / relative_path
            _reject_symlink_components(unresolved_path)
            path = unresolved_path.resolve()
            if not path.is_relative_to(capture_dir) or not path.is_file():
                raise ManualUpdateError(f"La captura activa de Seguimiento tiene una ruta inválida: {relative}.")
            if _sha256(path.read_bytes()) != expected:
                raise ManualUpdateError(f"La captura activa de Seguimiento no supera SHA-256 en {relative}.")
        metadata = json.loads((capture_dir / "metadata/capture.json").read_text(encoding="utf-8"))
        validation = json.loads((capture_dir / "validation/results.json").read_text(encoding="utf-8"))
        access = json.loads((capture_dir / "raw/access.json").read_text(encoding="utf-8"))
        snapshots = metadata.get("source_snapshots")
        follow_snapshot = snapshots.get("follow") if isinstance(snapshots, dict) else None
        access_by_view = metadata.get("access_by_view")
        follow_report = access_by_view.get("follow") if isinstance(access_by_view, dict) else None
        expected_identity = {
            "source": "BDFutbol", "section": "team_profile", "team_id": team_id,
            "season": "2026-27", "group": group,
        }
        if (
            any(metadata.get(key) != value for key, value in expected_identity.items())
            or metadata.get("capture_id") != capture_id
            or validation.get("valid") is not True
            or access.get("capture_id") != capture_id
            or access.get("views") != access_by_view
            or set(metadata.get("follow_states", {})) != {"p", "t", "go", "tot"}
            or not isinstance(follow_snapshot, dict)
            or follow_snapshot.get("access_status") != "VALID"
            or follow_snapshot.get("http_status") != 200
            or not isinstance(follow_report, dict)
            or follow_report.get("status") != "VALID"
            or follow_report.get("http_status") != 200
            or not follow_report.get("requested_url")
            or follow_report.get("requested_url") != follow_report.get("final_url")
            or follow_snapshot.get("url") != follow_report.get("requested_url")
        ):
            raise ManualUpdateError(f"La identidad, validación o los cuatro estados de Seguimiento no se verifican para team_id={team_id}.")
        indexed_state_hashes = entry.get("follow_states_sha256")
        if indexed_state_hashes is not None and not isinstance(indexed_state_hashes, dict):
            raise ManualUpdateError(f"El índice contiene hashes de estados inválidos para team_id={team_id}.")
        for state, evidence in metadata["follow_states"].items():
            if (
                evidence.get("status") not in {"VALID", "DERIVED_OFFLINE"}
                or evidence.get("selected_value") != state
            ):
                raise ManualUpdateError(f"La evidencia del estado de Seguimiento {state} no coincide con sus hashes.")
            _verified_follow_state_bytes(
                capture_dir,
                state=state,
                evidence=evidence,
                indexed_file_hashes=follow_hashes,
                indexed_state_hashes=indexed_state_hashes,
            )
        minutes_path = capture_dir / "normalized/player_match_minutes.json"
        minutes_hash = follow_hashes.get("normalized/player_match_minutes.json")
        if not minutes_hash or _sha256(minutes_path.read_bytes()) != minutes_hash:
            raise ManualUpdateError(f"Falta el hash de minutos por partido para team_id={team_id}.")
        minutes = json.loads(minutes_path.read_text(encoding="utf-8"))
        document_metadata = minutes.get("metadata") or {}
        if any(document_metadata.get(key) != value for key, value in {
            "capture_id": capture_id, "team_id": team_id, "season": "2026-27", "group": group,
        }.items()):
            raise ManualUpdateError(f"El JSON de Seguimiento no pertenece a team_id={team_id}.")
        records = minutes.get("records")
        if not isinstance(records, list):
            raise ManualUpdateError(f"El JSON de Seguimiento no contiene registros para team_id={team_id}.")
        return capture_dir, _follow_covered_match_ids(records, team_id=team_id, group=group, matches=catalog_matches)

    def _find_team_follow_candidate(
        self,
        *,
        team_id: int,
        group: str,
        team_record: dict[str, Any],
        catalog_path: Path,
        catalog_reference: dict[str, Any],
        group_teams: list[dict[str, Any]],
        group_matches: list[dict[str, Any]],
        missing_match_ids: set[str],
        active_capture_id: str,
    ) -> dict[str, Any] | None:
        """Reuse the newest fully revalidated local capture that covers the gap."""
        if self.player_team_captures_root is None:
            return None
        from football_data_hub.providers.bdfutbol.context import get_competition_context
        from football_data_hub.providers.bdfutbol.teams.acquisition import DEFAULT_VIEWS
        from football_data_hub.providers.bdfutbol.teams.capture_store import inspect_team_capture

        team_root = self.player_team_captures_root / "2026-27" / str(team_id)
        if not team_root.is_dir() or team_root.is_symlink():
            return None
        candidates = sorted(
            (path for path in team_root.iterdir() if path.is_dir() and not path.is_symlink() and path.name != active_capture_id),
            key=lambda path: path.name,
            reverse=True,
        )
        for capture_dir in candidates:
            try:
                inspection = inspect_team_capture(
                    capture_dir,
                    team_catalog_record=team_record,
                    competition=get_competition_context("2026-27", 1 if group == "I" else 2),
                    team_catalog_reference=catalog_reference,
                    group_team_catalog=group_teams,
                    known_matches=group_matches,
                    required_views=DEFAULT_VIEWS,
                    catalog_history_root=self.project_root,
                )
                if not inspection.complete_for_current_policy:
                    continue
                normalized = json.loads((capture_dir / "normalized/player_match_minutes.json").read_text(encoding="utf-8"))
                records = normalized.get("records")
                if not isinstance(records, list):
                    continue
                covered = _follow_covered_match_ids(
                    records,
                    team_id=team_id,
                    group=group,
                    matches={str(row["match_id"]): row for row in group_matches},
                )
                if missing_match_ids <= covered:
                    return {
                        "capture_id": inspection.capture_id,
                        "capture_directory": str(capture_dir.resolve()),
                        "capture_tree_sha256": _tree_sha256(capture_dir),
                        "missing_match_ids": sorted(missing_match_ids),
                        "reused_existing_capture": True,
                        "source_capture_ids": list(inspection.metadata.get("reused_source_capture_ids") or []),
                    }
            except Exception:
                # A corrupt/ambiguous local candidate is retained for diagnosis;
                # it cannot be used to replace the selected profile.
                continue
        return None

    def _update_team_follow(
        self,
        job: dict[str, Any],
        log_path: Path,
        *,
        normalized: dict[str, Path],
        stop_before_acquisition: str | None = None,
    ) -> dict[str, Any]:
        """Incrementally synchronize team player stats and Follow for played fixtures."""
        from football_data_hub.providers.bdfutbol.context import get_competition_context
        from football_data_hub.providers.bdfutbol.teams.catalog import load_team_catalog

        if self.team_profiles_index is None or self.player_team_captures_root is None:
            return {
                "status": "error",
                "teams": {},
                "reason": "El índice publicado o el almacén externo de capturas de equipos no está configurado.",
            }
        if self.team_profiles_index.is_symlink() or self.team_profiles_index.is_relative_to(self.project_root):
            return {"status": "error", "teams": {}, "reason": "El índice de equipos no es un archivo externo seguro."}
        try:
            index_bytes = self.team_profiles_index.read_bytes()
            index = json.loads(index_bytes)
            profiles = index.get("profiles")
            if index.get("schema_version") != 1 or index.get("season") != "2026-27" or not isinstance(profiles, dict):
                raise ValueError("contrato del índice no compatible")
            loaded = {
                group: load_team_catalog(normalized[group], competition=get_competition_context("2026-27", 1 if group == "I" else 2))
                for group in ("I", "II")
            }
            team_records = {group: value[0] for group, value in loaded.items()}
            matches_by_group = {group: value[1] for group, value in loaded.items()}
            references = {group: value[2] for group, value in loaded.items()}
            expected_profiles = {
                str(int(team["team_id"]))
                for group in ("I", "II") for team in team_records[group]
            }
            if len(expected_profiles) != 40 or set(profiles) != expected_profiles:
                raise ValueError("el índice y los dos catálogos no contienen los mismos 40 equipos")
            played_by_group, matches_by_team_catalog = _team_match_ids_by_group(matches_by_group)
        except Exception as exc:
            return {"status": "error", "teams": {}, "reason": f"No se pudo reconciliar el índice/catálogos de equipos: {type(exc).__name__}: {exc}"}

        index_sha256 = _sha256(index_bytes)
        statuses: dict[str, Any] = {}
        candidates: list[dict[str, Any]] = []
        acquisition_targets: list[tuple[int, str, dict[str, Any], set[str], Path]] = []
        for group in ("I", "II"):
            group_matches = matches_by_group[group]
            group_match_map = matches_by_team_catalog[group]
            for team in team_records[group]:
                team_id = int(team["team_id"])
                key = str(team_id)
                try:
                    active_dir, covered = self._read_team_follow_profile(
                        profiles[key], team_id=team_id, group=group, catalog_matches=group_match_map,
                    )
                    required = played_by_group[group].get(team_id, set())
                    missing = required - covered
                    if not missing:
                        statuses[key] = {
                            "status": "unchanged", "group": group,
                            "played_matches": len(required), "covered_matches": len(required),
                            "capture_id": active_dir.name,
                        }
                        continue
                    candidate = self._find_team_follow_candidate(
                        team_id=team_id, group=group, team_record=team,
                        catalog_path=normalized[group], catalog_reference=references[group],
                        group_teams=team_records[group], group_matches=group_matches,
                        missing_match_ids=missing, active_capture_id=active_dir.name,
                    )
                    if candidate is not None:
                        candidate.update({
                            "team_id": team_id, "group": group,
                            "previous_capture_id": active_dir.name,
                            "previous_covered_match_ids": sorted(covered),
                        })
                        candidates.append(candidate)
                        statuses[key] = {
                            "status": "changed", "group": group,
                            "missing_match_ids": sorted(missing), "capture_id": candidate["capture_id"],
                            "reused_existing_capture": True,
                        }
                    else:
                        acquisition_targets.append((team_id, group, team, missing, active_dir))
                        statuses[key] = {
                            "status": "pending", "group": group,
                            "missing_match_ids": sorted(missing), "capture_id": active_dir.name,
                        }
                except Exception as exc:
                    statuses[key] = {"status": "error", "group": group, "reason": f"{type(exc).__name__}: {str(exc)[:220]}"}

        batch_manifest_path: Path | None = None
        batch_error: str | None = None
        if acquisition_targets and stop_before_acquisition:
            batch_error = stop_before_acquisition
            for team_id, group, _team, missing, _active_dir in acquisition_targets:
                statuses[str(team_id)] = {
                    "status": "not_attempted", "group": group,
                    "missing_match_ids": sorted(missing),
                    "reason": stop_before_acquisition,
                }
            acquisition_targets = []
        if acquisition_targets:
            job["stage"] = "refreshing_team_profiles"
            self._save(job)
            store_root = self.player_team_captures_root
            manifests_dir = store_root / "2026-27" / "batch-manifests"
            previous_manifests = set(manifests_dir.glob("*/manifest.json")) if manifests_dir.is_dir() else set()
            args = [
                sys.executable, "scripts/acquire_bdfutbol_team_batch.py",
                "--season", "2026-27", "--groups", "both", "--pause-seconds", "5",
                "--output-root", str(store_root),
                "--group1-catalog", str(normalized["I"]), "--group2-catalog", str(normalized["II"]),
                "--profile", str(self.profile_dir),
            ]
            for view in TEAM_PROFILE_REFRESH_VIEWS:
                args.extend(("--view", view))
            for view in TEAM_PROFILE_REFRESH_VIEWS:
                args.extend(("--refresh-view", view))
            for team_id, _group, _team, _missing, _active_dir in acquisition_targets:
                args.extend(["--team-id", str(team_id)])
            if self.browser_executable:
                args.extend(["--browser-executable", str(self.browser_executable)])
            # The provider batch owns sequential pauses and stops after any
            # access denial. This generous bound is for a single uninterrupted
            # 40-team, three-view run; it does not enable retries.
            try:
                time.sleep(5)
                self._command(args, log_path, timeout=14_400)
            except Exception as exc:
                batch_error = f"{type(exc).__name__}: {str(exc)[:240]}"
            new_manifests = sorted(
                (set(manifests_dir.glob("*/manifest.json")) - previous_manifests)
                if manifests_dir.is_dir() else (),
                key=lambda path: path.stat().st_mtime_ns,
                reverse=True,
            )
            if len(new_manifests) == 1:
                batch_manifest_path = new_manifests[0]
                try:
                    manifest = json.loads(batch_manifest_path.read_text(encoding="utf-8"))
                    for entry in manifest.get("teams", []):
                        team_id = int(entry["team_id"])
                        key = str(team_id)
                        target = next((item for item in acquisition_targets if item[0] == team_id), None)
                        if target is None or entry.get("status") != "complete" or not entry.get("capture_id"):
                            if target is not None:
                                statuses[key] = {
                                    "status": "error" if entry.get("status") in {"failed", "incomplete"} else "not_attempted",
                                    "group": target[1], "missing_match_ids": sorted(target[3]),
                                    "reason": entry.get("error") or (manifest.get("stop_reason") or {}).get("message") or batch_error or "No se produjo una captura completa.",
                                }
                            continue
                        _team_id, group, team, missing, _active_dir = target
                        capture_dir = store_root / "2026-27" / str(team_id) / str(entry["capture_id"])
                        from football_data_hub.providers.bdfutbol.context import get_competition_context
                        from football_data_hub.providers.bdfutbol.teams.acquisition import DEFAULT_VIEWS
                        from football_data_hub.providers.bdfutbol.teams.capture_store import inspect_team_capture

                        inspection = inspect_team_capture(
                            capture_dir,
                            team_catalog_record=team,
                            competition=get_competition_context("2026-27", 1 if group == "I" else 2),
                            team_catalog_reference=references[group],
                            group_team_catalog=team_records[group],
                            known_matches=matches_by_group[group],
                            required_views=DEFAULT_VIEWS,
                            catalog_history_root=self.project_root,
                        )
                        if not inspection.complete_for_current_policy:
                            raise ManualUpdateError(f"La captura incremental del equipo {team_id} no es completa: {'; '.join(inspection.reasons[:3])}")
                        normalized_minutes = json.loads((capture_dir / "normalized/player_match_minutes.json").read_text(encoding="utf-8"))
                        records = normalized_minutes.get("records")
                        if not isinstance(records, list):
                            raise ManualUpdateError(f"La captura incremental del equipo {team_id} carece de minutos normalizados.")
                        covered = _follow_covered_match_ids(
                            records, team_id=team_id, group=group,
                            matches=matches_by_team_catalog[group],
                        )
                        if not missing <= covered:
                            raise ManualUpdateError(f"La captura incremental del equipo {team_id} sigue sin cubrir todos los partidos disputados.")
                        candidate = {
                            "team_id": team_id, "group": group,
                            "capture_id": inspection.capture_id,
                            "capture_directory": str(capture_dir.resolve()),
                            "capture_tree_sha256": _tree_sha256(capture_dir),
                            "previous_capture_id": _active_dir.name,
                            "previous_covered_match_ids": sorted(played_by_group[group].get(team_id, set()) - missing),
                            "missing_match_ids": sorted(missing),
                            "reused_existing_capture": False,
                            "acquired_views": list(entry.get("acquired_views") or []),
                            "reused_views": list(entry.get("reused_views") or []),
                            "acquired_follow_states": list(entry.get("acquired_follow_states") or []),
                            "reused_follow_states": list(entry.get("reused_follow_states") or []),
                        }
                        candidates.append(candidate)
                        statuses[key] = {
                            "status": "changed", "group": group,
                            "missing_match_ids": sorted(missing),
                            "capture_id": inspection.capture_id,
                            "reused_existing_capture": False,
                            "acquired_views": candidate["acquired_views"],
                        }
                except Exception as exc:
                    batch_error = batch_error or f"{type(exc).__name__}: {str(exc)[:240]}"
            elif batch_error is None:
                batch_error = "El lote de perfiles no dejó exactamente un manifiesto nuevo e íntegro."
            for team_id, group, _team, missing, _active_dir in acquisition_targets:
                key = str(team_id)
                if statuses.get(key, {}).get("status") == "pending":
                    statuses[key] = {
                        "status": "not_attempted", "group": group,
                        "missing_match_ids": sorted(missing),
                        "reason": batch_error or "El lote secuencial no llegó a este equipo.",
                    }

        errors = sum(item.get("status") == "error" for item in statuses.values())
        pending = sum(item.get("status") == "not_attempted" for item in statuses.values())
        changed = sum(item.get("status") == "changed" for item in statuses.values())
        unchanged = sum(item.get("status") == "unchanged" for item in statuses.values())
        return {
            "status": "error" if errors and not changed else "partial" if errors or pending else "changed" if changed else "unchanged",
            "teams": statuses,
            "candidate_profiles": candidates,
            "candidate_count": len(candidates),
            "changed_team_count": changed,
            "unchanged_team_count": unchanged,
            "error_team_count": errors,
            "pending_team_count": pending,
            "source_index_sha256": index_sha256,
            "batch_manifest": str(batch_manifest_path) if batch_manifest_path else None,
            "batch_error": batch_error,
        }

    def _update_team(self, job: dict[str, Any], log_path: Path) -> dict[str, Any]:
        assert self.data_root and job.get("team_id") and job.get("group")
        if self.team_profiles_index is None:
            raise ManualUpdateError("No hay índice de perfiles de equipo configurado para comparar.")
        if self.team_profiles_index.is_relative_to(self.project_root):
            raise ManualUpdateError("Configura FDH_TEAM_PROFILES_INDEX fuera del checkout antes de adquirir equipos.")
        group_paths = self.group_match_paths
        output_root = self.player_team_captures_root or (self.data_root / "team-captures")
        if not output_root.is_dir():
            raise ManualUpdateError("No existe el almacén externo de capturas de equipos.")
        index_bytes = self.team_profiles_index.read_bytes()
        prior_index = json.loads(index_bytes)
        prior = prior_index.get("profiles", {}).get(str(job["team_id"]), {})
        manifest_dir = output_root / "2026-27" / "batch-manifests"
        previous_manifests = set(manifest_dir.glob("*/manifest.json")) if manifest_dir.exists() else set()
        args = [
            sys.executable, "scripts/acquire_bdfutbol_team_batch.py",
            "--season", "2026-27", "--groups", str(job["group"]),
            "--team-id", str(job["team_id"]), "--pause-seconds", "5",
            "--force-refresh", "--output-root", str(output_root),
            "--group1-catalog", str(group_paths["I"]), "--group2-catalog", str(group_paths["II"]),
            "--profile", str(self.profile_dir),
        ]
        if self.browser_executable:
            args.extend(["--browser-executable", str(self.browser_executable)])
        job["stage"] = "capturing_team"
        self._save(job)
        self._command(args, log_path, timeout=2400)
        try:
            new_manifests = set(manifest_dir.glob("*/manifest.json")) - previous_manifests
            if len(new_manifests) != 1:
                raise ValueError("No se creó un único manifiesto nuevo")
            manifest_path = next(iter(new_manifests)).resolve()
            batch = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (ValueError, KeyError, OSError, json.JSONDecodeError) as exc:
            raise ManualUpdateError("No se pudo verificar el manifiesto del piloto de equipo.") from exc
        entries = [entry for entry in batch.get("teams", []) if entry.get("team_id") == job["team_id"]]
        if len(entries) != 1 or entries[0].get("status") != "complete" or not entries[0].get("capture_id"):
            raise ManualUpdateError("La captura del equipo no se marcó completa por el validador existente.")
        entry = entries[0]
        capture_dir = output_root / "2026-27" / str(job["team_id"]) / entry["capture_id"]
        validation = json.loads((capture_dir / "validation/results.json").read_text(encoding="utf-8"))
        if validation.get("valid") is not True:
            raise ManualUpdateError("La revalidación offline de la captura del equipo falló.")
        changes = _team_data_changes(capture_dir, prior, self.team_profiles_index)
        prior_dir = None
        if prior.get("directory"):
            prior_dir_value = Path(str(prior["directory"])).expanduser()
            prior_dir = prior_dir_value.resolve() if prior_dir_value.is_absolute() else (self.team_profiles_index.parent / prior_dir_value).resolve()
            if prior_dir.name != prior.get("capture_id"):
                raise ManualUpdateError("La ruta de la captura anterior no coincide con su capture_id publicado.")
        change_details = _team_change_details(capture_dir, prior_dir, changes)
        return {
            "kind": "team_profile_capture",
            "no_changes": bool(prior) and not changes,
            "team_id": job["team_id"],
            "group": job["group"],
            "capture_id": entry["capture_id"],
            "capture_directory": str(capture_dir),
            "capture_tree_sha256": _tree_sha256(capture_dir),
            "validation": validation.get("summary", {}),
            "requested_views": entry.get("requested_views", []),
            "follow_states": entry.get("follow_states", []),
            "changed_files": changes,
            "change_details": change_details,
            "previous_capture_id": prior.get("capture_id"),
            "published_index_sha256": _sha256(index_bytes),
            "activated": False,
            "published": False,
        }

    def approve_and_activate(
        self,
        *,
        job_id: str,
        reviewer: str,
        expected_candidate_sha256: str,
    ) -> dict[str, Any]:
        if not self.enabled:
            raise ManualUpdateError("Las publicaciones administrativas no están habilitadas.")
        job = self._read(job_id)
        if not job:
            raise ManualUpdateError("No existe un candidato de actualización verificable.")
        lock_dir = self.root / "locks"  # type: ignore[operator]
        global_fd = self._lock(lock_dir / "browser.lock")
        try:
            scope_fd = self._lock(lock_dir / f"{job.get('scope_key')}.lock")
        except BaseException:
            fcntl.flock(global_fd, fcntl.LOCK_UN)
            os.close(global_fd)
            raise
        try:
            return self._approve_and_activate_locked(
                job_id=job_id,
                reviewer=reviewer,
                expected_candidate_sha256=expected_candidate_sha256,
            )
        finally:
            for descriptor in (scope_fd, global_fd):
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                finally:
                    os.close(descriptor)

    def _approve_and_activate_locked(
        self,
        *,
        job_id: str,
        reviewer: str,
        expected_candidate_sha256: str,
    ) -> dict[str, Any]:
        job = self._read(job_id)
        if not job or job.get("scope") not in {"competition", "team"}:
            raise ManualUpdateError("No existe un candidato de actualización verificable.")
        reviewer = reviewer.strip()
        if not reviewer or len(reviewer) > 120:
            raise ManualUpdateError("Indica un nombre de revisor (máximo 120 caracteres).")
        candidate = job.get("candidate")
        if not isinstance(candidate, dict):
            raise ManualUpdateError("El trabajo no contiene un candidato validado.")
        stored_hash = job.get("candidate_sha256")
        candidate_body = {key: value for key, value in candidate.items() if key != "candidate_sha256"}
        actual_hash = _sha256(json.dumps(candidate_body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode())
        if (
            not isinstance(stored_hash, str)
            or not hmac.compare_digest(stored_hash, actual_hash)
            or not hmac.compare_digest(stored_hash, expected_candidate_sha256)
        ):
            raise ManualUpdateError("La huella del candidato no coincide con el que se revisó.")
        if job.get("status") == "published":
            return job
        if job.get("status") != "review_required":
            raise ManualUpdateError("Solo se pueden activar candidatos que esperan revisión.")
        if (self.root / "activation-pending.json").exists() and job.get("scope") != "competition":  # type: ignore[operator]
            raise ManualUpdateError("Hay una activación de competición pendiente que debe resolverse primero.")
        if candidate.get("no_changes"):
            raise ManualUpdateError("No hay cambios deportivos que activar.")

        event_root = self.root / "reviews"  # type: ignore[operator]
        event_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        event_id = job_id
        approval_path = event_root / f"{event_id}-approval.json"
        approval = {
            "schema_version": 1,
            "event": "MANUAL_UPDATE_APPROVED",
            "event_id": event_id,
            "job_id": job_id,
            "scope": job["scope"],
            "team_id": job.get("team_id"),
            "candidate_sha256": stored_hash,
            "reviewer": reviewer,
            "approved_at": utc_now(),
        }
        if approval_path.exists():
            try:
                previous = json.loads(approval_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ManualUpdateError("El evento de aprobación existente está corrupto.") from exc
            if any(previous.get(key) != approval.get(key) for key in (
                "event", "job_id", "scope", "team_id", "candidate_sha256", "reviewer"
            )):
                raise ManualUpdateError("Ya existe una aprobación incompatible para este trabajo.")
        else:
            _create_once(
                approval_path,
                (json.dumps(approval, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(),
            )
        log_path = self._jobs_dir() / job_id / "worker.log"
        publication_path = event_root / f"{event_id}-publication.json"
        if publication_path.exists():
            try:
                previous_publication = json.loads(publication_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ManualUpdateError("El evento de publicación existente está corrupto.") from exc
            if any(previous_publication.get(key) != value for key, value in (
                ("event", "MANUAL_UPDATE_PUBLISHED"),
                ("job_id", job_id),
                ("candidate_sha256", stored_hash),
                ("reviewer", reviewer),
            )):
                raise ManualUpdateError("Ya existe un evento de publicación incompatible para este trabajo.")
            publication = previous_publication.get("publication")
            if not isinstance(publication, dict):
                raise ManualUpdateError("El evento de publicación no contiene un recibo verificable.")
        else:
            if job["scope"] == "competition":
                publication = self._activate_competition(job, reviewer, log_path)
            else:
                publication = self._publish_team(job, reviewer, log_path)
            publication_event = {
                "schema_version": 1,
                "event": "MANUAL_UPDATE_PUBLISHED",
                "event_id": event_id,
                "job_id": job_id,
                "candidate_sha256": stored_hash,
                "reviewer": reviewer,
                "published_at": utc_now(),
                "publication": publication,
            }
            _create_once(
                publication_path,
                (json.dumps(publication_event, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(),
            )
        job.update({
            "status": "published", "stage": "published", "finished_at": utc_now(),
            "publication": publication, "review_event_id": event_id,
        })
        self._save(job)
        return job

    def _activate_competition(self, job: dict[str, Any], reviewer: str, log_path: Path) -> dict[str, Any]:
        candidate = job["candidate"]
        for group in ("I", "II"):
            capture_root = Path(candidate["source_captures"][group])
            matches_path = Path(candidate["normalized_matches"][group])
            _reject_symlink_components(matches_path)
            if _tree_sha256(capture_root) != candidate.get("source_capture_sha256", {}).get(group):
                raise ManualUpdateError(f"La captura del Grupo {group} cambió después de la revisión.")
            if _sha256(matches_path.read_bytes()) != candidate.get("normalized_match_sha256", {}).get(group):
                raise ManualUpdateError(f"Los resultados normalizados del Grupo {group} cambiaron después de la revisión.")
        candidate_directory = Path(candidate["candidate_directory"])
        if _tree_sha256(candidate_directory) != candidate.get("candidate_generation_sha256"):
            raise ManualUpdateError("La generación candidata cambió después de la revisión.")
        report_path = Path(candidate["diff_report"])
        _reject_symlink_components(report_path)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if _sha256(report_path.read_bytes()) != candidate.get("diff_artifact_sha256"):
            raise ManualUpdateError("El informe de diferencias cambió desde la revisión.")
        if report.get("report_sha256") != candidate.get("report_sha256"):
            raise ManualUpdateError("La huella de comparación no coincide con el informe.")
        report_summary = report.get("summary")
        if not isinstance(report_summary, dict) or report_summary != candidate.get("summary"):
            raise ManualUpdateError("El resumen de comparación no coincide con el candidato.")
        if report_summary.get("hard_conflicts") != 0:
            raise ManualUpdateError("Hay conflictos de identidad o calendario; la generación no se activará.")
        if report_summary.get("played_to_unplayed_conflicts") != 0:
            raise ManualUpdateError("Un partido disputado vuelve a aparecer pendiente; la generación no se activará.")
        assert self.data_root is not None
        journal_path = self.root / "activation-pending.json"  # type: ignore[operator]
        if journal_path.exists():
            try:
                journal = json.loads(journal_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ManualUpdateError("El journal de activación está corrupto; requiere recuperación administrativa.") from exc
            if (
                journal.get("job_id") != job.get("job_id")
                or journal.get("candidate_sha256") != job.get("candidate_sha256")
                or journal.get("candidate_generation_id") != candidate.get("candidate_generation_id")
            ):
                raise ManualUpdateError("El journal pertenece a otra actualización; no se cambiarán los punteros.")
        else:
            _atomic_json(journal_path, {
                "schema_version": 1,
                "job_id": job["job_id"],
                "candidate_generation_id": candidate.get("candidate_generation_id"),
                "candidate_sha256": job.get("candidate_sha256"),
                "started_at": utc_now(),
                "state": "activation_started",
            })
        args = [
            sys.executable, "scripts/manage_bdfutbol_match_generations.py", "activate",
            "--data-root", str(self.data_root),
            "--store-root", str(self.match_details_store_root.parent),
            "--candidate", str(Path(candidate["candidate_directory"]).resolve()),
            "--reviewer", reviewer,
            "--confirm-report-sha256", str(report["report_sha256"]),
        ]
        if report.get("before_generation_id"):
            args.extend(["--expected-current-generation", str(report["before_generation_id"])])
        for flag, path in (
            ("--player-inventory-root", self.player_inventory_root),
            ("--player-compact-root", self.player_compact_root),
            ("--team-captures-root", self.player_team_captures_root),
            ("--team-profiles-index", self.player_published_index_path),
        ):
            if path:
                args.extend([flag, str(path)])
        output = self._command(args, log_path, timeout=900)
        receipt = _last_json_object(output)
        if receipt.get("status") not in {"activated", "already_active"} or receipt.get("generation_id") != candidate.get("candidate_generation_id"):
            raise ManualUpdateError("MATCH no confirmó la activación de la generación revisada.")
        receipt["group_data_pointer_sha256"] = _activate_group_data_pointer(self.data_root, candidate)
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        journal.update({"state": "pointers_written", "completed_at": utc_now(), "receipt": receipt})
        _atomic_json(journal_path, journal)
        journal_path.unlink()
        directory_fd = os.open(journal_path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return receipt

    def _publish_team(self, job: dict[str, Any], reviewer: str, log_path: Path) -> dict[str, Any]:
        if self.team_profiles_index is None:
            raise ManualUpdateError("No hay un índice externo de perfiles configurado.")
        candidate = job["candidate"]
        capture_directory = Path(candidate["capture_directory"])
        if _tree_sha256(capture_directory) != candidate.get("capture_tree_sha256"):
            raise ManualUpdateError("La captura del equipo cambió después de la revisión.")
        store_root = self.player_team_captures_root or (self.data_root / "team-captures")  # type: ignore[operator]
        if self.team_profiles_index.is_symlink():
            raise ManualUpdateError("El índice de equipos es un symlink; se detuvo para evitar reemplazos ambiguos.")
        index_bytes = self.team_profiles_index.read_bytes()
        active_index = json.loads(index_bytes)
        profiles = active_index.get("profiles")
        if active_index.get("schema_version") != 1 or active_index.get("season") != "2026-27" or not isinstance(profiles, dict):
            raise ManualUpdateError("El índice publicado de equipos no cumple el contrato esperado.")
        team_id = int(job["team_id"])
        current = profiles.get(str(team_id))
        if _sha256(index_bytes) != candidate.get("published_index_sha256"):
            if (
                isinstance(current, dict)
                and current.get("capture_id") == candidate.get("capture_id")
                and len(profiles) == 40
            ):
                directory = Path(str(current.get("directory") or "")).expanduser()
                if not directory.is_absolute():
                    directory = self.team_profiles_index.parent / directory
                hashes = current.get("files_sha256")
                if directory.resolve() != capture_directory or not isinstance(hashes, dict):
                    raise ManualUpdateError("El índice ya referencia el candidato, pero su identidad/procedencia no coincide.")
                for relative, expected in hashes.items():
                    path = (capture_directory / relative).resolve()
                    if not path.is_relative_to(capture_directory) or not path.is_file() or _sha256(path.read_bytes()) != expected:
                        raise ManualUpdateError("El índice ya referencia el candidato, pero falla la verificación de un archivo.")
                receipt = {
                    "status": "already_published",
                    "profiles": 40,
                    "capture_id": candidate["capture_id"],
                    "index_sha256": _sha256(index_bytes),
                    "reviewer": reviewer,
                    "team_id": team_id,
                }
                return receipt
            raise ManualUpdateError("El índice de equipos cambió desde la captura; se requiere una nueva comprobación.")
        if not isinstance(current, dict) or current.get("capture_id") != candidate.get("previous_capture_id"):
            raise ManualUpdateError("La captura activa del equipo cambió desde la revisión.")
        catalog_by_id: dict[int, tuple[str, str]] = {}
        for group in ("I", "II"):
            payload = json.loads(self.group_match_paths[group].read_text(encoding="utf-8"))
            for team in payload.get("teams", []):
                catalog_by_id[int(team["team_id"])] = (group, str(team.get("name") or team.get("team_name") or ""))
        if len(catalog_by_id) != 40 or set(map(int, profiles)) != set(catalog_by_id):
            raise ManualUpdateError("El índice y los catálogos no contienen los mismos 40 IDs de equipo.")
        manifest_teams = []
        for selected_id, (group, name) in sorted(catalog_by_id.items()):
            selected_profile = profiles[str(selected_id)]
            selected_capture = candidate["capture_id"] if selected_id == team_id else selected_profile.get("capture_id")
            selected_directory = candidate["capture_directory"] if selected_id == team_id else selected_profile.get("directory")
            if not selected_capture or not selected_directory:
                raise ManualUpdateError(f"El perfil existente {selected_id} no tiene captura verificable.")
            selected_directory_path = Path(str(selected_directory)).expanduser()
            if not selected_directory_path.is_absolute():
                selected_directory_path = self.team_profiles_index.parent / selected_directory_path
            manifest_teams.append({
                "group": group,
                "team_id": selected_id,
                "team_name": name,
                "status": "complete",
                "capture_id": selected_capture,
                "coverage": {"capture_path": str(selected_directory_path.resolve())},
            })
        manifest = {
            "schema_version": 1,
            "season": "2026-27",
            "run_id": f"manual-update-{job['job_id']}",
            "batch_complete": True,
            "stopped_on_access_denial": False,
            "stop_reason": None,
            "requested_views": ["alignment", "squad", "statistics", "follow", "transfers", "matches"],
            "required_follow_states": ["p", "t", "go", "tot"],
            "teams": manifest_teams,
        }
        manifest_path = self._jobs_dir() / str(job["job_id"]) / "publish-manifest.json"
        raw_manifest = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()
        if manifest_path.exists():
            if manifest_path.read_bytes() != raw_manifest:
                raise ManualUpdateError("El manifiesto de publicación existente no coincide; no se sobrescribirá.")
        else:
            descriptor = os.open(manifest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw_manifest)
                stream.flush()
                os.fsync(stream.fileno())
        output = self._command([
            sys.executable, "scripts/publish_bdfutbol_team_profiles.py",
            "--store-root", str(store_root), "--manifest", str(manifest_path),
            "--group1-catalog", str(self.group_match_paths["I"]),
            "--group2-catalog", str(self.group_match_paths["II"]),
            "--output", str(self.team_profiles_index),
        ], log_path, timeout=900)
        receipt = _last_json_object(output)
        new_bytes = self.team_profiles_index.read_bytes()
        new_index = json.loads(new_bytes)
        published = new_index.get("profiles", {}).get(str(team_id), {})
        if published.get("capture_id") != candidate.get("capture_id") or receipt.get("profiles") != 40:
            raise ManualUpdateError("La publicación del equipo no confirma el nuevo capture_id en un índice de 40 equipos.")
        receipt["index_sha256"] = _sha256(new_bytes)
        receipt["reviewer"] = reviewer
        receipt["team_id"] = team_id
        return receipt
