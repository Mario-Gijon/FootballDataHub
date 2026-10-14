"""Offline inventory of player identities and team-season evidence."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


class PlayerInventoryError(ValueError):
    """Raised when an input capture cannot support a trustworthy inventory."""


PLAYER_IDENTITY_FIELDS = (
    "display_name",
    "full_name",
    "profile_url",
    "photo_url",
    "age_years",
)
REQUIRED_CAPTURE_FILES = (
    "metadata/capture.json",
    "validation/results.json",
    "normalized/team_identity.json",
    "normalized/players.json",
    "normalized/memberships.json",
    "normalized/player_statistics.json",
)
OPTIONAL_PLAYER_FILES = (
    "normalized/player_match_minutes.json",
    "normalized/player_match_metrics.json",
    "normalized/transfers.json",
)


def _json_file(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlayerInventoryError(f"No se puede leer JSON válido: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PlayerInventoryError(f"El documento JSON debe ser un objeto: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise PlayerInventoryError(f"No se puede leer el archivo de origen {path}: {exc}") from exc
    return digest.hexdigest()


def _expected_sha256(profile: dict[str, Any], relative: str) -> str | None:
    found = {
        mapping[relative]
        for key in (
            "files_sha256",
            "normalized_files_sha256",
            "follow_files_sha256",
            "transfers_files_sha256",
        )
        if isinstance((mapping := profile.get(key)), dict) and relative in mapping
    }
    if len(found) > 1:
        raise PlayerInventoryError(f"El índice publica hashes contradictorios para {relative}.")
    return next(iter(found), None)


def _checked_capture_file(
    capture_dir: Path,
    profile: dict[str, Any],
    relative: str,
    *,
    required: bool,
) -> tuple[Path, dict[str, Any]] | None:
    path = capture_dir / relative
    if not path.is_file():
        if required:
            raise PlayerInventoryError(f"Falta un archivo requerido de la captura: {path}")
        return None
    expected = _expected_sha256(profile, relative)
    if not expected:
        if required:
            raise PlayerInventoryError(f"El índice publicado no contiene SHA-256 para {relative}.")
        return None
    actual = _sha256(path)
    if actual != expected:
        raise PlayerInventoryError(
            f"SHA-256 incorrecto en {relative}: índice={expected}, actual={actual}."
        )
    return path, {"path": relative, "sha256": actual, "bytes": path.stat().st_size}


def _records(path: Path, label: str) -> list[dict[str, Any]]:
    payload = _json_file(path)
    records = payload.get("records")
    if not isinstance(records, list) or any(not isinstance(item, dict) for item in records):
        raise PlayerInventoryError(f"{label} debe contener una lista records de objetos: {path}")
    return records


def _empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _canonical_value(
    player_id: int,
    field: str,
    observations: list[dict[str, Any]],
) -> tuple[Any, dict[str, Any] | None]:
    values: dict[str, Any] = {}
    for observation in observations:
        value = observation["record"].get(field)
        if not _empty(value):
            values.setdefault(json.dumps(value, ensure_ascii=False, sort_keys=True), value)
    if not values:
        return None, None
    if len(values) == 1:
        return next(iter(values.values())), None
    evidence = [
        {
            "value": observation["record"].get(field),
            "source": observation["source_ref"],
        }
        for observation in observations
        if not _empty(observation["record"].get(field))
    ]
    return None, {"player_id": player_id, "field": field, "observations": evidence}


def _load_top_enrichment(
    group: str,
    root: Path,
    season: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    metadata_path = root / "metadata/capture.json"
    validation_path = root / "validation/results.json"
    players_path = root / "normalized/players.json"
    raw_path = root / "raw/source.html"
    for path in (metadata_path, validation_path, players_path, raw_path):
        if not path.is_file():
            raise PlayerInventoryError(f"Falta evidencia de la captura Destacados: {path}")
    metadata = _json_file(metadata_path)
    validation = _json_file(validation_path)
    players = _json_file(players_path)
    players_metadata = players.get("metadata", {})
    if (
        metadata.get("source") != "BDFutbol"
        or metadata.get("season") != season
        or metadata.get("group") != group
        or validation.get("valid") is not True
        or validation.get("issues") not in ([], None)
        or players_metadata.get("capture_id") != metadata.get("capture_id")
        or players_metadata.get("season") != season
        or players_metadata.get("group") != group
    ):
        raise PlayerInventoryError(f"La captura Destacados no valida temporada/grupo {season}/{group}.")
    raw_hash = _sha256(raw_path)
    expected_raw_hash = metadata.get("source_snapshot_sha256")
    if expected_raw_hash and raw_hash != expected_raw_hash:
        raise PlayerInventoryError(f"SHA-256 del HTML de Destacados incorrecto: {raw_path}")
    if players_metadata.get("source_snapshot_sha256") != raw_hash:
        raise PlayerInventoryError(f"players.json no refiere al HTML validado de Destacados: {players_path}")
    records = players.get("records")
    if not isinstance(records, list) or any(not isinstance(row, dict) for row in records):
        raise PlayerInventoryError(f"La captura Destacados no contiene records válidos: {players_path}")
    ids = [row.get("player_id") for row in records]
    if any(not isinstance(value, int) or value <= 0 for value in ids) or len(ids) != len(set(ids)):
        raise PlayerInventoryError(f"La captura Destacados contiene player_id inválidos o duplicados: {players_path}")
    files = []
    for path in (metadata_path, validation_path, players_path, raw_path):
        files.append({"path": path.relative_to(root).as_posix(), "sha256": _sha256(path), "bytes": path.stat().st_size})
    reference = {
        "source": "BDFutbol",
        "section": "top",
        "group": group,
        "season": season,
        "capture_id": metadata.get("capture_id"),
        "captured_at_utc": metadata.get("captured_at_utc"),
        "root": str(root.resolve()),
        "source_snapshot_sha256": raw_hash,
        "files": files,
        "record_count": len(records),
    }
    return records, reference


def build_player_inventory(
    published_index: Path,
    *,
    top_roots: Mapping[str, Path] | None = None,
    expected_profile_count: int | None = 40,
    expected_group_counts: Mapping[str, int] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Read published team captures, verify hashes, and build deterministic payloads.

    `players.json` includes unique IDs seen in rosters or transfer rows. Transfer-only
    people are explicitly marked and never turned into roster memberships.
    """
    index_path = published_index.expanduser().resolve()
    index = _json_file(index_path)
    season = index.get("season")
    profiles = index.get("profiles")
    if not isinstance(season, str) or not isinstance(profiles, dict):
        raise PlayerInventoryError("El índice publicado no contiene temporada y perfiles válidos.")
    if expected_profile_count is not None and len(profiles) != expected_profile_count:
        raise PlayerInventoryError(
            f"El índice incluye {len(profiles)} perfiles; se esperaban {expected_profile_count}."
        )

    expected_group_counts = dict(expected_group_counts or {"I": 20, "II": 20})
    team_sources: list[dict[str, Any]] = []
    player_observations: dict[int, list[dict[str, Any]]] = defaultdict(list)
    membership_rows: list[dict[str, Any]] = []
    stats_by_player: dict[int, list[dict[str, Any]]] = defaultdict(list)
    minutes_by_player: dict[int, list[dict[str, Any]]] = defaultdict(list)
    metrics_by_player: dict[int, list[dict[str, Any]]] = defaultdict(list)
    transfer_by_player: dict[int, list[dict[str, Any]]] = defaultdict(list)
    team_counts: dict[int, dict[str, Any]] = {}
    group_team_counts: Counter[str] = Counter()
    raw_player_count = 0
    stats_record_count = 0
    minutes_record_count = 0
    metrics_record_count = 0
    transfer_record_count = 0
    source_files_total = 0

    for team_id_text, profile in sorted(profiles.items(), key=lambda item: int(item[0])):
        try:
            team_id = int(team_id_text)
        except (TypeError, ValueError) as exc:
            raise PlayerInventoryError(f"team_id no numérico en índice: {team_id_text!r}") from exc
        if team_id <= 0 or not isinstance(profile, dict):
            raise PlayerInventoryError(f"Entrada inválida para team_id={team_id_text}.")
        capture_id = profile.get("capture_id")
        directory = profile.get("directory")
        if not isinstance(capture_id, str) or not isinstance(directory, str):
            raise PlayerInventoryError(f"Falta capture_id o directory para team_id={team_id}.")
        capture_dir = Path(directory).expanduser().resolve()
        if profile.get("publication_validation", {}).get("classification") != "complete":
            raise PlayerInventoryError(f"La captura publicada de team_id={team_id} no está completa.")
        if profile.get("publication_validation", {}).get("active_catalog_compatible") is not True:
            raise PlayerInventoryError(f"La captura de team_id={team_id} no es compatible con su catálogo.")

        checked: dict[str, dict[str, Any]] = {}
        payloads: dict[str, dict[str, Any]] = {}
        for relative in REQUIRED_CAPTURE_FILES:
            result = _checked_capture_file(capture_dir, profile, relative, required=True)
            assert result is not None
            path, file_ref = result
            checked[relative] = file_ref
            payloads[relative] = _json_file(path)
        optional: dict[str, list[dict[str, Any]]] = {}
        for relative in OPTIONAL_PLAYER_FILES:
            result = _checked_capture_file(capture_dir, profile, relative, required=False)
            if result is None:
                optional[relative] = []
                continue
            path, file_ref = result
            checked[relative] = file_ref
            optional[relative] = _records(path, relative)

        metadata = payloads["metadata/capture.json"]
        validation = payloads["validation/results.json"]
        identity_doc = payloads["normalized/team_identity.json"]
        player_doc = payloads["normalized/players.json"]
        membership_doc = payloads["normalized/memberships.json"]
        statistic_doc = payloads["normalized/player_statistics.json"]
        record_metadata = player_doc.get("metadata", {})
        if (
            metadata.get("source") != "BDFutbol"
            or metadata.get("season") != season
            or metadata.get("team_id") != team_id
            or metadata.get("group") not in {"I", "II"}
            or profile.get("publication_validation", {}).get("capture_id") != capture_id
            or metadata.get("capture_id") != capture_id
            or validation.get("valid") is not True
            or identity_doc.get("record", {}).get("team_id") != team_id
            or record_metadata.get("capture_id") != capture_id
            or record_metadata.get("team_id") != team_id
            or record_metadata.get("season") != season
            or record_metadata.get("group") != metadata.get("group")
        ):
            raise PlayerInventoryError(f"Metadatos o validación incoherentes para team_id={team_id}.")
        group = metadata["group"]
        identity = identity_doc.get("record", {})
        team_name = identity.get("name")
        if not isinstance(team_name, str) or not team_name.strip():
            raise PlayerInventoryError(f"Nombre de equipo ausente para team_id={team_id}.")
        group_team_counts[group] += 1
        source_base = {
            "team_id": team_id,
            "team_name": team_name,
            "group": group,
            "season": season,
            "capture_id": capture_id,
            "captured_at_utc": metadata.get("captured_at_utc"),
        }

        players = _records_from_document(player_doc, "normalized/players.json", capture_id)
        memberships = _records_from_document(membership_doc, "normalized/memberships.json", capture_id)
        stats = _records_from_document(statistic_doc, "normalized/player_statistics.json", capture_id)
        if player_doc.get("metadata", {}).get("team_id") != team_id:
            raise PlayerInventoryError(f"metadata.team_id incoherente en players.json de {team_id}.")
        if membership_doc.get("metadata", {}).get("capture_id") != capture_id:
            raise PlayerInventoryError(f"metadata.capture_id incoherente en memberships.json de {team_id}.")

        roster_by_id: dict[int, dict[str, Any]] = {}
        for index_in_file, record in enumerate(players):
            player_id = _player_id(record, f"players team_id={team_id}")
            if player_id in roster_by_id:
                raise PlayerInventoryError(f"player_id duplicado en plantilla team_id={team_id}: {player_id}.")
            roster_by_id[player_id] = record
            raw_player_count += 1
            ref = {**source_base, "path": "normalized/players.json", "sha256": checked["normalized/players.json"]["sha256"], "record_index": index_in_file}
            player_observations[player_id].append({"kind": "roster", "record": record, "source_ref": ref, **source_base})

        membership_ids: set[int] = set()
        for index_in_file, record in enumerate(memberships):
            player_id = _player_id(record, f"memberships team_id={team_id}")
            if player_id in membership_ids:
                raise PlayerInventoryError(f"Pertenencia duplicada player_id={player_id}, team_id={team_id}.")
            membership_ids.add(player_id)
            if player_id not in roster_by_id:
                raise PlayerInventoryError(f"Pertenencia sin identidad de plantilla: player_id={player_id}, team_id={team_id}.")
            if record.get("team_id") != team_id or record.get("season") != season or record.get("group") != group:
                raise PlayerInventoryError(f"Contexto de pertenencia incoherente para player_id={player_id}, team_id={team_id}.")
            membership_rows.append({
                **record,
                "team_name": team_name,
                "capture_id": capture_id,
                "captured_at_utc": metadata.get("captured_at_utc"),
                "source_ref": {
                    **source_base,
                    "path": "normalized/memberships.json",
                    "sha256": checked["normalized/memberships.json"]["sha256"],
                    "record_index": index_in_file,
                },
            })
        if membership_ids != set(roster_by_id):
            raise PlayerInventoryError(f"players/memberships no cubren el mismo conjunto en team_id={team_id}.")

        team_stats_ids: set[int] = set()
        for index_in_file, record in enumerate(stats):
            player_id = _player_id(record, f"player_statistics team_id={team_id}")
            if player_id in team_stats_ids or player_id not in roster_by_id:
                raise PlayerInventoryError(f"Estadística duplicada o fuera de plantilla: player_id={player_id}, team_id={team_id}.")
            team_stats_ids.add(player_id)
            if record.get("team_id") != team_id or record.get("season") != season or record.get("group") != group:
                raise PlayerInventoryError(f"Contexto estadístico incoherente para player_id={player_id}, team_id={team_id}.")
            ref = {**source_base, "path": "normalized/player_statistics.json", "sha256": checked["normalized/player_statistics.json"]["sha256"], "record_index": index_in_file}
            stats_by_player[player_id].append({"record": record, "source_ref": ref})
        stats_record_count += len(stats)

        for relative, target, key_name in (
            ("normalized/player_match_minutes.json", minutes_by_player, "minutes"),
            ("normalized/player_match_metrics.json", metrics_by_player, "metrics"),
        ):
            for index_in_file, record in enumerate(optional[relative]):
                player_id = _player_id(record, f"{key_name} team_id={team_id}")
                if player_id not in roster_by_id:
                    raise PlayerInventoryError(f"Dato por partido sin pertenencia de plantilla: player_id={player_id}, team_id={team_id}.")
                if record.get("team_id") != team_id or record.get("season") != season or record.get("group") != group:
                    raise PlayerInventoryError(f"Contexto de dato por partido incoherente para player_id={player_id}, team_id={team_id}.")
                ref = {**source_base, "path": relative, "sha256": checked[relative]["sha256"], "record_index": index_in_file}
                target[player_id].append({"record": record, "source_ref": ref})
        minutes_record_count += len(optional["normalized/player_match_minutes.json"])
        metrics_record_count += len(optional["normalized/player_match_metrics.json"])

        transfer_keys: Counter[tuple[int, str]] = Counter()
        for index_in_file, record in enumerate(optional["normalized/transfers.json"]):
            player_id = _player_id(record, f"transfers team_id={team_id}")
            direction = record.get("direction")
            if direction not in {"incoming", "outgoing"}:
                raise PlayerInventoryError(f"Dirección de traspaso inválida para player_id={player_id}, team_id={team_id}.")
            transfer_keys[(player_id, direction)] += 1
            if record.get("team_id") != team_id or record.get("season") != season or record.get("group") != group:
                raise PlayerInventoryError(f"Contexto de traspaso incoherente para player_id={player_id}, team_id={team_id}.")
            ref = {**source_base, "path": "normalized/transfers.json", "sha256": checked["normalized/transfers.json"]["sha256"], "record_index": index_in_file}
            player_observations[player_id].append({"kind": "transfer", "record": record, "source_ref": ref, **source_base})
            transfer_by_player[player_id].append({"record": record, "source_ref": ref})
        if any(count > 1 for count in transfer_keys.values()):
            raise PlayerInventoryError(f"El equipo {team_id} contiene movimientos duplicados por jugador y dirección.")
        transfer_record_count += len(optional["normalized/transfers.json"])
        source_files_total += len(checked)
        team_sources.append({
            **source_base,
            "directory": str(capture_dir),
            "files": [checked[name] for name in sorted(checked)],
            "indexed_file_count": len(profile.get("files_sha256", {})),
        })
        team_counts[team_id] = {
            **source_base,
            "player_records": len(players),
            "membership_records": len(memberships),
            "statistics_records": len(stats),
            "players_with_statistics": len(team_stats_ids),
            "match_minutes_records": len(optional["normalized/player_match_minutes.json"]),
            "match_metric_records": len(optional["normalized/player_match_metrics.json"]),
            "transfer_records": len(optional["normalized/transfers.json"]),
            "missing_profile_url_records": sum(not bool(row.get("profile_url")) for row in players),
            "missing_photo_records": sum(not bool(row.get("photo_url")) for row in players),
            "captured_at_utc": metadata.get("captured_at_utc"),
        }

    for group, expected in expected_group_counts.items():
        if group_team_counts[group] != expected:
            raise PlayerInventoryError(
                f"El catálogo tiene {group_team_counts[group]} equipos en Grupo {group}; se esperaban {expected}."
            )

    top_sources: list[dict[str, Any]] = []
    top_observations: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for group, root in sorted((top_roots or {}).items()):
        if group not in {"I", "II"}:
            raise PlayerInventoryError(f"Grupo inválido en enriquecimiento Destacados: {group}.")
        records, top_ref = _load_top_enrichment(group, Path(root).expanduser().resolve(), season)
        top_sources.append(top_ref)
        for index_in_file, record in enumerate(records):
            ref = {
                "source": "BDFutbol",
                "section": "top",
                "group": group,
                "season": season,
                "capture_id": top_ref["capture_id"],
                "captured_at_utc": top_ref["captured_at_utc"],
                "path": "normalized/players.json",
                "sha256": next(item["sha256"] for item in top_ref["files"] if item["path"] == "normalized/players.json"),
                "record_index": index_in_file,
            }
            top_observations[record["player_id"]].append({"record": record, "source_ref": ref, "group": group})

    all_ids = set(player_observations)
    top_unmatched_ids_by_group: dict[str, int] = {}
    for group, root in sorted((top_roots or {}).items()):
        candidates, _ = _load_top_enrichment(group, Path(root).expanduser().resolve(), season)
        top_unmatched_ids_by_group[group] = len({row["player_id"] for row in candidates} - all_ids)

    players: list[dict[str, Any]] = []
    identity_conflicts: list[dict[str, Any]] = []
    for player_id in sorted(all_ids):
        observations = player_observations[player_id]
        roster_observations = [row for row in observations if row["kind"] == "roster"]
        transfer_observations = [row for row in observations if row["kind"] == "transfer"]
        identity: dict[str, Any] = {"player_id": player_id}
        player_conflicts: list[dict[str, Any]] = []
        for field in PLAYER_IDENTITY_FIELDS:
            normalized_observations = []
            for observation in observations:
                raw = observation["record"]
                normalized_record = dict(raw)
                if observation["kind"] == "transfer":
                    normalized_record = {
                        **normalized_record,
                        "display_name": raw.get("player_display_name"),
                        "full_name": raw.get("player_full_name"),
                        "profile_url": raw.get("player_profile_url"),
                        "photo_url": raw.get("player_photo_url"),
                    }
                normalized_observations.append({**observation, "record": normalized_record})
            value, conflict = _canonical_value(player_id, field, normalized_observations)
            identity[field] = value
            if conflict:
                player_conflicts.append(conflict)
        # Roster profile codes and transfer-section position codes are distinct raw domains.
        identity["birth_date"] = _unique_roster_value(roster_observations, "birth_date", player_id, player_conflicts)
        identity["birthplace"] = _unique_roster_value(roster_observations, "birthplace", player_id, player_conflicts)
        identity["birthplace_province"] = _unique_roster_value(roster_observations, "birthplace_province", player_id, player_conflicts)
        identity["nationality"] = None
        identity["nationality_code"] = None
        identity["position_name"] = None
        identity["position_code"] = None
        identity["nationality_flag_url"] = _unique_roster_value(roster_observations, "nationality_flag_url", player_id, player_conflicts)
        identity["source_position_code"] = _unique_roster_value(roster_observations, "source_position_code", player_id, player_conflicts)
        identity["transfer_position_codes"] = sorted({
            str(observation["record"].get("source_position_code"))
            for observation in transfer_observations
            if not _empty(observation["record"].get("source_position_code"))
        })
        identity["verified_indicators"] = sorted({
            value
            for observation in roster_observations
            for value in observation["record"].get("verified_indicators", [])
            if isinstance(value, str)
        })
        identity["source_views"] = sorted({
            value
            for observation in roster_observations
            for value in observation["record"].get("source_views", [])
            if isinstance(value, str)
        })
        enrichment_rows = top_observations.get(player_id, [])
        nationality_values = {
            row["record"].get("nationality")
            for row in enrichment_rows
            if not _empty(row["record"].get("nationality"))
        }
        nationality_codes = {
            row["record"].get("nationality_code")
            for row in enrichment_rows
            if not _empty(row["record"].get("nationality_code"))
        }
        if len(nationality_values) == 1:
            identity["nationality"] = next(iter(nationality_values))
            identity["nationality_source_refs"] = [
                row["source_ref"] for row in enrichment_rows if not _empty(row["record"].get("nationality"))
            ]
        else:
            identity["nationality_source_refs"] = []
            if len(nationality_values) > 1:
                player_conflicts.append({
                    "player_id": player_id,
                    "field": "nationality",
                    "observations": [
                        {"value": row["record"].get("nationality"), "source": row["source_ref"]}
                        for row in enrichment_rows if not _empty(row["record"].get("nationality"))
                    ],
                })
        if len(nationality_codes) == 1:
            identity["nationality_code"] = next(iter(nationality_codes))
        elif len(nationality_codes) > 1:
            player_conflicts.append({
                "player_id": player_id,
                "field": "nationality_code",
                "observations": [
                    {"value": row["record"].get("nationality_code"), "source": row["source_ref"]}
                    for row in enrichment_rows if not _empty(row["record"].get("nationality_code"))
                ],
            })
        top_position_names = {
            row["record"].get("position_name")
            for row in enrichment_rows
            if not _empty(row["record"].get("position_name"))
        }
        top_position_codes = {
            row["record"].get("position_code")
            for row in enrichment_rows
            if not _empty(row["record"].get("position_code"))
        }
        if len(top_position_names) == 1:
            identity["position_name"] = next(iter(top_position_names))
        if len(top_position_codes) == 1:
            identity["position_code"] = next(iter(top_position_codes))
        identity["supplemental_top_observations"] = [
            {
                "source_ref": row["source_ref"],
                "nationality": row["record"].get("nationality"),
                "nationality_code": row["record"].get("nationality_code"),
                "position_name": row["record"].get("position_name"),
                "position_code": row["record"].get("position_code"),
                "age_years": row["record"].get("age_years"),
                "source_team_id": row["record"].get("team_id"),
                "source_team_name": row["record"].get("team_name"),
            }
            for row in enrichment_rows
        ]
        if player_conflicts:
            identity_conflicts.extend(player_conflicts)
        identity["identity_conflicts"] = player_conflicts
        membership_refs = [row for row in membership_rows if row["player_id"] == player_id]
        observed_team_groups: dict[tuple[int, str, str], set[str]] = defaultdict(set)
        for row in membership_refs:
            observed_team_groups[(row["team_id"], row["team_name"], row["group"])].add("membership")
        for row in transfer_observations:
            observed_team_groups[(row["team_id"], row["team_name"], row["group"])].add("transfer_reference")
        identity["team_associations"] = [
            {
                "team_id": team_id,
                "team_name": team_name,
                "group": group,
                "evidence_types": sorted(evidence_types),
            }
            for (team_id, team_name, group), evidence_types in sorted(observed_team_groups.items())
        ]
        identity["team_ids"] = sorted({row[0] for row in observed_team_groups})
        identity["groups"] = sorted({row[2] for row in observed_team_groups})
        identity["membership_count"] = len(membership_refs)
        identity["association_status"] = "roster_membership_observed" if membership_refs else "transfer_reference_only"
        identity["source_refs"] = sorted(
            {json.dumps(row["source_ref"], sort_keys=True): row["source_ref"] for row in observations}.values(),
            key=lambda item: (item["team_id"], item["path"], item["record_index"]),
        )
        identity["season_statistics"] = [
            {"record": row["record"], "source_ref": row["source_ref"]}
            for row in stats_by_player.get(player_id, [])
        ]
        identity["match_minutes"] = [
            {"record": row["record"], "source_ref": row["source_ref"]}
            for row in minutes_by_player.get(player_id, [])
        ]
        identity["match_metrics"] = [
            {"record": row["record"], "source_ref": row["source_ref"]}
            for row in metrics_by_player.get(player_id, [])
        ]
        identity["transfer_references"] = [
            {"record": row["record"], "source_ref": row["source_ref"]}
            for row in transfer_by_player.get(player_id, [])
        ]
        players.append(identity)

    roster_unique_ids = {row["player_id"] for row in players if row["association_status"] == "roster_membership_observed"}
    transfer_only_ids = {row["player_id"] for row in players if row["association_status"] == "transfer_reference_only"}
    multiple_teams = []
    membership_by_player: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in membership_rows:
        membership_by_player[row["player_id"]].append(row)
    for player_id, rows in sorted(membership_by_player.items()):
        distinct_teams = {row["team_id"] for row in rows}
        if len(distinct_teams) > 1:
            multiple_teams.append({
                "player_id": player_id,
                "display_name": next(
                    (row["record"].get("display_name") for row in player_observations[player_id] if row["kind"] == "roster"),
                    None,
                ),
                "memberships": [
                    {"team_id": row["team_id"], "team_name": row["team_name"], "group": row["group"]}
                    for row in sorted(rows, key=lambda item: (item["group"], item["team_id"]))
                ],
            })

    by_group: dict[str, Any] = {}
    for group in ("I", "II"):
        group_memberships = [row for row in membership_rows if row["group"] == group]
        group_players = {row["player_id"] for row in group_memberships}
        group_transfer_only = {
            player_id for player_id in transfer_only_ids
            if any(row["group"] == group for row in player_observations[player_id])
        }
        by_group[group] = {
            "teams": group_team_counts[group],
            "roster_records": sum(1 for row in membership_rows if row["group"] == group),
            "memberships": len(group_memberships),
            "unique_roster_players": len(group_players),
            "transfer_only_unique_players": len(group_transfer_only),
            "all_unique_related_players": len(group_players | group_transfer_only),
        }

    per_team = [team_counts[team_id] for team_id in sorted(team_counts)]
    profile_urls = sum(bool(row.get("profile_url")) for row in players)
    photos = sum(bool(row.get("photo_url")) for row in players)
    players_with_stats = {player_id for player_id, rows in stats_by_player.items() if rows}
    players_with_minutes = {player_id for player_id, rows in minutes_by_player.items() if rows}
    players_with_match_metrics = {player_id for player_id, rows in metrics_by_player.items() if rows}
    report = {
        "schema_version": 1,
        "season": season,
        "scope": "unique player IDs from 40 published team rosters plus verified transfer-section observations; transfer-only IDs are not memberships",
        "counts": {
            "teams": len(profiles),
            "roster_player_records": raw_player_count,
            "verified_membership_records": len(membership_rows),
            "unique_roster_player_ids": len(roster_unique_ids),
            "unique_transfer_only_player_ids": len(transfer_only_ids),
            "unique_transfer_related_player_ids": len(transfer_by_player),
            "unique_player_ids_in_inventory": len(players),
            "players_with_profile_url": profile_urls,
            "players_without_profile_url": len(players) - profile_urls,
            "players_with_photo_url": photos,
            "players_without_photo_url": len(players) - photos,
            "player_statistics_records": stats_record_count,
            "unique_players_with_player_statistics": len(players_with_stats),
            "players_with_match_minutes": len(players_with_minutes),
            "player_match_minutes_records": minutes_record_count,
            "players_with_match_metrics": len(players_with_match_metrics),
            "player_match_metric_records": metrics_record_count,
            "transfer_records": transfer_record_count,
            "players_with_multiple_roster_memberships": len(multiple_teams),
            "identity_conflicts": len(identity_conflicts),
            "players_with_identity_conflicts": len({item["player_id"] for item in identity_conflicts}),
            "top_player_ids_matched_by_player_id": len(set(top_observations) & all_ids),
        },
        "by_group": by_group,
        "players_with_multiple_roster_memberships": multiple_teams,
        "identity_conflicts": identity_conflicts,
        "transfer_only_player_ids": sorted(transfer_only_ids),
        "supplemental_top_unmatched_unique_ids_by_group": top_unmatched_ids_by_group,
        "per_team_coverage": per_team,
        "field_coverage": {
            field: sum(row.get(field) is not None and row.get(field) != "" for row in players)
            for field in (
                "display_name", "full_name", "profile_url", "photo_url", "birth_date",
                "age_years", "birthplace", "birthplace_province", "nationality",
                "nationality_code", "nationality_flag_url", "source_position_code",
                "position_name", "position_code",
            )
        },
        "data_semantics": [
            "A roster membership is evidence from the selected team-season capture, not proof of current employment.",
            "Transfer-only player IDs remain in the unique inventory with association_status=transfer_reference_only and no membership row.",
            "All joins use player_id; names are never used as identity keys.",
            "The team-profile source provides a nationality flag URL, not a nationality label. Nationality labels/codes are supplemented only from validated group Top captures and retain that older source timestamp.",
            "source_position_code from player roster and transfer section codes are kept in separate fields because the source uses distinct raw vocabularies.",
            "Season statistics and match-level follow rows preserve their source values, including zero and null.",
        ],
    }
    players_payload = {
        "schema_version": 1,
        "metadata": {
            "source": "BDFutbol team-profile captures",
            "season": season,
            "unique_roster_player_ids": len(roster_unique_ids),
            "unique_transfer_only_player_ids": len(transfer_only_ids),
            "unique_player_ids": len(players),
            "supplemental_top_captured_at_utc": {item["group"]: item["captured_at_utc"] for item in top_sources},
        },
        "records": players,
    }
    memberships_payload = {
        "schema_version": 1,
        "metadata": {"source": "BDFutbol team-profile captures", "season": season, "record_count": len(membership_rows)},
        "records": sorted(membership_rows, key=lambda row: (row["player_id"], row["team_id"])),
    }
    manifest = {
        "schema_version": 1,
        "season": season,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_index": {"path": str(index_path), "sha256": _sha256(index_path), "bytes": index_path.stat().st_size},
        "team_capture_count": len(team_sources),
        "verified_team_capture_files": source_files_total,
        "team_captures": team_sources,
        "supplemental_top_captures": top_sources,
        "output_file_hashes_exclude_manifest": True,
        "generation_policy": {
            "player_key": "player_id",
            "membership_key": ["player_id", "team_id", "season", "competition", "group"],
            "external_access_used": False,
            "browser_started": False,
        },
    }
    return players_payload, memberships_payload, report, manifest


