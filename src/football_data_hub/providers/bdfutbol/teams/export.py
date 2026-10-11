"""Immutable, versioned JSON and source snapshots for team-profile runs."""

from __future__ import annotations

import hashlib
import gzip
import json
import os
import shutil
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .acquisition import EXTRACTOR_VERSION, TeamAcquisitionBundle
from .models import TeamProfileData

CAPTURE_POLICY_ID = "team-profile-six-views-follow-states-v1"
CAPTURE_POLICY_VERSION = 1


def normalized_payloads(parsed: TeamProfileData) -> dict[str, dict[str, Any]]:
    """Return the normalized JSON bodies from the typed, validated model."""
    return {
        "team_identity": {"record": asdict(parsed.identity)},
        "team_season": {"record": asdict(parsed.season)},
        "players": {"records": [asdict(item) for item in parsed.players]},
        "memberships": {"records": [asdict(item) for item in parsed.memberships]},
        "player_statistics": {"records": [asdict(item) for item in parsed.player_statistics]},
        "player_match_minutes": {"records": [asdict(item) for item in parsed.player_match_minutes]},
        "player_match_metrics": {
            "records": [asdict(item) for item in parsed.player_match_metrics],
            "captured_states": list(parsed.follow_states_captured),
        },
        "transfers": {"records": [asdict(item) for item in parsed.transfers]},
        "profile_references": {
            "team_ids_from_profile": list(parsed.group_team_ids_from_profile),
            "match_ids_from_profile": list(parsed.team_match_ids_from_profile),
            "note": "References only. Reuse the corresponding group catalog for full records.",
        },
    }


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as target:
        json.dump(value, target, ensure_ascii=False, indent=2)
        target.write("\n")


def _dataset_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        key: metadata[key]
        for key in (
            "source", "season", "competition", "group", "team_id",
            "capture_id", "captured_at_utc", "started_at_utc", "extractor_version",
            "semantic_validation_version", "capture_policy", "related_team_catalog", "source_snapshots",
            "follow_states", "acquired_views", "reused_views", "reused_source_capture_ids",
        )
    }


