"""Offline catalog for reusable player captures and resumable acquisition progress."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .html_parser import soup_from_html

PLAYER_VIEWS = ("profile", "statistics", "matches", "rivals")
_VIEW_PATHS = {
    "profile": "/es/j/j{player_id}.html",
    "statistics": "/es/j/j{player_id}.html?p=stats",
    "matches": "/es/p/j{player_id}.html",
    "rivals": "/es/p/jr{player_id}.html",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _verified_base_snapshot(
    capture_root: Path,
    capture_id: str,
    item: dict[str, Any],
    *,
    player_id: int,
    view: str,
    expected_names: tuple[str, ...] = (),
) -> dict[str, Any] | None:
    if item.get("player_id") != player_id or item.get("view") != view:
        return None
    if item.get("snapshot_kind") != "BASE_VIEW":
        return None
    expected_url = "https://www.bdfutbol.com" + _VIEW_PATHS[view].format(player_id=player_id)
    if item.get("requested_url") != expected_url or item.get("final_url") != expected_url:
        return None
    try:
        metadata_path = (capture_root / capture_id / str(item["metadata_path"])).resolve()
        raw_path = (capture_root / capture_id / str(item["raw_path"])).resolve()
        run_dir = (capture_root / capture_id).resolve()
        if run_dir not in metadata_path.parents or run_dir not in raw_path.parents:
            return None
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        html = gzip.decompress(raw_path.read_bytes())
    except (KeyError, OSError, ValueError, json.JSONDecodeError):
        return None
    digest = hashlib.sha256(html).hexdigest()
    page = soup_from_html(html.decode("utf-8", errors="replace"))
    title = page.title.get_text(" ", strip=True) if page.title else ""
    heading = page.find("h1")
    visible_identity = f"{title} {heading.get_text(' ', strip=True) if heading else ''}".casefold()
    identity_valid = bool(expected_names) and any(
        name and name.casefold() in visible_identity for name in expected_names
    )
    if (
        metadata.get("capture_id") != capture_id
        or metadata.get("player_id") != player_id
        or metadata.get("view") != view
        or metadata.get("snapshot_kind") != "BASE_VIEW"
        or metadata.get("requested_url") != expected_url
        or metadata.get("final_url") != expected_url
        or metadata.get("access_status") != "VALID"
        or metadata.get("http_status") != 200
        or metadata.get("html_sha256") != digest
        or item.get("html_sha256") != digest
        or not identity_valid
    ):
        return None
    return {
        "capture_id": capture_id,
        "snapshot_id": str(item.get("snapshot_id") or metadata.get("snapshot_id")),
        "player_id": player_id,
        "view": view,
        "snapshot_kind": "BASE_VIEW",
        "requested_url": expected_url,
        "captured_at_utc": metadata.get("captured_at_utc"),
        "html_sha256": digest,
        "metadata_path": f"{capture_id}/{item['metadata_path']}",
        "raw_path": f"{capture_id}/{item['raw_path']}",
        "raw_bytes": len(html),
        "compressed_bytes": raw_path.stat().st_size,
    }


def find_valid_base_snapshot(
    capture_root: Path,
    *,
    player_id: int,
    view: str,
    expected_names: tuple[str, ...],
) -> dict[str, Any] | None:
    """Find a newest, hash-verified base view across all previous capture runs."""
    if view not in PLAYER_VIEWS:
        raise ValueError(f"Vista no admitida: {view}")
    root = capture_root.expanduser().resolve()
    candidates: list[dict[str, Any]] = []
    for manifest_path in root.glob("*/manifest.json"):
        capture_id = manifest_path.parent.name
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if manifest.get("capture_id") != capture_id:
            continue
        for item in manifest.get("snapshots", []):
            if not isinstance(item, dict):
                continue
            verified = _verified_base_snapshot(
                root, capture_id, item, player_id=player_id, view=view,
                expected_names=expected_names,
            )
            if verified:
                candidates.append(verified)
    return max(candidates, key=lambda item: str(item.get("captured_at_utc") or ""), default=None)


def build_player_acquisition_progress(
    *,
    inventory_path: Path,
    capture_root: Path,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Reconcile all valid base views against the inventory without browser access."""
    inventory_path = inventory_path.expanduser().resolve()
    capture_root = capture_root.expanduser().resolve()
    inventory_raw = inventory_path.read_bytes()
    inventory = json.loads(inventory_raw)
    records = inventory.get("records")
    if not isinstance(records, list):
        raise ValueError("El inventario no contiene records")
    player_records: dict[int, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("player_id"), int):
            continue
        player_id = record["player_id"]
        if player_id in player_records:
            raise ValueError(f"player_id duplicado en inventario: {player_id}")
        player_records[player_id] = record

    valid_by_player: dict[int, dict[str, dict[str, Any]]] = {
        player_id: {} for player_id in player_records
    }
    access_issues: dict[tuple[int, str], list[dict[str, Any]]] = {}
    corrupt_manifests: list[str] = []
    for manifest_path in sorted(capture_root.glob("*/manifest.json")):
        capture_id = manifest_path.parent.name
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            corrupt_manifests.append(capture_id)
            continue
        if manifest.get("capture_id") != capture_id:
            corrupt_manifests.append(capture_id)
            continue
        for event in [
            *manifest.get("navigation_events", []),
            *manifest.get("diagnostics", []),
        ]:
            if not isinstance(event, dict):
                continue
            player_id, view = event.get("player_id"), event.get("view")
            if player_id not in player_records or view not in PLAYER_VIEWS:
                continue
            if event.get("access_status") == "VALID" and event.get("http_status") == 200:
                continue
            if event.get("snapshot_kind") not in (None, "BASE_VIEW") and event.get("navigation_purpose") != "base_view_capture":
                continue
            key = (player_id, view)
            issue = {
                "capture_id": capture_id,
                "access_status": event.get("access_status"),
                "http_status": event.get("http_status"),
                "captured_at_utc": event.get("captured_at_utc") or event.get("recorded_at_utc"),
                "requested_url": event.get("requested_url"),
                "reason": event.get("reason"),
            }
            issues = access_issues.setdefault(key, [])
            if issue not in issues:
                issues.append(issue)
        for item in manifest.get("snapshots", []):
            if not isinstance(item, dict):
                continue
            player_id, view = item.get("player_id"), item.get("view")
            if player_id not in valid_by_player or view not in PLAYER_VIEWS:
                continue
            verified = _verified_base_snapshot(
                capture_root, capture_id, item, player_id=player_id, view=view,
                expected_names=tuple(
                    str(value).strip()
                    for value in (
                        player_records[player_id].get("display_name"),
                        player_records[player_id].get("full_name"),
                    ) if value
                ),
            )
            if verified:
                valid_by_player[player_id].setdefault(view, {})
                current = valid_by_player[player_id][view]
                if not current or str(verified.get("captured_at_utc") or "") > str(current.get("captured_at_utc") or ""):
                    valid_by_player[player_id][view] = verified

    progress_records: list[dict[str, Any]] = []
    ids_pending: list[int] = []
    views_pending: list[dict[str, Any]] = []
    completed_players = 0
    completed_roster = 0
    completed_transfer_only = 0
    roster_count = 0
    transfer_only_count = 0
    players_with_access_errors = 0
    blocked_base_views = 0
    pending_base_navigations = 0
    for player_id, player in sorted(player_records.items()):
        is_roster = int(player.get("membership_count") or 0) > 0
        cohort = "roster" if is_roster else "transfer_only"
        roster_count += int(is_roster)
        transfer_only_count += int(not is_roster)
        refs = valid_by_player[player_id]
        missing = [view for view in PLAYER_VIEWS if view not in refs]
        player_issues = {
            view: access_issues.get((player_id, view), [])
            for view in missing if access_issues.get((player_id, view))
        }
        players_with_access_errors += int(bool(player_issues))
        blocked_base_views += len(player_issues)
        pending_base_navigations += len(missing)
        if missing:
            ids_pending.append(player_id)
            views_pending.extend({"player_id": player_id, "view": view} for view in missing)
        else:
            completed_players += 1
            completed_roster += int(is_roster)
            completed_transfer_only += int(not is_roster)
        progress_records.append({
            "player_id": player_id,
            "display_name": player.get("display_name"),
            "cohort": cohort,
            "groups": player.get("groups", []),
            "membership_count": player.get("membership_count", 0),
            "view_snapshots": {
                view: refs.get(view) for view in PLAYER_VIEWS
            },
            "views_pending": missing,
            "access_issues": player_issues,
            "status": "COMPLETE_BASE_VIEWS" if not missing else (
                "STOPPED_AFTER_ACCESS_OR_STRUCTURE_ERROR" if player_issues
                else "PARTIAL_CHECKPOINT" if refs else "PENDING"
            ),
        })
    summary = {
        "inventory_players": len(player_records),
        "roster_players": roster_count,
        "transfer_only_players": transfer_only_count,
        "players_with_all_base_views": completed_players,
        "roster_players_with_all_base_views": completed_roster,
        "transfer_only_players_with_all_base_views": completed_transfer_only,
        "players_pending": len(ids_pending),
        "base_view_navigations_pending": pending_base_navigations,
        "captured_valid_base_views": 4 * len(player_records) - pending_base_navigations,
        "players_with_access_errors": players_with_access_errors,
        "blocked_base_views": blocked_base_views,
    }
    result = {
        "schema_version": "football_data_hub.bdfutbol.player_acquisition_progress.v1",
        "generated_at_utc": _utc_now(),
        "inventory": {
            "path": str(inventory_path),
            "sha256": hashlib.sha256(inventory_raw).hexdigest(),
            "schema_version": inventory.get("schema_version"),
            "season": inventory.get("metadata", {}).get("season"),
        },
        "capture_root": str(capture_root),
        "summary": summary,
        "pending_player_ids": ids_pending,
        "pending_views": views_pending,
        "corrupt_manifests": corrupt_manifests,
        "players": progress_records,
    }
    if output_path:
        destination = output_path.expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n"
        fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        except BaseException:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
        result["output_path"] = str(destination)
        result["output_sha256"] = hashlib.sha256(raw).hexdigest()
    return result