def _records_from_document(document: dict[str, Any], label: str, capture_id: str) -> list[dict[str, Any]]:
    records = document.get("records")
    metadata = document.get("metadata", {})
    if (
        not isinstance(records, list)
        or any(not isinstance(item, dict) for item in records)
        or metadata.get("capture_id") != capture_id
    ):
        raise PlayerInventoryError(f"{label} tiene records o metadata.capture_id inválidos.")
    return records


def _player_id(record: dict[str, Any], context: str) -> int:
    value = record.get("player_id")
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise PlayerInventoryError(f"player_id inválido en {context}: {value!r}.")
    return value


def _unique_roster_value(
    observations: list[dict[str, Any]],
    field: str,
    player_id: int,
    conflicts: list[dict[str, Any]],
) -> Any:
    values: dict[str, Any] = {}
    for observation in observations:
        value = observation["record"].get(field)
        if not _empty(value):
            values.setdefault(json.dumps(value, ensure_ascii=False, sort_keys=True), value)
    if len(values) > 1:
        conflicts.append({
            "player_id": player_id,
            "field": field,
            "observations": [
                {"value": observation["record"].get(field), "source": observation["source_ref"]}
                for observation in observations if not _empty(observation["record"].get(field))
            ],
        })
        return None
    return next(iter(values.values())) if values else None


