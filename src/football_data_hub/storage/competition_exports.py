"""Exportación reproducible a JSON y CSV de la extracción de competición."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from football_data_hub.providers.bdfutbol.competition import PARSER_VERSION

_STANDING_CSV_FIELDS = (
    "group", "position", "position_raw", "team_name", "team_season_id",
    "team_season_url", "points", "played", "wins", "draws", "losses",
    "goals_for", "goals_against", "yellow_cards", "red_cards",
    "stats_raw_json", "source_row_index", "_snapshot_sha256", "_captured_at_utc",
    "_parser_version",
)
_PARTICIPANT_CSV_FIELDS = (
    "group", "team_name", "team_season_id", "team_season_url",
    "standing_position", "_snapshot_sha256", "_captured_at_utc", "_parser_version",
)
_MATCH_CSV_FIELDS = (
    "group", "season", "round", "date", "date_raw", "home_team_name",
    "home_team_season_id", "home_team_season_url", "home_team_reference_method",
    "away_team_name", "away_team_season_id", "away_team_season_url",
    "away_team_reference_method", "fixture_status", "match_state", "match_state_issues",
    "match_state_evidence", "result_status", "result_raw", "home_goals",
    "away_goals", "match_link_status", "match_id", "match_url", "stadium_name", "stadium_id",
    "stadium_url", "referee_name", "referee_id", "referee_url",
    "source_row_index", "_snapshot_sha256", "_captured_at_utc", "_parser_version",
)


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, path)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)


def _write_json(path: Path, value: Any) -> None:
    content = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _atomic_write(path, content.encode("utf-8"))


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: tuple[str, ...]) -> None:
    from io import StringIO

    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    _atomic_write(path, buffer.getvalue().encode("utf-8"))


def _provenance(snapshot: Any) -> dict[str, str | None]:
    return {
        "snapshot_sha256": snapshot.sha256,
        "captured_at_utc": snapshot.metadata.get("captured_at_utc"),
        "parser_version": PARSER_VERSION,
    }


def _with_provenance(row: dict[str, Any], snapshot: Any) -> dict[str, Any]:
    return {
        **row,
        "_snapshot_sha256": snapshot.sha256,
        "_captured_at_utc": snapshot.metadata.get("captured_at_utc"),
        "_parser_version": PARSER_VERSION,
    }


def _flatten_standing(row: dict[str, Any], snapshot: Any) -> dict[str, Any]:
    return {
        **_with_provenance(row, snapshot),
        **row["stats"],
        "stats_raw_json": json.dumps(row["stats_raw"], ensure_ascii=False, sort_keys=True),
    }


def _flatten_quality(quality: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for group in quality["groups"]:
        observed = group["observed"]
        expected = group["expected"]
        rows.append({
            "scope": f"group_{group['group'].lower()}",
            "group": group["group"],
            "access_status": group["access_status"],
            "teams_observed": observed["teams"],
            "teams_expected": expected["teams"],
            "rounds_observed": observed["rounds"],
            "rounds_expected": expected["rounds"],
            "matches_observed": observed["matches"],
            "matches_expected": expected["matches"],
            "played_matches": observed["played_matches"],
            "scheduled_matches": observed["scheduled_matches"],
            "unresolved_matches": observed["unresolved_matches"],
            "inconsistent_matches": observed["inconsistent_matches"],
            "scheduled_without_published_id": observed["scheduled_matches_without_published_id"],
            "unresolved_without_published_id": observed["unresolved_matches_without_published_id"],
            "missing_dates": observed["missing_match_dates"],
            "duplicate_match_ids": len(observed["duplicate_match_ids"]),
            "unresolved_team_refs": observed["fixture_team_references_unresolved"],
            "fixture_coverage_complete": group["fixture_coverage_complete"],
            "source_snapshot_sha256": group["snapshot_sha256"],
            "source_captured_at_utc": group["snapshot_captured_at_utc"],
            "parser_version": quality["parser_version"],
        })
    observed = quality["observed"]
    expected = quality["expected"]
    rows.append({
        "scope": "total",
        "group": "",
        "access_status": "VALID" if quality["access_valid_for_all_groups"] else "INCOMPLETE",
        "teams_observed": observed["teams_total"],
        "teams_expected": expected["groups"] * expected["teams_per_group"],
        "rounds_observed": sum(group["observed"]["rounds"] for group in quality["groups"]),
        "rounds_expected": expected["groups"] * expected["rounds_per_group"],
        "matches_observed": observed["matches_total"],
        "matches_expected": expected["matches_total"],
        "played_matches": sum(group["observed"]["played_matches"] for group in quality["groups"]),
        "scheduled_matches": sum(group["observed"]["scheduled_matches"] for group in quality["groups"]),
        "unresolved_matches": sum(group["observed"]["unresolved_matches"] for group in quality["groups"]),
        "inconsistent_matches": sum(group["observed"]["inconsistent_matches"] for group in quality["groups"]),
        "scheduled_without_published_id": sum(
            group["observed"]["scheduled_matches_without_published_id"]
            for group in quality["groups"]
        ),
        "unresolved_without_published_id": sum(
            group["observed"]["unresolved_matches_without_published_id"]
            for group in quality["groups"]
        ),
        "missing_dates": sum(group["observed"]["missing_match_dates"] for group in quality["groups"]),
        "duplicate_match_ids": sum(len(group["observed"]["duplicate_match_ids"]) for group in quality["groups"]),
        "unresolved_team_refs": sum(group["observed"]["fixture_team_references_unresolved"] for group in quality["groups"]),
        "fixture_coverage_complete": quality["coverage_complete"],
        "source_snapshot_sha256": ";".join(
            group["snapshot_sha256"] or "" for group in quality["groups"]
        ),
        "source_captured_at_utc": ";".join(
            group["snapshot_captured_at_utc"] or "" for group in quality["groups"]
        ),
        "parser_version": quality["parser_version"],
    })
    return rows


def write_competition_exports(
    *,
    parsed_groups: list[dict[str, Any]],
    snapshots_by_group: dict[str, Any],
    quality: dict[str, Any],
    output_root: Path,
) -> Path:
    """Escribe salidas bajo una clave de contenido; reprocesar actualiza la misma."""
    ordered_groups = sorted(parsed_groups, key=lambda item: str(item["competition"]["group"]))
    digest_input = "|".join(
        f"{group}:{snapshots_by_group[group].sha256}" for group in ("I", "II")
    ) + f"|parser:{PARSER_VERSION}"
    extraction_key = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()[:20]
    output_dir = output_root / f"snapshot-{extraction_key}-parser-{PARSER_VERSION}"
    source_snapshots = {
        group: {
            "path": str(snapshots_by_group[group].directory),
            **_provenance(snapshots_by_group[group]),
            "requested_url": snapshots_by_group[group].metadata.get("requested_url"),
            "final_url": snapshots_by_group[group].metadata.get("final_url"),
            "http_status": snapshots_by_group[group].metadata.get("http_status"),
            "access_status": snapshots_by_group[group].metadata.get("access_status"),
        }
        for group in ("I", "II")
    }
    export_metadata = {
        "schema_version": "football_data_hub.competition_export.v1",
        "extraction_key": extraction_key,
        "parser_version": PARSER_VERSION,
        "season": "2026/27",
        "source_snapshots": source_snapshots,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "dataset_metadata.json", export_metadata)

    competition_rows = [
        {**item["competition"], **_provenance(snapshots_by_group[str(item["competition"]["group"])])}
        for item in ordered_groups
    ]
    _write_json(output_dir / "competition_groups.json", {**export_metadata, "items": competition_rows})
    _write_csv(
        output_dir / "competition_groups.csv",
        competition_rows,
        (
            "provider", "name", "source_name", "source_title", "season", "season_source",
            "group", "group_source", "url", "source_route_id", "snapshot_sha256",
            "captured_at_utc", "parser_version",
        ),
    )

    participant_rows: list[dict[str, Any]] = []
    for item in ordered_groups:
        group = str(item["competition"]["group"])
        participant_rows.extend(
            _with_provenance(row, snapshots_by_group[group]) for row in item["participants"]
        )
    _write_json(output_dir / "participants.json", {**export_metadata, "items": participant_rows})
    _write_csv(output_dir / "participants.csv", participant_rows, _PARTICIPANT_CSV_FIELDS)

    for item in ordered_groups:
        group = str(item["competition"]["group"])
        suffix = group.lower()
        snapshot = snapshots_by_group[group]
        standings = item["standings"]
        _write_json(
            output_dir / f"standings_group_{suffix}.json",
            {**export_metadata, "group": group, "items": standings},
        )
        _write_csv(
            output_dir / f"standings_group_{suffix}.csv",
            [_flatten_standing(row, snapshot) for row in standings],
            _STANDING_CSV_FIELDS,
        )
        matches = item["matches"]
        match_rows = [_with_provenance(row, snapshot) for row in matches]
        _write_json(
            output_dir / f"matches_group_{suffix}.json",
            {**export_metadata, "group": group, "items": matches},
        )
        _write_csv(output_dir / f"matches_group_{suffix}.csv", match_rows, _MATCH_CSV_FIELDS)

    _write_json(output_dir / "quality_coverage.json", quality)
    quality_rows = _flatten_quality(quality)
    quality_fields = (
        "scope", "group", "access_status", "teams_observed", "teams_expected",
        "rounds_observed", "rounds_expected", "matches_observed", "matches_expected",
        "played_matches", "scheduled_matches", "scheduled_without_published_id",
        "unresolved_matches", "inconsistent_matches", "unresolved_without_published_id", "missing_dates",
        "duplicate_match_ids",
        "unresolved_team_refs", "fixture_coverage_complete", "source_snapshot_sha256",
        "source_captured_at_utc", "parser_version",
    )
    _write_csv(output_dir / "quality_coverage.csv", quality_rows, quality_fields)
    return output_dir
