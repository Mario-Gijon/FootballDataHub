"""Verify offline player sources once and expose a bounded in-memory index."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from football_data_hub_api.schemas import (
    PlayerDetailResponse,
    PlayerDirectoryMetadataResponse,
    PlayerDirectoryResponse,
    PlayerIndexRecordResponse,
    PlayerIndividualViewResponse,
    PlayerMatchMetricResponse,
    PlayerCompactTableResponse,
    PlayerSeasonStatisticResponse,
    PlayerTableCellResponse,
    PlayerTableColumnResponse,
    PlayerTableRowResponse,
    PlayerTeamAssociationResponse,
    PlayerTeamFilterResponse,
    PlayerTransferReferenceResponse,
)

PLAYER_INVENTORY_SCHEMA = "football_data_hub.player_inventory.v1"
PLAYER_COMPACT_SCHEMA = "football_data_hub.bdfutbol.player_compact_profile.v1"
PLAYER_COMPACT_GENERATION_SCHEMA = "football_data_hub.player_compact_generation.v1"
PLAYER_COMPACT_POINTER_SCHEMA = "football_data_hub.player_compact_current.v1"
PLAYER_VIEWS = ("profile", "statistics", "matches", "rivals")
_CONTEXT_FIELDS = (
    "season_raw", "team_name_raw", "country_raw", "division_raw",
    "competition_raw", "date_raw", "round_title_raw", "opponent_team_raw",
    "team_name", "opponent_team", "coach_name_raw", "player_display_name",
    "match_id", "source_kind", "player_team_raw", "player_team_side_raw",
    "season", "competition", "team_id", "group", "minutes",
)


class PlayerDatasetLoadError(ValueError):
    """Player inventory or compact generation failed provenance validation."""


@dataclass(frozen=True, slots=True)
class PlayerDirectoryBundle:
    metadata: PlayerDirectoryMetadataResponse
    players: tuple[dict[str, Any], ...]
    players_by_id: dict[int, dict[str, Any]]
    memberships_by_player: dict[int, tuple[dict[str, Any], ...]]
    teams: tuple[PlayerTeamFilterResponse, ...]
    compact_documents: dict[int, dict[str, Any]]
    etag: str

    def list_players(
        self,
        *,
        query: str = "",
        group: str | None = None,
        team_id: int | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> PlayerDirectoryResponse:
        normalized = _normalize(query)
        matches = []
        for player in self.players:
            groups = player["groups"]
            associations = player.get("team_associations", [])
            if group is not None and group not in groups:
                continue
            if team_id is not None and not any(
                item.get("team_id") == team_id for item in associations
            ):
                continue
            if normalized:
                text = _normalize(" ".join((
                    str(player.get("display_name") or ""),
                    str(player.get("full_name") or ""),
                    str(player.get("nationality") or ""),
                    str(player.get("position_name") or ""),
                    " ".join(
                        str(item.get("team_name") or "") for item in associations
                        if isinstance(item, dict)
                    ),
                )))
                if normalized not in text:
                    continue
            matches.append(player)
        start = (page - 1) * page_size
        results = [
            self._index_record(player)
            for player in matches[start : start + page_size]
        ]
        return PlayerDirectoryResponse(
            metadata=self.metadata,
            available_teams=list(self.teams),
            query=query,
            group=group,
            team_id=team_id,
            page=page,
            page_size=page_size,
            total=len(matches),
            players=results,
        )

    def detail(self, player_id: int) -> PlayerDetailResponse | None:
        player = self.players_by_id.get(player_id)
        if player is None:
            return None
        index_record = self._index_record(player)
        associations = index_record.team_associations
        membership_team = {
            (item["team_id"], item["group"]): item["team_name"]
            for item in self.memberships_by_player.get(player_id, ())
        }
        statistics = []
        for item in player.get("season_statistics", []):
            record = item.get("record", {})
            if not isinstance(record, dict):
                continue
            key = (record.get("team_id"), record.get("group"))
            if type(record.get("team_id")) is not int or record.get("group") not in {"I", "II"}:
                continue
            statistics.append(PlayerSeasonStatisticResponse(
                team_id=record.get("team_id"),
                team_name=membership_team.get(key, _association_name(associations, key)),
                group=record.get("group"),
                matches_played=record.get("matches_played"),
                starts=record.get("starts"),
                minutes_played=record.get("minutes_played"),
                goals=record.get("goals"),
                assists=record.get("assists"),
                yellow_cards=record.get("yellow_cards"),
                red_cards=record.get("red_cards"),
                source_view=record.get("source_view"),
            ))
        metrics = _player_metric_records(
            player.get("match_metrics", []), membership_team, associations
        )
        minutes = _player_metric_records(
            player.get("match_minutes", []), membership_team, associations
        )
        transfers = []
        for item in player.get("transfer_references", []):
            record = item.get("record", {})
            if not isinstance(record, dict):
                continue
            key = (record.get("team_id"), record.get("group"))
            if type(record.get("team_id")) is not int or record.get("group") not in {"I", "II"}:
                continue
            transfers.append(PlayerTransferReferenceResponse(
                team_id=record.get("team_id"),
                team_name=membership_team.get(key, _association_name(associations, key)),
                group=record.get("group"),
                direction=record.get("direction"),
                other_team_name=record.get("other_team_name"),
                other_team_id=record.get("other_team_id"),
                source_position_code=record.get("source_position_code"),
                age_years=record.get("age_years"),
            ))
        compact = self.compact_documents.get(player_id)
        views = _project_individual_views(compact) if compact else []
        warnings: list[str] = []
        if player.get("identity_conflicts"):
            warnings.append("El inventario conserva discrepancias de identidad; no se han resuelto por nombre.")
        if compact is None:
            warnings.append("La generación compacta publicada no incluye un perfil individual para este jugador; sus vistas no se interpretan como vacías.")
        elif compact.get("status") != "COMPLETE_BASE_VIEWS":
            warnings.append("La captura individual es parcial; las vistas ausentes no se interpretan como vacías.")
        if player.get("association_status") == "roster_membership_observed":
            warnings.append("La pertenencia se observó en capturas de la temporada; no certifica que siga vigente hoy.")
        return PlayerDetailResponse(
            metadata=self.metadata,
            player=index_record,
            birth_place=player.get("birthplace"),
            birthplace_province=player.get("birthplace_province"),
            nationality_flag_url=_safe_bdfutbol_url(player.get("nationality_flag_url")),
            verified_indicators=list(player.get("verified_indicators") or []),
            associations=associations,
            transfer_references=transfers,
            season_statistics=statistics,
            match_minutes=minutes,
            match_metrics=metrics,
            verified_individual_views=views,
            warnings=warnings,
        )

    def _index_record(self, player: dict[str, Any]) -> PlayerIndexRecordResponse:
        player_id = player["player_id"]
        full_compact = self.compact_documents.get(player_id)
        compact_status = full_compact.get("status") if full_compact else None
        if compact_status == "COMPLETE_BASE_VIEWS":
            profile_status = "four_views_verified"
        elif compact_status == "PARTIAL_BASE_VIEWS":
            profile_status = "partial_individual_views"
        else:
            profile_status = "inventory_only"
        return PlayerIndexRecordResponse(
            player_id=player_id,
            display_name=player.get("display_name") or player.get("full_name"),
            full_name=player.get("full_name"),
            profile_url=_player_profile_url(player.get("profile_url"), player_id),
            photo_url=_safe_bdfutbol_url(player.get("photo_url")),
            birth_date=player.get("birth_date"),
            age_years=player.get("age_years"),
            nationality=player.get("nationality"),
            position_name=player.get("position_name"),
            groups=list(player.get("groups") or []),
            association_status=player.get("association_status"),
            team_associations=_associations(player),
            profile_status=profile_status,
        )


def load_player_directory(
    *,
    inventory_root: Path,
    compact_root: Path,
    team_captures_root: Path,
    published_index_path: Path,
) -> PlayerDirectoryBundle:
    inventory_root = _regular_directory(inventory_root, "raíz de inventario")
    compact_root = _regular_directory(compact_root, "raíz compacta")
    team_captures_root = _regular_directory(team_captures_root, "capturas de equipos")
    manifest, _ = _read_json(inventory_root / "manifest.json", "manifest de inventario")
    if manifest.get("schema_version") != 1 or manifest.get("season") != "2026-27":
        raise PlayerDatasetLoadError("El manifest de inventario no corresponde a 2026/27.")
    _verify_file(published_index_path, manifest.get("source_index"), "índice publicado de equipos")

    files: dict[str, bytes] = {}
    for name in ("players.json", "memberships.json", "inventory_report.json"):
        path = inventory_root / name
        files[name] = _verify_file(path, manifest.get("output_files", {}).get(name), name)
    inventory = _decode_json(files["players.json"], "players.json")
    memberships = _decode_json(files["memberships.json"], "memberships.json")
    report = _decode_json(files["inventory_report.json"], "inventory_report.json")
    if (
        inventory.get("schema_version") != 1
        or inventory.get("metadata", {}).get("season") != "2026-27"
        or memberships.get("schema_version") != 1
        or report.get("season") != "2026-27"
        or manifest.get("team_capture_count") != 40
    ):
        raise PlayerDatasetLoadError("Los contratos del inventario y su manifest no coinciden.")
    _verify_team_capture_sources(manifest, team_captures_root)
    player_records = inventory.get("records")
    membership_records = memberships.get("records")
    if not isinstance(player_records, list) or not isinstance(membership_records, list):
        raise PlayerDatasetLoadError("El inventario no contiene registros de jugadores y pertenencias.")
    players_by_id: dict[int, dict[str, Any]] = {}
    for record in player_records:
        if not isinstance(record, dict) or type(record.get("player_id")) is not int:
            raise PlayerDatasetLoadError("El inventario contiene un jugador sin ID entero.")
        player_id = record["player_id"]
        if player_id <= 0 or player_id in players_by_id:
            raise PlayerDatasetLoadError(f"player_id duplicado o inválido: {player_id}")
        if record.get("association_status") not in {
            "roster_membership_observed", "transfer_reference_only"
        }:
            raise PlayerDatasetLoadError(f"Estado de asociación desconocido para player_id={player_id}.")
        _player_profile_url(record.get("profile_url"), player_id)
        players_by_id[player_id] = record
    if len(players_by_id) != inventory.get("metadata", {}).get("unique_player_ids"):
        raise PlayerDatasetLoadError("El recuento único no coincide con metadata.unique_player_ids.")

    memberships_by_player: dict[int, list[dict[str, Any]]] = {}
    membership_keys: set[tuple[int, int, str]] = set()
    team_names: dict[tuple[int, str], str] = {}
    for item in membership_records:
        if not isinstance(item, dict):
            raise PlayerDatasetLoadError("El inventario contiene una pertenencia mal formada.")
        player_id, team_id, group = item.get("player_id"), item.get("team_id"), item.get("group")
        key = (player_id, team_id, group)
        if (
            type(player_id) is not int or player_id not in players_by_id
            or type(team_id) is not int or team_id <= 0
            or group not in {"I", "II"}
            or item.get("season") != "2026-27"
            or not isinstance(item.get("team_name"), str)
            or key in membership_keys
        ):
            raise PlayerDatasetLoadError("Una pertenencia tiene identidad/contexto inválido o duplicado.")
        membership_keys.add(key)
        memberships_by_player.setdefault(player_id, []).append(item)
        team_names[(team_id, group)] = item["team_name"]
    for player_id, record in players_by_id.items():
        if int(record.get("membership_count") or 0) != len(memberships_by_player.get(player_id, [])):
            raise PlayerDatasetLoadError(f"El recuento de pertenencias no coincide para player_id={player_id}.")
        _validate_associations(record, membership_keys)

    compact_manifest, compact_docs = _load_compact_generation(
        compact_root, expected_inventory_sha=hashlib.sha256(files["players.json"]).hexdigest()
    )
    metadata = PlayerDirectoryMetadataResponse(
        season="2026-27",
        inventory_generated_at=manifest["generated_at_utc"],
        inventory_player_count=len(players_by_id),
        complete_individual_profile_count=sum(doc.get("status") == "COMPLETE_BASE_VIEWS" for doc in compact_docs.values()),
        partial_individual_profile_count=sum(doc.get("status") == "PARTIAL_BASE_VIEWS" for doc in compact_docs.values()),
        inventory_only_count=len(players_by_id) - len(compact_docs),
        roster_membership_count=sum(record.get("association_status") == "roster_membership_observed" for record in player_records),
        transfer_only_count=sum(record.get("association_status") == "transfer_reference_only" for record in player_records),
        compact_generation_id=compact_manifest.get("generation_id") if compact_manifest else None,
        compact_generated_at=compact_manifest.get("generated_at_utc") if compact_manifest else None,
        inventory_sha256=hashlib.sha256(files["players.json"]).hexdigest(),
    )
    teams = tuple(
        PlayerTeamFilterResponse(team_id=team_id, team_name=name, group=group)
        for (team_id, group), name in sorted(team_names.items(), key=lambda item: (item[0][1], item[1].casefold(), item[0][0]))
    )
    ordered = tuple(sorted(
        players_by_id.values(),
        key=lambda player: (
            _normalize(str(player.get("display_name") or player.get("full_name") or "")),
            player["player_id"],
        ),
    ))
    representation = json.dumps({
        "inventory_sha256": metadata.inventory_sha256,
        "compact_generation_id": metadata.compact_generation_id,
        "compact_generated_at": metadata.compact_generated_at.isoformat() if metadata.compact_generated_at else None,
    }, sort_keys=True, separators=(",", ":")).encode()
    etag = f'"players-v1-{hashlib.sha256(representation).hexdigest()[:24]}"'
    return PlayerDirectoryBundle(
        metadata=metadata,
        players=ordered,
        players_by_id=players_by_id,
        memberships_by_player={key: tuple(value) for key, value in memberships_by_player.items()},
        teams=teams,
        compact_documents=compact_docs,
        etag=etag,
    )


def _verify_team_capture_sources(manifest: dict[str, Any], capture_root: Path) -> None:
    captures = manifest.get("team_captures")
    if not isinstance(captures, list) or len(captures) != 40:
        raise PlayerDatasetLoadError("El manifest no declara las 40 capturas de equipos.")
    identities: set[tuple[str, int]] = set()
    groups = {"I": 0, "II": 0}
    files_verified = 0
    for capture in captures:
        if not isinstance(capture, dict):
            raise PlayerDatasetLoadError("Referencia de captura de equipo mal formada.")
        group = capture.get("group")
        team_id = capture.get("team_id")
        capture_id = capture.get("capture_id")
        identity = (group, team_id)
        if (
            group not in groups or type(team_id) is not int or team_id <= 0
            or identity in identities or capture.get("season") != "2026-27"
            or not isinstance(capture_id, str) or not re.fullmatch(r"[0-9TZ.\-a-f]+", capture_id)
        ):
            raise PlayerDatasetLoadError("Identidad de captura de equipo inválida o duplicada.")
        identities.add(identity)
        groups[group] += 1
        base = _safe_child(capture_root, f"2026-27/{team_id}/{capture_id}")
        if not isinstance(capture.get("files"), list):
            raise PlayerDatasetLoadError("La captura de equipo no lista sus archivos fuente.")
        for spec in capture["files"]:
            rel = spec.get("path") if isinstance(spec, dict) else None
            if not isinstance(rel, str):
                raise PlayerDatasetLoadError("Referencia de archivo de equipo inválida.")
            path = _safe_child(base, rel)
            _verify_file(path, spec, f"captura {capture_id}/{rel}")
            files_verified += 1
    if groups != {"I": 20, "II": 20} or files_verified != manifest.get("verified_team_capture_files"):
        raise PlayerDatasetLoadError("La cobertura de capturas de equipo no coincide con el manifest.")


def _load_compact_generation(
    compact_root: Path, *, expected_inventory_sha: str
) -> tuple[dict[str, Any] | None, dict[int, dict[str, Any]]]:
    pointer_path = compact_root / "current.json"
    if not pointer_path.is_file():
        return None, {}
    pointer, pointer_raw = _read_json(pointer_path, "puntero compacto")
    generation_id = pointer.get("generation_id")
    if (
        pointer.get("schema_version") != PLAYER_COMPACT_POINTER_SCHEMA
        or not isinstance(generation_id, str)
        or not re.fullmatch(r"[0-9]{8}T[0-9]{6}\.[0-9]{6}Z-[0-9a-f]{8}", generation_id)
        or pointer.get("manifest_path") != f"generations/{generation_id}/manifest.json"
    ):
        raise PlayerDatasetLoadError("El puntero de compactos tiene contrato o ruta inválidos.")
    generation_root = _safe_child(compact_root, f"generations/{generation_id}")
    manifest_path = generation_root / "manifest.json"
    raw = manifest_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != pointer.get("manifest_sha256"):
        raise PlayerDatasetLoadError("El hash del manifest compacto no coincide con current.json.")
    manifest = _decode_json(raw, "manifest compacto")
    if (
        manifest.get("schema_version") != PLAYER_COMPACT_GENERATION_SCHEMA
        or manifest.get("generation_id") != generation_id
        or manifest.get("season") != "2026-27"
        or manifest.get("inventory_sha256") != expected_inventory_sha
        or not isinstance(manifest.get("entries"), list)
        or manifest.get("player_count") != len(manifest["entries"])
    ):
        raise PlayerDatasetLoadError("La generación compacta no corresponde al inventario actual.")
    docs: dict[int, dict[str, Any]] = {}
    for entry in manifest["entries"]:
        if not isinstance(entry, dict):
            raise PlayerDatasetLoadError("Entrada de generación compacta mal formada.")
        player_id = entry.get("player_id")
        status = entry.get("status")
        if type(player_id) is not int or player_id <= 0 or player_id in docs:
            raise PlayerDatasetLoadError("player_id compacto inválido o duplicado.")
        if status not in {"COMPLETE_BASE_VIEWS", "PARTIAL_BASE_VIEWS"}:
            raise PlayerDatasetLoadError(f"Estado compacto no reconocido para player_id={player_id}.")
        path = _safe_child(generation_root, entry.get("path", ""))
        compressed = _verify_file(path, entry, f"compacto player_id={player_id}")
        if entry.get("compression") != "gzip":
            raise PlayerDatasetLoadError(f"Compresión compacta inesperada para player_id={player_id}.")
        try:
            document = _decode_json(gzip.decompress(compressed), f"compacto player_id={player_id}")
        except (OSError, EOFError) as exc:
            raise PlayerDatasetLoadError(f"El compacto gzip no se puede leer para player_id={player_id}.") from exc
        views = document.get("views")
        if (
            document.get("schema_version") != PLAYER_COMPACT_SCHEMA
            or document.get("player_id") != player_id
            or document.get("status") != status
            or document.get("season_context") != "2026-27"
            or not isinstance(views, dict)
            or not set(views).issubset(PLAYER_VIEWS)
        ):
            raise PlayerDatasetLoadError(f"Identidad o estructura compacta inválida para player_id={player_id}.")
        if status == "COMPLETE_BASE_VIEWS" and set(views) != set(PLAYER_VIEWS):
            raise PlayerDatasetLoadError(f"El compacto completo carece de una vista de player_id={player_id}.")
        docs[player_id] = document
    if sum(doc.get("status") == "COMPLETE_BASE_VIEWS" for doc in docs.values()) != manifest.get("complete_player_count"):
        raise PlayerDatasetLoadError("El recuento de compactos completos no coincide con el manifest.")
    return manifest, docs


def _project_individual_views(document: dict[str, Any]) -> list[PlayerIndividualViewResponse]:
    result = []
    sources = document.get("view_sources", {})
    views = document.get("views", {})
    for view in PLAYER_VIEWS:
        payload = views.get(view)
        source = sources.get(view)
        if not isinstance(payload, dict) or not isinstance(source, dict):
            continue
        source_url = _safe_bdfutbol_url(source.get("requested_url"))
        if source_url is None:
            continue
        tables_source: list[dict[str, Any]] = []
        if view == "profile":
            tables_source.extend(payload.get("career_tables", []))
            tables_source.extend(payload.get("career_totals_tables", []))
        elif view == "statistics":
            tables_source.extend(payload.get("statistics_tables", []))
        elif view == "rivals":
            tables_source.extend(payload.get("rival_tables", []))
        coverage = payload.get("coverage")
        scope_note = "Datos estructurados de la captura individual."
        if view == "matches":
            scope_note = (
                "Registros estructurados de la vista capturada; exhaustividad: "
                f"{payload.get('exhaustiveness_status') or 'no determinada'}."
            )
        elif isinstance(coverage, dict):
            scope_note = str(coverage.get("data_scope") or coverage.get("parse_status") or scope_note)
        result.append(PlayerIndividualViewResponse(
            view=view,
            source_url=source_url,
            captured_at=source.get("captured_at_utc"),
            source_sha256=source.get("html_sha256"),
            scope_note=scope_note,
            tables=[_project_table(table) for table in tables_source if isinstance(table, dict)],
            historical_matches=[
                _project_historical_match(item)
                for item in payload.get("individual_matches", [])
                if isinstance(item, dict)
            ] if view == "matches" else [],
        ))
    return result


def _project_table(table: dict[str, Any]) -> PlayerCompactTableResponse:
    columns_source = table.get("columns")
    columns = []
    if isinstance(columns_source, list):
        for index, column in enumerate(columns_source):
            if not isinstance(column, dict):
                continue
            label = column.get("header_original") or column.get("header_title_raw") or column.get("data_colid_raw")
            if not isinstance(label, str) or not label.strip():
                label = f"Campo sin rótulo ({index + 1})"
            columns.append(PlayerTableColumnResponse(
                label=label.strip(),
                title=column.get("header_title_raw") if isinstance(column.get("header_title_raw"), str) else None,
                hidden_in_source=column.get("hidden_by_inline_style") is True,
            ))
    rows = []
    for record in table.get("records", []):
        if not isinstance(record, dict):
            continue
        context = {
            key: record[key] for key in _CONTEXT_FIELDS
            if key in record and (
                record[key] is None or isinstance(record[key], (str, int, float, bool))
            )
        }
        cells = []
        for cell in record.get("column_values", []):
            if not isinstance(cell, list):
                continue
            raw = cell[0] if len(cell) > 0 else None
            normalized = cell[1] if len(cell) > 1 and type(cell[1]) is int else None
            status = cell[2] if len(cell) > 2 and isinstance(cell[2], str) else None
            cells.append(PlayerTableCellResponse(
                raw_value=raw if raw is None or isinstance(raw, (str, int, float, bool)) else str(raw),
                normalized_integer=normalized,
                value_status=status,
            ))
        rows.append(PlayerTableRowResponse(context=context, cells=cells))
    return PlayerCompactTableResponse(
        table_role=str(table.get("table_role") or "Tabla de BDFutbol"),
        source_table_index=table.get("source_table_index") if type(table.get("source_table_index")) is int else None,
        columns=columns,
        rows=rows,
    )


def _project_historical_match(item: dict[str, Any]) -> dict[str, Any]:
    match_id = item.get("match_id")
    match_url = _safe_bdfutbol_url(item.get("match_url"))
    if not isinstance(match_id, str):
        match_id = str(match_id or "")
    return {
        "match_id": str(match_id) if match_id is not None else None,
        "match_url": match_url,
        "date": item.get("date"),
        "date_raw": item.get("date_raw"),
        "season": item.get("season_raw"),
        "competition": item.get("competition_raw"),
        "round_label": item.get("round_title_raw"),
        "player_team": item.get("player_team_raw"),
        "opponent_team": item.get("opponent_team_raw"),
        "side": item.get("player_team_side_raw"),
        "minutes": item.get("minutes") if type(item.get("minutes")) is int else None,
        "match_state": item.get("match_state"),
        "appearance_status": item.get("player_appearance_status"),
    }


def _player_metric_records(
    source: Any,
    membership_team: dict[tuple[int, str], str],
    associations: list[PlayerTeamAssociationResponse],
) -> list[PlayerMatchMetricResponse]:
    result = []
    for item in source if isinstance(source, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("record"), dict):
            continue
        record = item["record"]
        if (
            type(record.get("value")) is not int or record["value"] < 0
            or type(record.get("team_id")) is not int or record.get("group") not in {"I", "II"}
            or type(record.get("matchday")) is not int or not 1 <= record["matchday"] <= 38
        ):
            continue
        key = (record.get("team_id"), record.get("group"))
        source_ref = item.get("source_ref") if isinstance(item.get("source_ref"), dict) else {}
        result.append(PlayerMatchMetricResponse(
            team_id=record.get("team_id"),
            team_name=membership_team.get(key, _association_name(associations, key)),
            group=record.get("group"),
            match_id=str(record["match_id"]) if record.get("match_id") is not None else None,
            matchday=record.get("matchday"),
            metric=record.get("metric"),
            value=record["value"],
            raw_value=str(record["raw_value"]) if record.get("raw_value") is not None else None,
            source_state=record.get("source_state"),
            captured_at=source_ref.get("captured_at_utc"),
        ))
    return result


def _associations(player: dict[str, Any]) -> list[PlayerTeamAssociationResponse]:
    result = []
    for item in player.get("team_associations", []):
        if not isinstance(item, dict):
            continue
        result.append(PlayerTeamAssociationResponse(
            team_id=item.get("team_id"),
            team_name=item.get("team_name"),
            group=item.get("group"),
            evidence_types=item.get("evidence_types", []),
        ))
    return result


def _validate_associations(player: dict[str, Any], membership_keys: set[tuple[int, int, str]]) -> None:
    transfer_keys = set()
    for item in player.get("transfer_references", []):
        record = item.get("record", {}) if isinstance(item, dict) else {}
        if isinstance(record, dict):
            transfer_keys.add((record.get("team_id"), record.get("group")))
    associations = player.get("team_associations")
    if not isinstance(associations, list):
        raise PlayerDatasetLoadError(f"Faltan las asociaciones de player_id={player['player_id']}.")
    seen: set[tuple[int, str]] = set()
    for association in associations:
        if not isinstance(association, dict):
            raise PlayerDatasetLoadError("Asociación de equipo mal formada.")
        team_id, group = association.get("team_id"), association.get("group")
        key = (team_id, group)
        evidence = association.get("evidence_types")
        if (
            type(team_id) is not int or team_id <= 0 or group not in {"I", "II"}
            or not isinstance(association.get("team_name"), str)
            or not isinstance(evidence, list) or not evidence
            or any(value not in {"membership", "transfer_reference"} for value in evidence)
            or key in seen
        ):
            raise PlayerDatasetLoadError(f"Asociación inválida para player_id={player['player_id']}.")
        seen.add(key)
        if "membership" in evidence and (player["player_id"], team_id, group) not in membership_keys:
            raise PlayerDatasetLoadError("La pertenencia asociada no existe en memberships.json.")
        if "transfer_reference" in evidence and key not in transfer_keys:
            raise PlayerDatasetLoadError("La referencia de traspaso asociada no existe en el inventario.")
def _association_name(
    associations: list[PlayerTeamAssociationResponse], key: tuple[Any, Any]
) -> str | None:
    for item in associations:
        if (item.team_id, item.group) == key:
            return item.team_name
    return None


def _verify_file(path: Path, spec: Any, label: str) -> bytes:
    if not isinstance(spec, dict) or path.is_symlink() or not path.is_file():
        raise PlayerDatasetLoadError(f"Archivo de procedencia ausente o inválido: {label}.")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PlayerDatasetLoadError(f"No se puede leer el archivo de procedencia: {label}.") from exc
    if (
        hashlib.sha256(raw).hexdigest() != spec.get("sha256")
        or type(spec.get("bytes")) is not int
        or len(raw) != spec["bytes"]
    ):
        raise PlayerDatasetLoadError(f"SHA-256 o tamaño no coincide para {label}.")
    return raw


def _safe_child(root: Path, relative: str) -> Path:
    if not isinstance(relative, str):
        raise PlayerDatasetLoadError("Ruta relativa de datos inválida.")
    rel = PurePosixPath(relative)
    if rel.is_absolute() or not rel.parts or any(part in {"", ".", ".."} for part in rel.parts) or "\\" in relative:
        raise PlayerDatasetLoadError("Ruta relativa de datos no segura.")
    current = root
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise PlayerDatasetLoadError("La ruta de datos contiene un symlink.")
    try:
        current.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise PlayerDatasetLoadError("La ruta de datos escapa de la raíz configurada.") from exc
    return current


def _regular_directory(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve(strict=True)
    if not resolved.is_dir():
        raise PlayerDatasetLoadError(f"No existe el directorio configurado para {label}.")
    return resolved


def _read_json(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PlayerDatasetLoadError(f"No se puede leer JSON válido: {label}.") from exc
    if not isinstance(value, dict):
        raise PlayerDatasetLoadError(f"Se esperaba un objeto JSON: {label}.")
    return value, raw


def _decode_json(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PlayerDatasetLoadError(f"JSON inválido en {label}.") from exc
    if not isinstance(value, dict):
        raise PlayerDatasetLoadError(f"Se esperaba un objeto JSON en {label}.")
    return value


def _normalize(value: str) -> str:
    import unicodedata

    return " ".join(unicodedata.normalize("NFD", value.casefold()).encode("ascii", "ignore").decode().split())


def _player_profile_url(value: Any, player_id: int) -> str | None:
    if value is None:
        return None
    url = _safe_bdfutbol_url(value)
    if url is None:
        raise PlayerDatasetLoadError(f"URL de perfil no válida para player_id={player_id}.")
    parsed = urlsplit(url)
    if not re.search(rf"(?:^|/)j/j{player_id}\.html$", parsed.path):
        raise PlayerDatasetLoadError(f"La URL no corresponde a player_id={player_id}.")
    return url


def _safe_bdfutbol_url(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname not in {"www.bdfutbol.com", "bdfutbol.com"} or parsed.username or parsed.password:
        return None
    return value