def write_inventory_atomic(
    output_dir: Path,
    players: dict[str, Any],
    memberships: dict[str, Any],
    report: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, str]:
    """Publish all four JSONs by atomically renaming a complete staging directory."""
    destination = output_dir.expanduser().resolve()
    if destination.exists():
        raise PlayerInventoryError(f"El destino ya existe; no se sobrescribirá: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    payloads = {
        "players.json": players,
        "memberships.json": memberships,
        "inventory_report.json": report,
    }
    stage = Path(tempfile.mkdtemp(prefix=f".{destination.name}.tmp-", dir=destination.parent))
    output_hashes: dict[str, str] = {}
    try:
        for filename, payload in payloads.items():
            body = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
            target = stage / filename
            with target.open("xb") as sink:
                sink.write(body)
                sink.flush()
                os.fsync(sink.fileno())
            output_hashes[filename] = hashlib.sha256(body).hexdigest()
        manifest["output_files"] = {
            filename: {"sha256": digest, "bytes": (stage / filename).stat().st_size}
            for filename, digest in sorted(output_hashes.items())
        }
        manifest_body = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        with (stage / "manifest.json").open("xb") as sink:
            sink.write(manifest_body)
            sink.flush()
            os.fsync(sink.fileno())
        os.rename(stage, destination)
    except Exception:
        if stage.exists():
            for child in stage.iterdir():
                child.unlink()
            stage.rmdir()
        raise
    return {**output_hashes, "manifest.json": hashlib.sha256(manifest_body).hexdigest()}