def export_team_capture(
    output_root: Path,
    bundle: TeamAcquisitionBundle,
    *,
    profile_dir: Path | None,
    capture_timestamp_basis: str,
) -> dict[str, Path]:
    """Atomically publish a complete new capture; never replace earlier data."""
    team_id = bundle.parsed.identity.team_id
    parent = output_root.expanduser() / bundle.competition.season / str(team_id)
    parent.mkdir(parents=True, exist_ok=True)
    run_dir = parent / bundle.capture_id
    staging_dir = parent / f".{bundle.capture_id}.tmp"
    staging_dir.mkdir(exist_ok=False)
    try:
        source_snapshots: dict[str, dict[str, Any]] = {}
        for view, html in bundle.raw_views.items():
            html_bytes = html.encode("utf-8")
            compressed_bytes = gzip.compress(html_bytes, compresslevel=9, mtime=0)
            relative = Path("raw") / f"{view}.html.gz"
            source_path = staging_dir / relative
            source_path.parent.mkdir(parents=True, exist_ok=True)
            with source_path.open("xb") as target:
                target.write(compressed_bytes)
            source_snapshots[view] = {
                "path": relative.as_posix(),
                "compression": "gzip",
                "url": bundle.view_urls[view],
                "title": bundle.page_titles.get(view),
                "http_status": bundle.access_by_view[view].get("http_status"),
                "sha256": hashlib.sha256(html_bytes).hexdigest(),
                "bytes_utf8": len(html_bytes),
                "stored_bytes": len(compressed_bytes),
                "access_status": bundle.access_by_view[view].get("status"),
                "captured_at_utc": bundle.access_by_view[view].get("captured_at_utc"),
                "capture_timestamp_basis": bundle.access_by_view[view].get("capture_timestamp_basis"),
            }
        metadata = {
            "schema_version": 1,
            "capture_id": bundle.capture_id,
            "source": "BDFutbol",
            "section": "team_profile",
            "season": bundle.competition.season,
            "competition": bundle.competition.competition,
            "competition_scope": "Liga",
            "group": bundle.competition.group_roman,
            "group_number": bundle.competition.group_number,
            "team_id": team_id,
            "team_name": bundle.parsed.identity.name,
            "team_url": bundle.parsed.identity.team_url,
            "requested_views": list(bundle.requested_views),
            "acquired_views": list(bundle.acquired_views),
            "reused_views": [view for view in bundle.requested_views if view not in bundle.acquired_views],
            "view_urls": bundle.view_urls,
            "captured_at_utc": bundle.captured_at_utc,
            "started_at_utc": bundle.started_at_utc,
            "capture_timestamp_basis": capture_timestamp_basis,
            "extractor_version": EXTRACTOR_VERSION,
            "semantic_validation_version": bundle.validation.get("semantic_version"),
            "capture_policy": {
                "id": CAPTURE_POLICY_ID,
                "version": CAPTURE_POLICY_VERSION,
                "required_views": ["alignment", "squad", "statistics", "follow", "transfers", "matches"],
                "required_follow_states": ["p", "t", "go", "tot"],
            },
            "browser": bundle.browser,
            "profile_dir": str(profile_dir.expanduser()) if profile_dir is not None else None,
            "access_by_view": bundle.access_by_view,
            "source_snapshots": source_snapshots,
            "reused_source_capture_ids": list(bundle.seed_capture_ids),
            "follow_states": {},
            "related_team_catalog": bundle.team_catalog_reference,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "data_scope_notes": [
                "The team profile supplements the group match/standings datasets.",
                "Team-match references are IDs only; fixture and score records are not duplicated.",
                "Images are represented by source URLs and were not downloaded.",
            ],
        }
        _write_json(staging_dir / "raw" / "access.json", {
            "capture_id": bundle.capture_id,
            "captured_at_utc": bundle.captured_at_utc,
            "capture_timestamp_basis": capture_timestamp_basis,
            "requested_views": list(bundle.requested_views),
            "views": bundle.access_by_view,
            "browser": bundle.browser,
        })
        _write_json(staging_dir / "metadata" / "capture.json", metadata)

        follow_state_metadata: dict[str, dict[str, Any]] = {}
        for state, html in bundle.follow_state_html.items():
            html_bytes = html.encode("utf-8")
            compressed_bytes = gzip.compress(html_bytes, compresslevel=9, mtime=0)
            relative = Path("raw") / "follow_states" / f"{state}.html.gz"
            source_path = staging_dir / relative
            source_path.parent.mkdir(parents=True, exist_ok=True)
            with source_path.open("xb") as target:
                target.write(compressed_bytes)
            follow_state_metadata[state] = {
                **{
                    key: value
                    for key, value in bundle.follow_state_diagnostics.get(state, {}).items()
                    if key not in {"path", "compression", "sha256", "stored_bytes", "bytes_utf8"}
                },
                "status": "VALID",
                "selected_value": state,
                "source_capture_id": bundle.follow_state_diagnostics.get(state, {}).get("source_capture_id") or bundle.capture_id,
                "sha256": hashlib.sha256(html_bytes).hexdigest(),
                "path": relative.as_posix(),
                "compression": "gzip",
                "bytes_utf8": len(html_bytes),
                "stored_bytes": len(compressed_bytes),
            }
        metadata["follow_states"] = follow_state_metadata
        if follow_state_metadata:
            # Rewrite the still-unpublished metadata file with the complete raw
            # evidence index; all writes remain inside the atomic staging dir.
            metadata_path = staging_dir / "metadata" / "capture.json"
            metadata_path.unlink()
            _write_json(metadata_path, metadata)
        if follow_state_metadata:
            access_path = staging_dir / "raw" / "access.json"
            access_payload = json.loads(access_path.read_text(encoding="utf-8"))
            access_payload["follow_states"] = follow_state_metadata
            access_path.unlink()
            _write_json(access_path, access_payload)

        payloads = normalized_payloads(bundle.parsed)
        output_paths: dict[str, Path] = {
            "raw_access": run_dir / "raw" / "access.json",
            "metadata": run_dir / "metadata" / "capture.json",
        }
        for dataset, payload in payloads.items():
            path = staging_dir / "normalized" / f"{dataset}.json"
            _write_json(path, {
                "schema_version": 1,
                "metadata": _dataset_metadata(metadata),
                **payload,
            })
            output_paths[dataset] = run_dir / path.relative_to(staging_dir)
        metadata["normalized_snapshots"] = {
            path.name: {
                "path": path.relative_to(staging_dir).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in sorted((staging_dir / "normalized").glob("*.json"))
        }
        metadata_path = staging_dir / "metadata" / "capture.json"
        metadata_path.unlink()
        _write_json(metadata_path, metadata)
        validation_path = staging_dir / "validation" / "results.json"
        _write_json(validation_path, bundle.validation)
        output_paths["validation"] = run_dir / validation_path.relative_to(staging_dir)

        # os.rename is atomic on the same filesystem and fails if the capture ID exists.
        if run_dir.exists():
            raise FileExistsError(f"La captura ya existe y no se sobrescribirá: {run_dir}")
        os.rename(staging_dir, run_dir)
        output_paths["run_directory"] = run_dir
        output_paths["source_snapshots"] = run_dir / "raw"
        return output_paths
    except BaseException:
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        raise
