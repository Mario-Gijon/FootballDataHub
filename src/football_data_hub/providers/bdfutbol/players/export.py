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
            "detail_coverage": page.detail_coverage,
        }
    return {
        "rival_records": len(page.rival_records),
        "rival_kind_counts": dict(
            (kind, sum(row.get("rival_kind") == kind for row in page.rival_records))
            for kind in sorted({row.get("rival_kind") for row in page.rival_records})
        ),
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
    store.reconcile_navigation_ledger(notes=[
        "La primera validación de Rivales de j23751 fue INVALID_CONTENT por exigir el nombre corto en el título; la página HTTP 200 mostraba el nombre completo del inventario. La misma ruta pasó VALID en la única revalidación posterior; no hubo desafío ni denegación.",
    ])
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
