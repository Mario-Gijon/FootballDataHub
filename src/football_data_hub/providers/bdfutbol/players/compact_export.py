"""Compact, provenance-preserving exports consolidated across capture runs."""

from __future__ import annotations

import hashlib
import gzip
import json
import os
import shutil
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from .catalog import PLAYER_VIEWS, build_player_acquisition_progress
from .parsers import PlayerCaptureParseError, parse_snapshot

COMPACT_SCHEMA_VERSION = "football_data_hub.bdfutbol.player_compact_profile.v1"
_ROW_LAYOUT_KEYS = {
    "classes_raw", "style_raw", "responsive_optional", "colspan", "rowspan",
    "tag", "data_colid_raw",
}
_MATCH_RAW_KEYS = {"source_values_raw", "source_js_field_names", "source_snapshot"}
_IDENTITY_FIELDS = (
    "player_id", "display_name", "full_name", "profile_url", "photo_url",
    "birth_date", "age_years", "birthplace", "birthplace_province",
    "nationality", "nationality_code", "position_code", "position_name",
    "source_position_code", "association_status", "groups", "team_ids",
    "membership_count", "verified_indicators", "identity_conflicts",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _atomic_json(path: Path, value: dict[str, Any]) -> bytes:
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"
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


def _atomic_bytes(path: Path, raw: bytes) -> None:
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


def _compact_column(column: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key in (
        "column_index", "group_header_raw", "header_original", "header_title_raw",
        "data_colid_raw", "raw_value", "normalized_integer", "value_status",
        "hidden_by_inline_style",
    ):
        if key in column:
            compact[key] = column[key]
    links = column.get("links")
    if isinstance(links, list):
        compact["links"] = [
            {key: link[key] for key in ("text_raw", "href_raw", "url") if key in link}
            for link in links
            if isinstance(link, dict)
        ]
    return compact


def _compact_cells(cells: Any) -> Any:
    if not isinstance(cells, list):
        return cells
    return [
        _compact_column(cell) if isinstance(cell, dict) else cell
        for cell in cells
    ]


def _compact_row(row: dict[str, Any], *, is_match: bool = False) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in row.items():
        if key in _ROW_LAYOUT_KEYS or (is_match and key in _MATCH_RAW_KEYS):
            continue
        if key == "columns":
            compact[key] = _compact_cells(value)
        elif key == "cells":
            compact[key] = _compact_cells(value)
        else:
            compact[key] = value
    return compact


def _compact_tabular_tables(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group rows by source table and store repeated headers once per table."""
    tables: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    omitted = _ROW_LAYOUT_KEYS | {
        "columns", "cells", "source_table_index", "table_id", "table_role",
        "source_table_id", "source_table_role",
    }
    for row in rows:
        columns = row.get("columns", row.get("cells"))
        if not isinstance(columns, list):
            key = (str(row.get("table_id") or row.get("source_table_id") or ""),
                   str(row.get("table_role") or row.get("source_table_role") or ""),
                   str(row.get("source_table_index") or ""), "no-schema")
            table = tables.setdefault(key, {
                "table_id": row.get("table_id", row.get("source_table_id")),
                "table_role": row.get("table_role", row.get("source_table_role")),
                "source_table_index": row.get("source_table_index"),
                "cell_value_fields": ["raw_value", "normalized_integer", "value_status"],
                "columns": [],
                "records": [],
            })
            table["records"].append(_compact_row(row))
            continue
        headers = []
        values = []
        for index, column in enumerate(columns):
            if not isinstance(column, dict):
                headers.append({"source_index": index, "header_original": None, "header_title_raw": None})
                values.append({"raw_value": column, "normalized_integer": None, "value_status": "RAW_ONLY"})
                continue
            header = {
                "source_index": index,
                "group_header_raw": column.get("group_header_raw"),
                "header_original": column.get("header_original"),
                "header_title_raw": column.get("header_title_raw"),
                "data_colid_raw": column.get("data_colid_raw"),
                "hidden_by_inline_style": column.get("hidden_by_inline_style"),
            }
            headers.append(header)
            values.append({
                "raw_value": column.get("raw_value"),
                "normalized_integer": column.get("normalized_integer"),
                "value_status": column.get("value_status"),
            })
        signature = json.dumps(headers, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        schema_id = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:16]
        table_id = str(row.get("table_id", row.get("source_table_id")) or "")
        table_role = str(row.get("table_role", row.get("source_table_role")) or "")
        table_index = str(row.get("source_table_index") or "")
        key = (table_id, table_role, table_index, schema_id)
        if key not in tables:
            tables[key] = {
                "schema_id": schema_id,
                "source_table_index": row.get("source_table_index"),
                "table_id": row.get("table_id", row.get("source_table_id")),
                "table_role": row.get("table_role", row.get("source_table_role")),
                "cell_value_fields": ["raw_value", "normalized_integer", "value_status"],
                "columns": headers,
                "records": [],
            }
        compact = {field: value for field, value in row.items() if field not in omitted | {"player_id"}}
        compact["column_values"] = [
            [value.get("raw_value"), value.get("normalized_integer"), value.get("value_status")]
            for value in values
        ]
        tables[key]["records"].append(compact)
    return list(tables.values())


def compact_player_page(page: Any, source_ref: dict[str, Any]) -> dict[str, Any]:
    """Project a parsed view to semantic records; raw HTML remains the evidence."""
    view = page.view
    result: dict[str, Any] = {
        "view": view,
        "requested_url": page.requested_url,
        "final_url": page.final_url,
        "page_title_raw": page.page_title_raw,
        "source": source_ref,
        "coverage": page.coverage,
    }
    if view == "profile":
        profile = dict(page.profile)
        profile.pop("career_rows", None)
        profile.pop("career_totals_raw", None)
        result["profile"] = profile
        result["career_tables"] = _compact_tabular_tables(page.career_rows)
        result["career_totals_tables"] = _compact_tabular_tables(page.career_totals)
    elif view == "statistics":
        result["statistics_tables"] = _compact_tabular_tables(page.statistics_rows)
    elif view == "matches":
        result.update({
            "summary_tables": _compact_tabular_tables(page.summary_rows),
            "individual_matches_source": page.individual_matches_source,
            "window_p_parse_status": page.window_p_parse_status,
            "window_p_record_count": page.window_p_record_count,
            "detail_coverage": page.detail_coverage,
            "filter_parameters": page.filter_parameters,
            "filtered_view": page.filtered_view,
            "exhaustiveness_status": page.exhaustiveness_status,
        })
        matches = [_compact_row(row, is_match=True) for row in page.individual_matches]
        result["individual_matches"] = [
            row for row in matches
            if row.get("player_appearance_status") == "APPEARED_PER_SOURCE_FLAGS"
        ]
        result["summoned_without_participation"] = [
            row for row in matches
            if row.get("player_summoned_status")
            == "SUMMONED_WITHOUT_APPEARANCE_PER_SOURCE_FLAG"
        ]
        result["other_match_records"] = [
            row for row in matches
            if row.get("player_appearance_status") != "APPEARED_PER_SOURCE_FLAGS"
            and row.get("player_summoned_status")
            != "SUMMONED_WITHOUT_APPEARANCE_PER_SOURCE_FLAG"
        ]
        result["record_counts"] = {
            "individual_matches": len(result["individual_matches"]),
            "summoned_without_participation": len(result["summoned_without_participation"]),
            "other_match_records": len(result["other_match_records"]),
        }
    elif view == "rivals":
        result["rival_tables"] = _compact_tabular_tables(page.rival_records)
    else:
        raise PlayerCaptureParseError(f"Vista no admitida para export compacto: {view}")
    return result


def _source_reference(reference: dict[str, Any], capture_root: Path) -> dict[str, Any]:
    return {
        "capture_id": reference["capture_id"],
        "snapshot_id": reference["snapshot_id"],
        "view": reference["view"],
        "snapshot_kind": reference["snapshot_kind"],
        "captured_at_utc": reference.get("captured_at_utc"),
        "requested_url": reference["requested_url"],
        "final_url": reference.get("final_url"),
        "html_sha256": reference["html_sha256"],
        "metadata_sha256": reference.get("metadata_sha256"),
        "raw_path": reference["raw_path"],
        "metadata_path": reference["metadata_path"],
        "compressed_bytes": reference.get("compressed_bytes"),
        "metadata_bytes": reference.get("metadata_bytes"),
    }


def _parse_indexed_snapshot(
    capture_root: Path,
    reference: dict[str, Any],
    player: dict[str, Any],
) -> Any:
    capture_id = reference["capture_id"]
    prefix = f"{capture_id}/"
    metadata_path = str(reference["metadata_path"])
    raw_path = str(reference["raw_path"])
    if not metadata_path.startswith(prefix) or not raw_path.startswith(prefix):
        raise PlayerCaptureParseError("La referencia del snapshot escapa de su captura")
    snapshot_record = {
        "player_id": player["player_id"],
        "view": reference["view"],
        "snapshot_id": reference["snapshot_id"],
        "snapshot_kind": reference["snapshot_kind"],
        "metadata_path": metadata_path[len(prefix):],
        "raw_path": raw_path[len(prefix):],
        "html_sha256": reference["html_sha256"],
        "requested_url": reference["requested_url"],
    }
    names = tuple(
        str(value).strip()
        for value in (player.get("display_name"), player.get("full_name"))
        if value
    )
    return parse_snapshot(
        capture_root / capture_id,
        snapshot_record,
        expected_player_id=player["player_id"],
        expected_names=names,
    )


def build_compact_player_document(
    *,
    player: dict[str, Any],
    capture_root: Path,
    progress_record: dict[str, Any],
    inventory_sha256: str,
    season: str,
) -> dict[str, Any]:
    """Consolidate the latest four verified base views, possibly across runs."""
    capture_root = capture_root.expanduser().resolve()
    views: dict[str, Any] = {}
    source_refs: dict[str, dict[str, Any]] = {}
    parse_errors: dict[str, str] = {}
    snapshots = progress_record.get("view_snapshots", {})
    for view in PLAYER_VIEWS:
        reference = snapshots.get(view)
        if not isinstance(reference, dict):
            continue
        try:
            page = _parse_indexed_snapshot(capture_root, reference, player)
            source_ref = _source_reference(reference, capture_root)
            views[view] = compact_player_page(page, source_ref)
            source_refs[view] = source_ref
        except (OSError, ValueError, TypeError, KeyError) as exc:
            parse_errors[view] = f"{type(exc).__name__}: {exc}"

    views_missing = [view for view in PLAYER_VIEWS if view not in views]
    complete = not views_missing and not parse_errors
    profile_page = views.get("profile", {})
    career_rows = [
        row
        for table in profile_page.get("career_tables", [])
        for row in table.get("records", [])
    ]
    club_career_relationships = [
        {
            key: row.get(key)
            for key in (
                "team_name_raw", "season_raw", "division_raw",
                "team_season_reference", "team_season_url", "source_row_index",
            )
        }
        for row in career_rows
    ]
    identity = {key: player.get(key) for key in _IDENTITY_FIELDS if key in player}
    inventory_enrichment = {
        key: player.get(key)
        for key in (
            "team_associations", "source_refs", "source_views", "season_statistics",
            "match_metrics", "match_minutes", "transfer_references",
            "supplemental_top_observations", "nationality_source_refs",
        )
        if key in player
    }
    warnings = []
    if views_missing:
        warnings.append("Faltan vistas base: " + ", ".join(views_missing))
    if parse_errors:
        warnings.append("Una o más vistas verificadas no pudieron parsearse")
    if player.get("identity_conflicts"):
        warnings.append("El inventario conserva conflictos de identidad sin resolver")
    return {
        "schema_version": COMPACT_SCHEMA_VERSION,
        "player_id": int(player["player_id"]),
        "season_context": season,
        "derived_at_utc": _utc_now(),
        "status": "COMPLETE_BASE_VIEWS" if complete else "PARTIAL_BASE_VIEWS",
        "base_view_completeness_certifies_historical_exhaustiveness": False,
        "identity": identity,
        "inventory_enrichment": inventory_enrichment,
        "club_career_relationships": club_career_relationships,
        "views": views,
        "view_sources": source_refs,
        "views_missing": views_missing,
        "parse_errors": parse_errors,
        "warnings": warnings,
        "inventory_source": {
            "sha256": inventory_sha256,
            "schema_version": "football_data_hub.player_inventory.v1",
        },
    }


def _build_compact_generation_entry(
    task: tuple[dict[str, Any], Path, dict[str, Any], str, str, Path],
) -> dict[str, Any]:
    player, capture_root, progress_record, inventory_hash, season, temporary_dir = task
    player_id = int(player["player_id"])
    document = build_compact_player_document(
        player=player,
        capture_root=capture_root,
        progress_record=progress_record,
        inventory_sha256=inventory_hash,
        season=season,
    )
    relative_path = Path("players") / f"{player_id}.json.gz"
    json_raw = json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"
    raw = gzip.compress(json_raw, compresslevel=6, mtime=0)
    _atomic_bytes(temporary_dir / relative_path, raw)
    return {
        "player_id": player_id,
        "cohort": "roster" if int(player.get("membership_count") or 0) > 0 else "transfer_only",
        "status": document["status"],
        "path": relative_path.as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "uncompressed_bytes": len(json_raw),
        "compression": "gzip",
        "source_capture_ids": sorted({
            ref["capture_id"] for ref in document["view_sources"].values()
        }),
    }


def build_compact_player_generation(
    *,
    inventory_path: Path,
    capture_root: Path,
    output_root: Path,
    player_ids: set[int] | None = None,
    complete_only: bool = False,
    progress_index: dict[str, Any] | None = None,
    max_workers: int = 4,
    progress_callback: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Atomically publish compact player documents and a versioned manifest."""
    inventory_path = inventory_path.expanduser().resolve()
    capture_root = capture_root.expanduser().resolve()
    output_root = output_root.expanduser().resolve()
    if type(max_workers) is not int or not 1 <= max_workers <= 8:
        raise ValueError("max_workers debe estar entre 1 y 8")
    inventory_raw = inventory_path.read_bytes()
    inventory_hash = hashlib.sha256(inventory_raw).hexdigest()
    inventory = json.loads(inventory_raw)
    progress = progress_index or build_player_acquisition_progress(
        inventory_path=inventory_path,
        capture_root=capture_root,
    )
    if progress.get("inventory", {}).get("sha256") != inventory_hash:
        raise ValueError("El índice de progreso corresponde a otro inventario")
    if Path(str(progress.get("capture_root", ""))).resolve() != capture_root:
        raise ValueError("El índice de progreso corresponde a otra raíz de capturas")
    inventory_records = {
        int(record["player_id"]): record
        for record in inventory.get("records", [])
        if isinstance(record, dict) and isinstance(record.get("player_id"), int)
    }
    selected = []
    for record in progress.get("players", []):
        player_id = int(record["player_id"])
        if player_ids is not None and player_id not in player_ids:
            continue
        if player_id not in inventory_records:
            raise ValueError(f"El índice contiene player_id fuera del inventario: {player_id}")
        if complete_only and record.get("status") != "COMPLETE_BASE_VIEWS":
            continue
        selected.append(record)
    selected.sort(key=lambda record: (
        0 if int(inventory_records[int(record["player_id"])].get("membership_count") or 0) > 0 else 1,
        int(record["player_id"]),
    ))

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    generation_id = f"{stamp}-{uuid4().hex[:8]}"
    generations_root = output_root / "generations"
    generations_root.mkdir(parents=True, exist_ok=True)
    temporary_dir = Path(tempfile.mkdtemp(prefix=f".tmp-{generation_id}-", dir=generations_root))
    final_dir = generations_root / generation_id
    entries: list[dict[str, Any]] = []
    try:
        tasks = [
            (
                inventory_records[int(record["player_id"])],
                capture_root,
                record,
                inventory_hash,
                str(inventory.get("metadata", {}).get("season") or "2026-27"),
                temporary_dir,
            )
            for record in selected
        ]
        if max_workers == 1:
            results = map(_build_compact_generation_entry, tasks)
            for completed, entry in enumerate(results, start=1):
                entries.append(entry)
                if progress_callback is not None:
                    progress_callback(completed, len(tasks))
        else:
            entry_by_id = {}
            with ProcessPoolExecutor(max_workers=max_workers) as executor:
                futures = [executor.submit(_build_compact_generation_entry, task) for task in tasks]
                for completed, future in enumerate(as_completed(futures), start=1):
                    entry = future.result()
                    entry_by_id[entry["player_id"]] = entry
                    if progress_callback is not None:
                        progress_callback(completed, len(tasks))
            entries = [entry_by_id[int(record["player_id"])] for record in selected]
        manifest = {
            "schema_version": "football_data_hub.player_compact_generation.v1",
            "generation_id": generation_id,
            "generated_at_utc": _utc_now(),
            "season": str(inventory.get("metadata", {}).get("season") or "2026-27"),
            "inventory_path": str(inventory_path),
            "inventory_sha256": inventory_hash,
            "capture_root": str(capture_root),
            "player_count": len(entries),
            "complete_player_count": sum(entry["status"] == "COMPLETE_BASE_VIEWS" for entry in entries),
            "partial_player_count": sum(entry["status"] != "COMPLETE_BASE_VIEWS" for entry in entries),
            "compact_json_gzip_bytes": sum(entry["bytes"] for entry in entries),
            "compact_json_uncompressed_bytes": sum(entry["uncompressed_bytes"] for entry in entries),
            "entries": entries,
        }
        manifest_raw = _atomic_json(temporary_dir / "manifest.json", manifest)
        manifest_hash = hashlib.sha256(manifest_raw).hexdigest()
        os.replace(temporary_dir, final_dir)
        pointer = {
            "schema_version": "football_data_hub.player_compact_current.v1",
            "generation_id": generation_id,
            "manifest_path": f"generations/{generation_id}/manifest.json",
            "manifest_sha256": manifest_hash,
            "generated_at_utc": manifest["generated_at_utc"],
        }
        _atomic_json(output_root / "current.json", pointer)
        return {
            **{key: value for key, value in manifest.items() if key != "entries"},
            "generation_dir": str(final_dir),
            "manifest_sha256": manifest_hash,
            "mean_player_bytes": round(manifest["compact_json_gzip_bytes"] / len(entries)) if entries else 0,
            "mean_player_uncompressed_bytes": round(manifest["compact_json_uncompressed_bytes"] / len(entries)) if entries else 0,
            "max_player_bytes": max((entry["bytes"] for entry in entries), default=0),
        }
    except BaseException:
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir, ignore_errors=True)
        raise
