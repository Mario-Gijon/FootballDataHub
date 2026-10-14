"""Versioned JSON exports for recovered player-page snapshots."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .capture_store import PlayerCaptureStore
from .html_parser import PLAYER_PARSER_VERSION, PLAYER_SCHEMA_VERSION
from .parsers import PlayerCaptureParseError, parse_snapshot, player_page_to_dict


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _atomic_json(path: Path, value: dict[str, Any]) -> bytes:
    raw = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return raw


def _counts(page: Any) -> dict[str, int | str]:
    if page.view == "profile":
        return {"career_rows": len(page.career_rows), "total_rows": len(page.career_totals)}
    if page.view == "statistics":
        return {"statistics_rows": len(page.statistics_rows)}
    if page.view == "matches":
        return {
            "summary_rows": len(page.summary_rows),
            "individual_matches": len(page.individual_matches),
            "individual_matches_source": page.individual_matches_source,
            "window_p_parse_status": page.window_p_parse_status,
            "window_p_record_count": page.window_p_record_count,
            "detail_coverage": page.detail_coverage,
            "exhaustiveness_status": page.exhaustiveness_status,
        }
    return {
        "rival_records": len(page.rival_records),
        "rival_kind_counts": dict(
            (kind, sum(row.get("rival_kind") == kind for row in page.rival_records))
            for kind in sorted({row.get("rival_kind") for row in page.rival_records})
        ),
    }


_MATCH_COMPARISON_FIELDS = (
    "date", "home_team_raw", "away_team_raw", "home_goals", "away_goals",
    "competition_raw", "round_raw", "player_team_side_raw",
)


def _deduplicate_match_sources(sources: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    grouped: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    unkeyed: list[dict[str, Any]] = []
    for source in sources:
        record = source["record"]
        match_id = record.get("match_id")
        if match_id in (None, ""):
            unkeyed.append(source)
        else:
            grouped[(int(record["player_id"]), str(match_id))].append(source)

    output: list[dict[str, Any]] = []
    duplicate_count = 0
    conflict_rows: list[dict[str, Any]] = []
    for (player_id, match_id), records in sorted(grouped.items()):
        records.sort(key=lambda item: (
            item["source"].get("snapshot_kind") != "BASE_VIEW",
            item["record"].get("source_kind") != "WINDOW_P",
            str(item["source"].get("captured_at_utc") or ""),
        ))
        canonical = records[0]["record"]
        conflicts = []
        for field in _MATCH_COMPARISON_FIELDS:
            observed: list[Any] = []
            for item in records:
                value = item["record"].get(field)
                if value is not None and value not in observed:
                    observed.append(value)
            if len(observed) > 1:
                conflicts.append({"field": field, "values": observed})
        if conflicts:
            conflict_rows.append({"player_id": player_id, "match_id": match_id, "fields": conflicts})
        duplicate_count += max(0, len(records) - 1)
        output.append({
            "player_id": player_id,
            "match_id": match_id,
            "record": canonical,
            "sources": [item["source"] for item in records],
            "source_record_count": len(records),
            "field_conflicts": conflicts,
        })

    for index, item in enumerate(unkeyed):
        record = item["record"]
        output.append({
            "player_id": record.get("player_id"),
            "match_id": None,
            "unkeyed_record_index": index,
            "record": record,
            "sources": [item["source"]],
            "source_record_count": 1,
            "field_conflicts": [],
        })
    output.sort(key=lambda item: (
        int(item["player_id"] or 0),
        str(item.get("match_id") or f"~{item.get('unkeyed_record_index', 0)}"),
    ))
    return output, {
        "source_record_count": len(sources),
        "unique_player_match_ids": len(grouped),
        "records_without_match_id": len(unkeyed),
        "duplicate_records_across_snapshots": duplicate_count,
        "conflicting_player_match_ids": len(conflict_rows),
        "conflicts": conflict_rows,
    }


def build_player_capture_export(
    *,
    capture_dir: Path,
    inventory_path: Path,
    derivation_id: str | None = None,
) -> dict[str, Any]:
    """Parse all immutable raw records; keep failures separate from valid data."""
    capture_dir = capture_dir.expanduser().resolve()
    manifest_path = capture_dir / "manifest.json"
    if not manifest_path.is_file():
        raise PlayerCaptureParseError(f"Falta el manifiesto del run: {capture_dir}")
    store = PlayerCaptureStore(capture_dir.parent, capture_id=capture_dir.name)
    inventory_path = inventory_path.expanduser().resolve()
    inventory_raw = inventory_path.read_bytes()
    inventory = json.loads(inventory_raw)
    inventory_metadata = inventory.get("metadata", {})
    store.record_inventory_source({
        "path": str(inventory_path),
        "sha256": hashlib.sha256(inventory_raw).hexdigest(),
        "schema_version": inventory.get("schema_version"),
        "season": inventory_metadata.get("season", "2026-27"),
        "source": "PLAYER-01A published offline player inventory",
    })
    store.reconcile_navigation_ledger()
    manifest_raw = manifest_path.read_bytes()
    manifest = json.loads(manifest_raw)
    if manifest.get("status") != "complete":
        raise PlayerCaptureParseError("El run no está marcado como complete; se conserva para reanudación")
    player_records = {
        item["player_id"]: item
        for item in inventory.get("records", [])
        if isinstance(item, dict) and isinstance(item.get("player_id"), int)
    }
    capture_manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    derived_at = _utc_now()
    suffix = uuid4().hex[:8]
    derivation_id = derivation_id or (
        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')}"
        f"-{PLAYER_PARSER_VERSION}-{capture_manifest_hash[:8]}-{suffix}"
    )
    derivation_dir = capture_dir / "normalized" / "derivations" / derivation_id
    derivation_dir.mkdir(parents=True, exist_ok=False)
    validation_dir = derivation_dir / "validation"

    results: list[dict[str, Any]] = []
    grouped: dict[int, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: {"base_views_parsed": 0, "variants_parsed": 0})
    )
    parsed_count = 0
    match_sources: list[dict[str, Any]] = []
    for record in manifest.get("snapshots", []):
        player_id = record.get("player_id")
        inventory_player = player_records.get(player_id)
        if inventory_player is None:
            results.append({
                **record,
                "parse_status": "ERROR",
                "error_type": "InventoryIdentityMissing",
                "error": "El ID no aparece en el inventario publicado",
            })
            continue
        names = tuple(
            value for value in (
                str(inventory_player.get("display_name") or "").strip(),
                str(inventory_player.get("full_name") or "").strip(),
            ) if value
        )
        try:
            page = parse_snapshot(
                capture_dir,
                record,
                expected_player_id=player_id,
                expected_names=names,
            )
            normalized = player_page_to_dict(page)
            destination = (
                derivation_dir
                / f"j{player_id}"
                / str(record["view"])
                / f"{record['snapshot_id']}.json"
            )
            normalized_bytes = _atomic_json(destination, normalized)
            digest = hashlib.sha256(normalized_bytes).hexdigest()
            parsed_count += 1
            if page.view == "matches":
                for record_index, match_record in enumerate(page.individual_matches):
                    match_sources.append({
                        "record": match_record,
                        "source": {
                            "capture_id": capture_dir.name,
                            "snapshot_id": record.get("snapshot_id"),
                            "snapshot_kind": record.get("snapshot_kind"),
                            "requested_url": record.get("requested_url"),
                            "filter_parameters": record.get("filter_parameters", {}),
                            "captured_at_utc": record.get("captured_at_utc"),
                            "html_sha256": record.get("html_sha256"),
                            "rows_source": page.individual_matches_source,
                            "record_index": match_record.get("source_record_index", record_index),
                        },
                    })
            key = "base_views_parsed" if record.get("snapshot_kind") == "BASE_VIEW" else "variants_parsed"
            grouped[player_id][record["view"]][key] += 1
            results.append({
                **record,
                "parse_status": "PARSED",
                "normalized_path": destination.relative_to(derivation_dir).as_posix(),
                "normalized_sha256": digest,
                "row_counts": _counts(page),
                "coverage": page.coverage,
            })
        except (PlayerCaptureParseError, OSError, ValueError, TypeError) as exc:
            results.append({
                **record,
                "parse_status": "ERROR",
                "error_type": type(exc).__name__,
                "error": str(exc),
            })

    error_count = sum(item["parse_status"] != "PARSED" for item in results)
    deduplicated_matches, match_deduplication = _deduplicate_match_sources(match_sources)
    matches_document = {
        "schema_version": "football_data_hub.bdfutbol.player_individual_matches.v1",
        "capture_id": capture_dir.name,
        "derivation_id": derivation_id,
        "derived_at_utc": derived_at,
        "source_manifest_sha256": capture_manifest_hash,
        "parser_version": PLAYER_PARSER_VERSION,
        "completeness_status": "SNAPSHOTS_ONLY_NOT_CERTIFIED_COMPLETE",
        "deduplication": match_deduplication,
        "records": deduplicated_matches,
    }
    _atomic_json(derivation_dir / "individual_matches.json", matches_document)
    per_player = [
        {
            "player_id": player_id,
            "display_name": player_records.get(player_id, {}).get("display_name"),
            "views": {view: dict(counts) for view, counts in views.items()},
        }
        for player_id, views in sorted(grouped.items())
    ]
    validation = {
        "schema_version": "football_data_hub.bdfutbol.player_capture_validation.v1",
        "capture_id": capture_dir.name,
        "derivation_id": derivation_id,
        "derived_at_utc": derived_at,
        "source_manifest_sha256": capture_manifest_hash,
        "parser_version": PLAYER_PARSER_VERSION,
        "expected_player_schema": PLAYER_SCHEMA_VERSION,
        "snapshot_count": len(results),
        "parsed_count": parsed_count,
        "error_count": error_count,
        "individual_matches": match_deduplication,
        "status": "valid" if error_count == 0 else "partial",
        "players": per_player,
        "snapshots": results,
    }
    _atomic_json(validation_dir / "results.json", validation)
    export_manifest = {
        "schema_version": "football_data_hub.bdfutbol.player_normalized_export.v1",
        "capture_id": capture_dir.name,
        "derivation_id": derivation_id,
        "derived_at_utc": derived_at,
        "source_manifest_sha256": capture_manifest_hash,
        "parser_version": PLAYER_PARSER_VERSION,
        "snapshot_count": len(results),
        "parsed_count": parsed_count,
        "error_count": error_count,
        "individual_matches_path": "individual_matches.json",
        "individual_match_record_count": len(deduplicated_matches),
        "individual_match_source_record_count": len(match_sources),
        "individual_match_conflict_count": match_deduplication["conflicting_player_match_ids"],
        "status": validation["status"],
        "validation_path": "validation/results.json",
    }
    _atomic_json(derivation_dir / "manifest.json", export_manifest)
    return {
        **export_manifest,
        "derivation_dir": str(derivation_dir),
        "navigation_count_total": manifest.get("navigation_count_total"),
        "successful_navigation_count": manifest.get("successful_navigation_count"),
        "non_valid_navigation_count": manifest.get("non_valid_navigation_count"),
    }
