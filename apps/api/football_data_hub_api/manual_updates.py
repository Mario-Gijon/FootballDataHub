"""Loopback-only incremental updates using existing BDFutbol pipelines.

Competition snapshots are acquired sequentially, validated, compared by stable
IDs, and activated automatically only when the generation is conflict-free.
Team capture helpers remain for historical job compatibility; they are not
exposed by the current update API.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from football_data_hub_api.config import GroupDatasetSettings


class ManualUpdateError(RuntimeError):
    """A requested update could not be safely prepared."""


class UpdateAlreadyRunning(ManualUpdateError):
    """Another update owns the browser or the requested scope."""


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
        if pointer.get("schema_version") != "football_data_hub.manual_group_data.v1":
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
    return replace(
        settings,
        matches_path=paths["matches"],
        classification_path=paths["classification"],
        progress_path=paths["progress"],
        capture_metadata_path=paths["capture_metadata"],
    )


def _activate_group_data_pointer(data_root: Path, candidate: dict[str, Any]) -> str:
    pointer_path = data_root / "operations" / "manual-updates" / "active-group-data.json"
    if pointer_path.is_symlink():
        raise ManualUpdateError("El puntero activo de grupos es un symlink; se detuvo.")
    if pointer_path.is_file():
        pointer_bytes = pointer_path.read_bytes()
        pointer = json.loads(pointer_bytes)
        if pointer.get("schema_version") != "football_data_hub.manual_group_data.v1" or not isinstance(pointer.get("groups"), dict):
            raise ManualUpdateError("El puntero activo de grupos no cumple el contrato esperado.")
        groups = dict(pointer["groups"])
    else:
        pointer_bytes = None
        groups = {}
    sources = candidate.get("source_captures") or {}
    normalized = candidate.get("normalized_matches") or {}
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
    if pointer_bytes is not None:
        history = pointer_path.parent / "active-group-data-history"
        history.mkdir(parents=True, exist_ok=True, mode=0o700)
        previous_id = _sha256(pointer_bytes)
        history_path = history / f"{previous_id}.json"
        _create_once(history_path, pointer_bytes)
    _atomic_json(pointer_path, {
        "schema_version": "football_data_hub.manual_group_data.v1",
        "season": "2026-27",
        "groups": groups,
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


def public_manual_update_job(job: dict[str, Any] | None) -> dict[str, Any] | None:
    """Project only user-facing progress; source paths and integrity hashes stay local."""
    if job is None:
        return None
    return {
        key: job.get(key)
        for key in (
            "job_id", "scope", "team_id", "group", "status", "stage",
            "created_at", "updated_at", "finished_at", "summary", "error",
        )
    }


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
    consumed = -1
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, size = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and size > consumed:
            parsed = value
            consumed = size
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
        self.root = (self.data_root / "operations" / "manual-updates") if self.data_root else None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fdh-manual-update")
        self._mutex = threading.RLock()
        self._leases: dict[str, tuple[int, int]] = {}
        self._active_processes: set[subprocess.Popen[bytes]] = set()
        self.on_competition_applied: Callable[[dict[str, Any]], None] | None = None
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
            job.update({
                "status": "failed",
                "stage": "failed",
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

    def _finish_competition_update(
        self, job: dict[str, Any], log_path: Path, *, no_changes: bool
    ) -> None:
        candidate = job.get("candidate")
        if not isinstance(candidate, dict):
            raise ManualUpdateError("La actualización no produjo un candidato verificable.")
        if no_changes:
            job.update({
                "status": "completed",
                "stage": "no_changes",
                "finished_at": utc_now(),
                "summary": {"message": "Sin cambios", "changed_groups": candidate.get("changed_groups", {})},
            })
            self._save(job)
            return

        stored_hash = job.get("candidate_sha256")
        candidate_hash = candidate.get("candidate_sha256")
        candidate_body = {key: value for key, value in candidate.items() if key != "candidate_sha256"}
        if (
            not isinstance(stored_hash, str)
            or candidate_hash != stored_hash
            or not hmac.compare_digest(stored_hash, _candidate_sha256(candidate_body))
        ):
            raise ManualUpdateError("La huella interna del candidato no coincide.")
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
            "candidate_sha256": stored_hash,
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
        job.update({
            "status": "applied",
            "stage": "refreshing_api",
            "finished_at": utc_now(),
            "summary": summary,
            "publication": publication,
            "auto_apply_event_id": event_id,
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
                    "finished_at": utc_now(),
                })
                self._save(job)
                return
        job.update({"stage": "completed", "finished_at": utc_now()})
        self._save(job)

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
            "message": "Actualización aplicada",
            "changed_groups": candidate.get("changed_groups", {}),
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
            raise ManualUpdateError(f"El proceso terminó con código {return_code}; no se reintentó.")
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
            normalized[group] = base / "normalized" / f"group-{group.lower()}" / "matches.json"
            normalized[group].parent.mkdir(parents=True, exist_ok=False, mode=0o700)
            self._command([
                sys.executable, "scripts/extract_bdfutbol_matches.py",
                "--snapshot", str(roots[group] / "raw/source.html"),
                "--capture", str(roots[group] / "metadata/capture.json"),
                "--output", str(normalized[group]),
            ], log_path, timeout=300)
            validation = json.loads((roots[group] / "validation/results.json").read_text(encoding="utf-8"))
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

        if not any(changed_groups.values()):
            return {
                "kind": "competition_generation",
                "no_changes": True,
                "changed_groups": changed_groups,
                "standings_changes": standings_changes,
                "progress_changes": progress_changes,
                "source_captures": {group: str(path) for group, path in roots.items()},
                "normalized_matches": {group: str(path) for group, path in normalized.items()},
                "source_capture_sha256": {group: _tree_sha256(path) for group, path in roots.items()},
                "normalized_match_sha256": {group: _sha256(path.read_bytes()) for group, path in normalized.items()},
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
            "candidate_generation_sha256": _tree_sha256(candidate_path),
            "activated": False,
            "published_match_details": False,
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
