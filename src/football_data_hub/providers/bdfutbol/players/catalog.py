"""Offline catalog for reusable player captures and resumable acquisition progress."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import tempfile
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .parsers import PLAYER_PARSER_VERSION, PlayerCaptureParseError, parse_player_html

PLAYER_VIEWS = ("profile", "statistics", "matches", "rivals")
_NON_ACCESS_STOP_CODES = {"DISK_SPACE_LOW"}
_VIEW_PATHS = {
    "profile": "/es/j/j{player_id}.html",
    "statistics": "/es/j/j{player_id}.html?p=stats",
    "matches": "/es/p/j{player_id}.html",
    "rivals": "/es/p/jr{player_id}.html",
}
_ACCESS_POLICY = "STOP_ON_UNVERIFIED_HTTP_ERROR"


def _parse_validation_is_current(item: dict[str, Any], html_sha256: str) -> bool:
    validation = item.get("parse_validation")
    if not isinstance(validation, dict):
        return False
    if validation.get("status") != "VALID" or validation.get("parser_version") != PLAYER_PARSER_VERSION:
        return False
    # The digest field was added after the first player captures. For older
    # manifests, raw HTML hashes and metadata identity fields are still checked.
    return validation.get("html_sha256") in (None, html_sha256)


def _is_retryable_navigation_timeout(issue: dict[str, Any]) -> bool:
    """Recognize only a single, unconfirmed Selenium navigation timeout."""
    return (
        issue.get("error_code") == "NAVIGATION_ERROR"
        and issue.get("access_status") == "NAVIGATION_ERROR"
        and issue.get("http_status") is None
        and issue.get("failure_stage") == "access_assessment"
        and issue.get("classification") == "unverified_http_or_content_error"
        and issue.get("policy") == _ACCESS_POLICY
        and "TimeoutError" in str(issue.get("reason") or "")
        and issue.get("final_url") in (None, "")
        and not any(issue.get(key) for key in (
            "missing_markers", "missing_title_markers", "missing_selectors",
            "missing_dom_evidence", "challenge_markers", "denial_markers",
        ))
    )


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
    inventory_sha256: str | None = None,
    manifest_inventory_sha256: str | None = None,
) -> dict[str, Any] | None:
    if item.get("player_id") != player_id or item.get("view") != view:
        return None
    if item.get("snapshot_kind") != "BASE_VIEW":
        return None
    validation = item.get("parse_validation")
    if isinstance(validation, dict) and validation.get("status") == "INVALID":
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
        metadata_raw = metadata_path.read_bytes()
        metadata = json.loads(metadata_raw)
        html = gzip.decompress(raw_path.read_bytes())
    except (KeyError, OSError, ValueError, EOFError, zlib.error, json.JSONDecodeError):
        return None
    if not isinstance(metadata, dict):
        return None
    digest = hashlib.sha256(html).hexdigest()
    captured_at = metadata.get("captured_at_utc")
    try:
        parsed_capture_time = datetime.fromisoformat(str(captured_at).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed_capture_time.tzinfo is None:
        return None
    if (
        metadata.get("capture_id") != capture_id
        or metadata.get("snapshot_id") != item.get("snapshot_id")
        or metadata.get("player_id") != player_id
        or metadata.get("view") != view
        or metadata.get("snapshot_kind") != "BASE_VIEW"
        or metadata.get("requested_url") != expected_url
        or metadata.get("final_url") != expected_url
        or metadata.get("access_status") != "VALID"
        or metadata.get("http_status") != 200
        or metadata.get("html_sha256") != digest
        or metadata.get("html_uncompressed_bytes") != len(html)
        or item.get("html_sha256") != digest
    ):
        return None
    if (
        isinstance(validation, dict)
        and validation.get("html_sha256")
        and validation.get("html_sha256") != digest
    ):
        return None
    validation_is_current = _parse_validation_is_current(item, digest)
    parse_validation = validation
    identity_proof_matches_inventory = bool(
        validation_is_current
        and inventory_sha256
        and manifest_inventory_sha256 == inventory_sha256
    )
    if not identity_proof_matches_inventory:
        try:
            # The compressed file was already read, decompressed and hashed.
            # Parse those exact bytes to avoid a second disk read/decompression.
            parse_player_html(
                html.decode("utf-8"),
                metadata,
                expected_player_id=player_id,
                expected_names=expected_names,
                snapshot_label=str(item.get("metadata_path")),
            )
        except (PlayerCaptureParseError, OSError, ValueError, TypeError, KeyError, UnicodeDecodeError):
            return None
        parse_validation = {
            "status": "VALID",
            "parser_version": PLAYER_PARSER_VERSION,
            "validation_source": "offline_reparse_during_progress_reconciliation",
            "html_sha256": digest,
        }
    if parse_validation.get("status") != "VALID":
        return None
    return {
        "capture_id": capture_id,
        "snapshot_id": str(item.get("snapshot_id") or metadata.get("snapshot_id")),
        "player_id": player_id,
        "view": view,
        "snapshot_kind": "BASE_VIEW",
        "parse_validation": parse_validation,
        "requested_url": expected_url,
        "captured_at_utc": metadata.get("captured_at_utc"),
        "final_url": metadata.get("final_url"),
        "http_status": metadata.get("http_status"),
        "access_status": metadata.get("access_status"),
        "html_sha256": digest,
        "metadata_sha256": hashlib.sha256(metadata_raw).hexdigest(),
        "metadata_path": f"{capture_id}/{item['metadata_path']}",
        "raw_path": f"{capture_id}/{item['raw_path']}",
        "html_uncompressed_bytes": len(html),
        "metadata_bytes": metadata_path.stat().st_size,
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
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Reconcile all valid base views against the inventory without browser access."""
    inventory_path = inventory_path.expanduser().resolve()
    capture_root = capture_root.expanduser().resolve()
    inventory_raw = inventory_path.read_bytes()
    inventory_sha256 = hashlib.sha256(inventory_raw).hexdigest()
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
    manifest_paths = sorted(capture_root.glob("*/manifest.json"))
    started = time.monotonic()
    snapshots_processed = 0
    snapshots_verified = 0
    last_progress_at = started
    if progress_callback is not None:
        progress_callback({
            "phase": "manifest_scan_started",
            "manifest_count": len(manifest_paths),
            "manifests_processed": 0,
            "snapshots_processed": 0,
            "snapshots_verified": 0,
            "elapsed_seconds": 0.0,
        })
    for manifest_index, manifest_path in enumerate(manifest_paths, start=1):
        capture_id = manifest_path.parent.name
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            corrupt_manifests.append(capture_id)
            continue
        if manifest.get("capture_id") != capture_id:
            corrupt_manifests.append(capture_id)
            continue
        inventory_source = manifest.get("inventory_source")
        manifest_inventory_sha256 = (
            inventory_source.get("sha256") if isinstance(inventory_source, dict) else None
        )
        # Failed navigations are normally recorded both as a navigation event
        # and a diagnostic. Merge that pair using the source capture timestamp,
        # but keep distinct attempts separate.
        merged_events: dict[tuple[Any, ...], dict[str, Any]] = {}
        for event in [*manifest.get("navigation_events", []), *manifest.get("diagnostics", [])]:
            if not isinstance(event, dict):
                continue
            event_key = (
                event.get("player_id"), event.get("view"), event.get("requested_url"),
                event.get("access_status"), event.get("http_status"),
                event.get("captured_at_utc") or event.get("recorded_at_utc"),
            )
            merged_events.setdefault(event_key, {}).update(event)
        for event in merged_events.values():
            if event.get("error_code") in _NON_ACCESS_STOP_CODES:
                # A storage pause is resumable and must not be reported as an
                # unresolved HTTP/content error on the next preflight.
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
                "error_code": event.get("error_code"),
                "failure_stage": event.get("failure_stage"),
                "classification": event.get("classification"),
                "policy": event.get("policy"),
                "stop_acquisition": event.get("stop_acquisition"),
                "captured_at_utc": event.get("captured_at_utc") or event.get("recorded_at_utc"),
                "requested_url": event.get("requested_url"),
                "final_url": event.get("final_url"),
                "reason": event.get("reason"),
                "missing_markers": event.get("missing_markers", []),
                "missing_title_markers": event.get("missing_title_markers", []),
                "missing_selectors": event.get("missing_selectors", []),
                "missing_dom_evidence": event.get("missing_dom_evidence", []),
                "challenge_markers": event.get("challenge_markers", []),
                "denial_markers": event.get("denial_markers", []),
            }
            issues = access_issues.setdefault(key, [])
            if issue not in issues:
                issues.append(issue)
        for item in manifest.get("snapshots", []):
            snapshots_processed += 1
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
                inventory_sha256=inventory_sha256,
                manifest_inventory_sha256=manifest_inventory_sha256,
            )
            if verified:
                snapshots_verified += 1
                valid_by_player[player_id].setdefault(view, {})
                current = valid_by_player[player_id][view]
                if not current or str(verified.get("captured_at_utc") or "") > str(current.get("captured_at_utc") or ""):
                    valid_by_player[player_id][view] = verified
            now = time.monotonic()
            if progress_callback is not None and (
                snapshots_processed % 10 == 0 or now - last_progress_at >= 2.0
            ):
                progress_callback({
                    "phase": "snapshot_verification",
                    "manifest_count": len(manifest_paths),
                    "manifests_processed": manifest_index - 1,
                    "current_capture_id": capture_id,
                    "snapshots_processed": snapshots_processed,
                    "snapshots_verified": snapshots_verified,
                    "elapsed_seconds": round(now - started, 1),
                })
                last_progress_at = now
        if progress_callback is not None:
            progress_callback({
                "phase": "manifest_complete",
                "manifest_count": len(manifest_paths),
                "manifests_processed": manifest_index,
                "current_capture_id": capture_id,
                "snapshots_processed": snapshots_processed,
                "snapshots_verified": snapshots_verified,
                "elapsed_seconds": round(time.monotonic() - started, 1),
            })

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
    retryable_navigation_errors = [
        {"player_id": player_id, "view": view, **issue}
        for (player_id, view), issues in access_issues.items()
        for issue in issues
        if _is_retryable_navigation_timeout(issue)
    ]
    summary["retryable_navigation_errors"] = len(retryable_navigation_errors)
    result = {
        "schema_version": "football_data_hub.bdfutbol.player_acquisition_progress.v1",
        "generated_at_utc": _utc_now(),
        "inventory": {
            "path": str(inventory_path),
            "sha256": inventory_sha256,
            "schema_version": inventory.get("schema_version"),
            "season": inventory.get("metadata", {}).get("season"),
        },
        "capture_root": str(capture_root),
        "summary": summary,
        "pending_player_ids": ids_pending,
        "pending_views": views_pending,
        "corrupt_manifests": corrupt_manifests,
        "retryable_navigation_errors": retryable_navigation_errors,
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
