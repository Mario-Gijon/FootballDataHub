#!/usr/bin/env python3
"""Build a deduplicated, offline entity inventory from parsed exports and raw metadata."""

from __future__ import annotations

import argparse
import gzip
import json
import os
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from football_data_hub.audits.entity_inventory import (
    EntityInventoryBuilder,
    acquisition_status,
    build_position_code_catalog,
    identify_entity_url,
)
from football_data_hub.dev_explorer.data import (
    _stream_gzip_json_items,
    discover_club_exports,
    discover_player_exports,
    latest_valid_club_export,
    latest_valid_player_export,
)

GENERATOR_VERSION = "1.0.0"
CLUB_RELATION_FIELDS = {
    "entity_id", "entity_type", "name", "url", "source_entity_id", "source_entity_type",
    "source_row_index", "source_table_id", "source_table_index", "source_column_index",
    "source_root_index", "source_snapshot_sha256", "source_url", "source_view", "source_variant_id",
}
MATCH_FIELDS = {
    "match_id", "match_url", "date", "date_raw", "season_raw", "match_season_raw",
    "competition_code_raw", "round_code_raw", "round_label_raw", "home_club_id", "away_club_id",
    "home_team_name_raw", "away_team_name_raw", "home_goals", "away_goals", "referee_id_raw",
    "source_observation_count", "team_season_identity_status",
}
OBSERVATION_FIELDS = {
    "match_id", "source_club_id", "source_team_season_id", "source_record_index", "captured_at_utc",
    "snapshot_sha256", "url", "source_kind",
}
RELATIONSHIP_FIELDS = {
    "related_entity_id", "related_entity_type", "related_name_raw", "player_id", "page_view",
    "table_role", "table_id", "source_row_index", "source_column_index", "source_table_index",
    "source_url", "source_snapshot_directory", "source_snapshot_sha256", "source_view", "url",
}

FIELD_COVERAGE: dict[str, dict[str, list[str]]] = {
    "match": {
        "normalized_or_structured": ["match_id", "date", "home_club_id", "away_club_id", "home_goals", "away_goals"],
        "raw_only_or_source_labeled": ["date_raw", "season_raw", "competition_code_raw", "round_code_raw", "round_label_raw", "referee_id_raw", "home_team_name_raw", "away_team_name_raw"],
        "pending_or_not_present": ["stadium_id", "lineups", "substitutions", "goals_and_cards_as_match_events", "individual_match_detail_fields"],
    },
    "coach": {
        "normalized_or_structured": ["coach_id", "club_id", "team_season_id"],
        "raw_only_or_source_labeled": ["name_raw", "birth_date_raw", "coach_url"],
        "pending_or_not_present": ["captured_individual_profile", "career_history", "season_by_season_match_stats"],
    },
    "referee": {
        "normalized_or_structured": [],
        "raw_only_or_source_labeled": ["referee_id_raw", "candidate_profile_url_from_observed_pattern"],
        "pending_or_not_present": ["captured_individual_profile", "designations", "career_match_stats"],
    },
    "stadium": {
        "normalized_or_structured": ["stadium_id_from_source_link"],
        "raw_only_or_source_labeled": ["name_raw", "profile_url"],
        "pending_or_not_present": ["captured_individual_profile", "capacity_and_facilities_if_published", "match_to_stadium_relation"],
    },
    "player": {
        "normalized_or_structured": ["player_id", "club_id", "team_season_id", "appearances"],
        "raw_only_or_source_labeled": ["name_raw", "position_raw", "shirt_number_raw", "birth_date_raw", "player_url"],
        "pending_or_not_present": ["profile_for_uncaptured_player", "complete_career", "all_required_views"],
    },
    "club": {
        "normalized_or_structured": ["club_id", "current_team_season_id"],
        "raw_only_or_source_labeled": ["name_raw", "profile_url"],
        "pending_or_not_present": ["unacquired_historical_club_profile", "historical_team_season_identity_resolution"],
    },
    "team_season": {
        "normalized_or_structured": ["team_season_id", "current_club_id", "current_group_when_consensual"],
        "raw_only_or_source_labeled": ["team_name_raw", "season_raw", "source_link_url"],
        "pending_or_not_present": ["historical_team_season_page", "historical_current_club_resolution"],
    },
}


def _read_gzip_json(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise ValueError(f"Se esperaba un objeto JSON en {path}")
    return value


def _items(path: Path, keep_fields: set[str] | None = None) -> list[dict[str, Any]]:
    _, items, _ = _stream_gzip_json_items(path, keep_fields=keep_fields)
    return items


def _source_path(value: Any, repo_root: Path) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    if path.is_absolute():
        try:
            return path.resolve().relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            return path.as_posix()
    return path.as_posix()


def _source_reference(
    *,
    dataset: str,
    resource: str,
    repo_root: Path,
    row: dict[str, Any],
    source_entity_type: str | None = None,
    source_entity_id: str | None = None,
    observed_target_url: str | None = None,
) -> dict[str, Any]:
    source = row.get("source") if isinstance(row.get("source"), dict) else {}
    values = {
        "dataset": dataset,
        "resource": resource,
        "source_entity_type": source_entity_type or row.get("source_entity_type"),
        "source_entity_id": source_entity_id or row.get("source_entity_id"),
        "source_view": row.get("source_view") or row.get("page_view") or source.get("view"),
        "source_url": row.get("source_url") or source.get("final_url"),
        "observed_target_url": observed_target_url,
        "snapshot_directory": _source_path(
            source.get("snapshot_directory") or row.get("source_snapshot_directory") or row.get("snapshot_directory"),
            repo_root,
        ),
        "snapshot_sha256": (
            source.get("rendered_html_sha256") or row.get("source_snapshot_sha256")
            or row.get("snapshot_sha256") or row.get("rendered_html_sha256")
        ),
        "captured_at_utc": source.get("captured_at_utc") or row.get("captured_at_utc"),
        "source_row_index": (
            row.get("source_row_index")
            if row.get("source_row_index") is not None
            else row.get("source_record_index")
        ),
        "source_table_id": row.get("source_table_id") or row.get("table_id"),
        "source_table_role": row.get("table_role"),
        "source_table_index": row.get("source_table_index"),
        "source_column_index": row.get("source_column_index"),
    }
    return {key: value for key, value in values.items() if value is not None}


def _add_edge(
    builder: EntityInventoryBuilder,
    source_type: str,
    source_id: Any,
    target_type: str,
    target_id: Any,
    *,
    role: str,
    evidence: dict[str, Any],
    target_url: str | None = None,
    target_name: str | None = None,
) -> None:
    if source_id in (None, "") or target_id in (None, ""):
        return
    edge = {
        "source_entity_type": source_type,
        "source_entity_id": str(source_id),
        "target_entity_type": target_type,
        "target_entity_id": str(target_id),
        "relation_role": role,
        "evidence": evidence,
    }
    builder.add(
        source_type,
        str(source_id),
        relationship=edge,
    )
    builder.add(
        target_type,
        str(target_id),
        url=target_url,
        source_reference=evidence,
        relationship=edge,
        display_name_raw=target_name,
    )


def _load_raw_capture_index(raw_root: Path, repo_root: Path) -> tuple[dict[tuple[str, str], list[dict[str, Any]]], Counter[str]]:
    captures: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    page_counts: Counter[str] = Counter()
    for metadata_path in sorted(raw_root.rglob("metadata.json")):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        url = metadata.get("final_url") or metadata.get("requested_url")
        identified = identify_entity_url(str(url or ""))
        if not identified:
            continue
        entity_type = identified["entity_type"]
        entity_id = identified["entity_id"]
        view = identified["view"]
        html_path = metadata_path.parent / "rendered.html"
        capture = {
            "view": view,
            "requested_url": metadata.get("requested_url"),
            "final_url": metadata.get("final_url"),
            "access_status": metadata.get("access_status"),
            "http_status": metadata.get("http_status"),
            "page_title": metadata.get("page_title"),
            "rendered_html_sha256": metadata.get("rendered_html_sha256"),
            "rendered_html_bytes": metadata.get("rendered_html_bytes"),
            "rendered_html_exists": html_path.is_file(),
            "snapshot_metadata_path": _source_path(str(metadata_path), repo_root),
            "snapshot_directory": _source_path(str(metadata_path.parent), repo_root),
            "snapshot_html_path": _source_path(str(html_path), repo_root) if html_path.is_file() else None,
            "captured_at_utc": metadata.get("captured_at_utc"),
        }
        captures[(entity_type, entity_id)].append(capture)
        page_counts[entity_type] += 1
    return captures, page_counts


def _load_club_profiles(club_export: Path, builder: EntityInventoryBuilder, repo_root: Path) -> int:
    count = 0
    profile_root = club_export / "pages" / "club"
    for profile_path in sorted(profile_root.glob("*/club_profile.json.gz")):
        try:
            profile = _read_gzip_json(profile_path)
        except (OSError, EOFError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            continue
        club_id = profile.get("entity_id")
        if not club_id or profile.get("entity_type") != "club":
            continue
        source = profile.get("source", {})
        evidence = {
            "dataset": _source_path(str(club_export), repo_root),
            "resource": _source_path(str(profile_path.relative_to(club_export)), repo_root),
            "source_url": profile.get("url"),
            "snapshot_directory": _source_path(source.get("snapshot_directory"), repo_root),
            "snapshot_sha256": source.get("rendered_html_sha256"),
            "captured_at_utc": source.get("captured_at_utc"),
            "evidence_kind": "parsed_club_profile",
        }
        builder.add(
            "club",
            str(club_id),
            url=profile.get("url"),
            source_reference=evidence,
            display_name_raw=profile.get("title"),
            fields_available=("club_id", "profile_title_raw", "hero_text_raw"),
        )
        count += 1
    return count


def _add_club_relationships(
    builder: EntityInventoryBuilder,
    rows: Iterable[dict[str, Any]],
    repo_root: Path,
) -> Counter[str]:
    source_counts: Counter[str] = Counter()
    for row in rows:
        entity_type = str(row.get("entity_type") or "")
        entity_id = row.get("entity_id")
        source_type = str(row.get("source_entity_type") or "")
        source_id = row.get("source_entity_id")
        if entity_type not in {"player", "coach", "club", "match", "stadium", "team_season"} or not entity_id:
            continue
        target_url = row.get("url")
        evidence = _source_reference(
            dataset="club_team_export",
            resource="relationships.json.gz",
            repo_root=repo_root,
            row=row,
            observed_target_url=target_url,
        )
        builder.add(
            entity_type,
            str(entity_id),
            url=target_url,
            source_reference=evidence,
            display_name_raw=row.get("name") if entity_type != "match" else None,
            fields_available=("source_link_reference",),
        )
        if source_type and source_id:
            role = f"source_link:{row.get('source_view') or 'unknown_view'}"
            _add_edge(
                builder,
                source_type,
                source_id,
                entity_type,
                entity_id,
                role=role,
                evidence=evidence,
                target_url=target_url,
                target_name=row.get("name"),
            )
        source_counts[entity_type] += 1
    return source_counts


def _add_player_relationships(
    builder: EntityInventoryBuilder,
    rows: Iterable[dict[str, Any]],
    repo_root: Path,
) -> Counter[str]:
    source_counts: Counter[str] = Counter()
    for row in rows:
        entity_type = str(row.get("related_entity_type") or "")
        entity_id = row.get("related_entity_id")
        player_id = row.get("player_id")
        if entity_type not in {"player", "coach", "club", "match", "team_season"} or not entity_id:
            continue
        source = row.get("source") if isinstance(row.get("source"), dict) else {}
        evidence = _source_reference(
            dataset="player_export",
            resource="relationships.json.gz",
            repo_root=repo_root,
            row={**row, "source_url": source.get("final_url"), "source_snapshot_directory": source.get("snapshot_directory"), "source_snapshot_sha256": source.get("rendered_html_sha256"), "captured_at_utc": source.get("captured_at_utc")},
            source_entity_type="player",
            source_entity_id=str(player_id or ""),
            observed_target_url=row.get("url"),
        )
        builder.add(
            entity_type,
            str(entity_id),
            url=row.get("url"),
            source_reference=evidence,
            display_name_raw=row.get("related_name_raw") if entity_type != "match" else None,
            fields_available=("player_page_relationship",),
        )
        if player_id:
            _add_edge(
                builder,
                "player",
                player_id,
                entity_type,
                entity_id,
                role=f"player_page:{row.get('table_role') or row.get('page_view') or 'related'}",
                evidence=evidence,
                target_url=row.get("url"),
                target_name=row.get("related_name_raw"),
            )
        source_counts[entity_type] += 1
    return source_counts


def _add_memberships(
    builder: EntityInventoryBuilder,
    rows: Iterable[dict[str, Any]],
    repo_root: Path,
) -> None:
    for row in rows:
        evidence = _source_reference(
            dataset="player_export",
            resource="memberships.json.gz",
            repo_root=repo_root,
            row={**row, "source_url": row.get("url")},
            source_entity_type="team_season",
            source_entity_id=str(row.get("team_season_id") or ""),
            observed_target_url=row.get("player_url"),
        )
        player_id = row.get("player_id")
        club_id = row.get("club_id")
        team_id = row.get("team_season_id")
        if not player_id:
            continue
        builder.add(
            "player",
            str(player_id),
            url=row.get("player_url"),
            source_reference=evidence,
            display_name_raw=row.get("name_raw"),
            fields_available=("player_id", "position_raw", "shirt_number_raw", "appearances_raw", "birth_date_raw"),
            fields_pending=("individual_profile",),
        )
        if club_id:
            _add_edge(builder, "player", player_id, "club", club_id, role="membership_2026_27", evidence=evidence, target_url=None, target_name=row.get("team_name"))
        if team_id:
            _add_edge(builder, "player", player_id, "team_season", team_id, role="membership_2026_27", evidence=evidence, target_url=row.get("url"), target_name=row.get("team_name"))
        if club_id and team_id:
            _add_edge(builder, "team_season", team_id, "club", club_id, role="current_team_identity_2026_27", evidence=evidence, target_url=None, target_name=row.get("team_name"))


def _add_current_coaches(
    builder: EntityInventoryBuilder,
    rows: Iterable[dict[str, Any]],
    repo_root: Path,
) -> None:
    for row in rows:
        evidence = _source_reference(
            dataset="club_team_export",
            resource="sports/coaches_current.json.gz",
            repo_root=repo_root,
            row={**row, "source_url": row.get("url")},
            source_entity_type="team_season",
            source_entity_id=str(row.get("team_season_id") or ""),
            observed_target_url=row.get("coach_url"),
        )
        coach_id = row.get("coach_id")
        if not coach_id:
            continue
        builder.add(
            "coach",
            str(coach_id),
            url=row.get("coach_url"),
            source_reference=evidence,
            display_name_raw=row.get("name_raw"),
            fields_available=("coach_id", "name_raw", "birth_date_raw", "club_id", "team_season_id"),
            fields_pending=("individual_profile", "career_history", "season_statistics"),
        )
        if row.get("club_id"):
            _add_edge(builder, "coach", coach_id, "club", row["club_id"], role="current_staff_2026_27", evidence=evidence, target_url=row.get("coach_url"), target_name=row.get("name_raw"))
        if row.get("team_season_id"):
            _add_edge(builder, "coach", coach_id, "team_season", row["team_season_id"], role="current_staff_2026_27", evidence=evidence, target_url=row.get("coach_url"), target_name=row.get("name_raw"))


def _add_matches(
    builder: EntityInventoryBuilder,
    match_rows: Iterable[dict[str, Any]],
    observations: Iterable[dict[str, Any]],
    repo_root: Path,
) -> tuple[int, int]:
    observation_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for observation in observations:
        match_id = str(observation.get("match_id") or "")
        if match_id:
            observation_rows[match_id].append(observation)
    count = 0
    referee_references = 0
    for row in match_rows:
        match_id = str(row.get("match_id") or "")
        if not match_id:
            continue
        url = row.get("match_url")
        base_evidence = {
            "dataset": "club_team_export",
            "resource": "sports/matches_from_embedded_data.json.gz",
            "source_row_match_id": match_id,
            "evidence_kind": "parsed_unique_match_index",
        }
        builder.add(
            "match",
            match_id,
            url=url,
            source_reference=base_evidence,
            display_name_raw=f"{row.get('home_team_name_raw') or ''} - {row.get('away_team_name_raw') or ''}".strip(" -"),
            fields_available=("match_id", "date", "home_club_id", "away_club_id", "home_goals", "away_goals", "referee_id_raw"),
            fields_pending=("stadium_id", "lineups", "match_events"),
        )
        for observation in observation_rows.get(match_id, []):
            evidence = _source_reference(
                dataset="club_team_export",
                resource="sports/embedded_match_observations.json.gz",
                repo_root=repo_root,
                row={**observation, "source_url": observation.get("url")},
                source_entity_type="club",
                source_entity_id=str(observation.get("source_club_id") or ""),
                observed_target_url=url,
            )
            builder.add("match", match_id, url=url, source_reference=evidence)
        for role, field in (("home", "home_club_id"), ("away", "away_club_id")):
            club_id = row.get(field)
            if club_id:
                _add_edge(builder, "match", match_id, "club", club_id, role=role, evidence=base_evidence)
        referee_id = row.get("referee_id_raw")
        if referee_id not in (None, ""):
            referee_references += 1
            evidence = {**base_evidence, "field": "referee_id_raw"}
            _add_edge(builder, "match", match_id, "referee", str(referee_id), role="referee_id_raw", evidence=evidence)
            builder.add(
                "referee", str(referee_id), fields_available=("referee_id_raw",),
                fields_pending=("individual_profile", "designations", "career_match_stats"),
            )
        count += 1
    return count, referee_references


def _add_player_data(
    builder: EntityInventoryBuilder,
    *,
    player_export: Path,
    repo_root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    players = _items(player_export / "players.json.gz")
    profiles = _items(player_export / "profiles.json.gz")
    memberships = _items(player_export / "memberships.json.gz")
    coverage = _items(player_export / "coverage.json.gz")
    relationships = _items(player_export / "relationships.json.gz", RELATIONSHIP_FIELDS)
    individual_matches = _items(player_export / "individual_matches.json.gz")

    for row in players:
        player_id = row.get("player_id")
        if player_id:
            url = row.get("player_url") or row.get("url")
            evidence = _source_reference(
                dataset="player_export",
                resource="players.json.gz",
                repo_root=repo_root,
                row=row,
                observed_target_url=url,
            )
            builder.add("player", str(player_id), url=url, source_reference=evidence, display_name_raw=row.get("name_raw") or row.get("display_name_raw"), fields_available=("player_id", "current_roster_presence"))
    for row in profiles:
        player_id = row.get("player_id")
        if not player_id:
            continue
        source = row.get("source") if isinstance(row.get("source"), dict) else {}
        evidence = _source_reference(
            dataset="player_export",
            resource="profiles.json.gz",
            repo_root=repo_root,
            row={**row, "source": source},
            observed_target_url=source.get("final_url"),
        )
        builder.add(
            "player", str(player_id), url=source.get("final_url"), source_reference=evidence,
            display_name_raw=row.get("display_name_raw"),
            fields_available=("display_name_raw", "full_name_raw", "position_raw", "trajectory_raw", "photo_references"),
        )
    _add_memberships(builder, memberships, repo_root)
    for row in coverage:
        player_id = row.get("player_id")
        if not player_id:
            continue
        evidence = {
            "dataset": "player_export",
            "resource": "coverage.json.gz",
            "view": row.get("view"),
            "requested_url": row.get("requested_url"),
            "snapshot_status": row.get("snapshot_status"),
            "coverage_status": row.get("coverage_status"),
            "snapshot_directory": _source_path(row.get("selected_snapshot_directory"), repo_root),
            "snapshot_sha256": row.get("selected_snapshot_sha256"),
        }
        builder.add(
            "player", str(player_id), url=row.get("requested_url"), source_reference=evidence,
            fields_available=("profile_view_coverage",),
            fields_pending=("complete_profile_views",) if row.get("snapshot_status") == "PENDING_CAPTURE" else (),
        )
    player_relation_counts = _add_player_relationships(builder, relationships, repo_root)
    for row in individual_matches:
        match_id = row.get("match_id")
        player_id = row.get("player_id")
        if not match_id:
            continue
        source = row.get("source") if isinstance(row.get("source"), dict) else {}
        evidence = _source_reference(
            dataset="player_export",
            resource="individual_matches.json.gz",
            repo_root=repo_root,
            row={**row, "source": source},
            source_entity_type="player",
            source_entity_id=str(player_id or ""),
            observed_target_url=row.get("match_url"),
        )
        builder.add("match", str(match_id), url=row.get("match_url"), source_reference=evidence, fields_available=("player_individual_match_row",))
        if player_id:
            _add_edge(builder, "player", player_id, "match", match_id, role="player_match_row", evidence=evidence, target_url=row.get("match_url"))
        for role, field in (("home", "home_club_id_raw"), ("away", "away_club_id_raw")):
            if row.get(field):
                _add_edge(builder, "match", match_id, "club", str(row[field]), role=role, evidence=evidence)
    stats = {
        "player_rows": len(players),
        "profiles_parsed": len(profiles),
        "membership_rows": len(memberships),
        "coverage_rows": len(coverage),
        "individual_match_rows": len(individual_matches),
        "individual_match_unique_ids": len({str(row.get("match_id")) for row in individual_matches if row.get("match_id")}),
        "player_relationship_rows_by_type": dict(player_relation_counts),
        "position_catalog": build_position_code_catalog(memberships, profiles),
    }
    return players, profiles, memberships, {**stats, "player_relationships": relationships, "individual_matches": individual_matches}


def _load_capture_records(
    captures: dict[tuple[str, str], list[dict[str, Any]]],
    entity_type: str,
    entity_id: str,
) -> list[dict[str, Any]]:
    return captures.get((entity_type, entity_id), [])


def _finalize_records(
    builder: EntityInventoryBuilder,
    captures: dict[tuple[str, str], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    output = []
    for record in builder.records():
        entity_type, entity_id = record["entity_type"], record["entity_id"]
        entity_captures = _load_capture_records(captures, entity_type, entity_id)
        if entity_type == "player":
            profile_captures = [item for item in entity_captures if item.get("view") == "profile"]
            page_captures = [item for item in entity_captures if item.get("view") != "profile"]
            status = acquisition_status(profile_captures)
            if status == "PENDING_CAPTURE" and any(acquisition_status([item]) == "CAPTURED_VALID" for item in page_captures):
                status = "PARTIAL_VIEWS_CAPTURED"
        else:
            status = acquisition_status(entity_captures)
        record["acquisition_status"] = status
        field_coverage = FIELD_COVERAGE.get(entity_type, {})
        record["field_coverage"] = field_coverage
        record["fields_pending"] = sorted(set(record["fields_pending"]) | set(field_coverage.get("pending_or_not_present", [])))
        record["capture_views"] = sorted({item.get("view") for item in entity_captures if item.get("view")})
        record["captures"] = sorted(entity_captures, key=lambda item: (str(item.get("view")), str(item.get("captured_at_utc")), str(item.get("final_url"))))
        if entity_type == "referee" and not record["observed_urls"]:
            record["candidate_url"] = f"https://www.bdfutbol.com/es/r/r{entity_id}.html"
            record["url_status"] = "PATTERN_INFERRED_FROM_LOCALLY_CAPTURED_SAMPLE"
        elif record["observed_urls"]:
            record["candidate_url"] = record["observed_urls"][0]
            record["url_status"] = "OBSERVED_IN_LOCAL_SOURCE"
        else:
            record["candidate_url"] = None
            record["url_status"] = "NOT_OBSERVED"
        output.append(record)
    return output


def _write_gzip_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as raw:
            with gzip.GzipFile(filename="", fileobj=raw, mode="wb", compresslevel=6, mtime=0) as compressed:
                compressed.write((json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
            raw.flush()
            os.fsync(raw.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def build_inventory(repo_root: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    club_root = repo_root / "data/parsed/bdfutbol/club_team_2026_27/compact"
    player_root = repo_root / "data/parsed/bdfutbol/player_2026_27/compact"
    raw_root = repo_root / "data/raw/bdfutbol"

    club_export = latest_valid_club_export(discover_club_exports(club_root))
    player_export = latest_valid_player_export(discover_player_exports(player_root))
    if club_export is None or player_export is None:
        raise RuntimeError("No se encontraron exports compactos válidos de clubes y jugadores")
    club_path, player_path = club_export.path, player_export.path
    builder = EntityInventoryBuilder()

    club_meta = _read_gzip_json(club_path / "dataset_metadata.json.gz")
    club_relations = _items(club_path / "relationships.json.gz", CLUB_RELATION_FIELDS)
    relation_counts = _add_club_relationships(builder, club_relations, repo_root)
    del club_relations

    club_people = _items(club_path / "club_people.json.gz")
    people_counts: Counter[str] = Counter()
    for row in club_people:
        entity_type = "player" if row.get("person_type") == "player" else "coach" if row.get("person_type") == "coach" else ""
        person_id = row.get("person_id")
        if not entity_type or not person_id:
            continue
        evidence = _source_reference(
            dataset="club_team_export", resource="club_people.json.gz", repo_root=repo_root,
            row=row, source_entity_type="club", source_entity_id=str(row.get("club_id") or ""),
            observed_target_url=row.get("url"),
        )
        builder.add(entity_type, str(person_id), url=row.get("url"), source_reference=evidence, display_name_raw=row.get("name_raw"), fields_available=("source_person_reference",))
        if row.get("club_id"):
            _add_edge(builder, "club", row["club_id"], entity_type, person_id, role=f"club_people:{row.get('registry_view') or 'unknown'}", evidence=evidence, target_url=row.get("url"), target_name=row.get("name_raw"))
        people_counts[entity_type] += 1
    del club_people

    current_clubs = _items(club_path / "sports/embedded_match_coverage_by_club.json.gz")
    for row in current_clubs:
        club_id = row.get("club_id")
        if club_id:
            builder.add("club", str(club_id), source_reference={
                "dataset": "club_team_export", "resource": "sports/embedded_match_coverage_by_club.json.gz",
                "current_team_season_id": row.get("team_season_id"),
            }, fields_available=("current_club_participant",))
            if row.get("team_season_id"):
                _add_edge(builder, "club", club_id, "team_season", row["team_season_id"], role="current_team_identity_2026_27", evidence={"dataset": "club_team_export", "resource": "sports/embedded_match_coverage_by_club.json.gz"})
    profile_count = _load_club_profiles(club_path, builder, repo_root)

    rosters = _items(club_path / "sports/rosters.json.gz")
    for row in rosters:
        player_id = row.get("player_id")
        if player_id:
            evidence = _source_reference(dataset="club_team_export", resource="sports/rosters.json.gz", repo_root=repo_root, row={**row, "source_url": row.get("url")}, source_entity_type="team_season", source_entity_id=str(row.get("team_season_id") or ""), observed_target_url=row.get("player_url"))
            builder.add("player", str(player_id), url=row.get("player_url"), source_reference=evidence, display_name_raw=row.get("name_raw"), fields_available=("player_id", "position_raw", "shirt_number_raw", "appearances_raw"))
            if row.get("team_season_id"):
                _add_edge(builder, "team_season", row["team_season_id"], "player", player_id, role="roster_2026_27", evidence=evidence, target_url=row.get("player_url"), target_name=row.get("name_raw"))
            if row.get("club_id"):
                _add_edge(builder, "club", row["club_id"], "player", player_id, role="roster_2026_27", evidence=evidence, target_url=row.get("player_url"), target_name=row.get("name_raw"))

    coaches = _items(club_path / "sports/coaches_current.json.gz")
    _add_current_coaches(builder, coaches, repo_root)
    matches = _items(club_path / "sports/matches_from_embedded_data.json.gz", MATCH_FIELDS)
    observations = _items(club_path / "sports/embedded_match_observations.json.gz", OBSERVATION_FIELDS)
    observation_count = len(observations)
    unique_match_count, referee_reference_count = _add_matches(builder, matches, observations, repo_root)
    del observations, matches

    players, profiles, memberships, player_stats = _add_player_data(builder, player_export=player_path, repo_root=repo_root)
    player_stats.pop("player_relationships")
    player_stats.pop("individual_matches")
    del players, profiles, memberships

    # Historical/current team-season references, clubs, and people from source-linked rows
    # are already represented above. Include all page captures for acquisition state.
    captures, raw_page_counts = _load_raw_capture_index(raw_root, repo_root)
    for (entity_type, entity_id), entity_captures in captures.items():
        if entity_type in {"match", "coach", "referee", "stadium", "player", "club", "team_season"}:
            for capture in entity_captures:
                builder.add(entity_type, entity_id, url=capture.get("final_url"), source_reference={
                    "dataset": "raw_snapshot_metadata",
                    "resource": capture.get("snapshot_metadata_path"),
                    "source_url": capture.get("final_url"),
            "snapshot_directory": capture.get("snapshot_directory"),
            "snapshot_html_path": capture.get("snapshot_html_path"),
                    "snapshot_sha256": capture.get("rendered_html_sha256"),
                    "captured_at_utc": capture.get("captured_at_utc"),
                })

    records = _finalize_records(builder, captures)
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_type[record["entity_type"]].append(record)
    summary = {}
    for entity_type in sorted(by_type):
        entity_records = by_type[entity_type]
        status_counts = Counter(item["acquisition_status"] for item in entity_records)
        summary[entity_type] = {
            "unique_ids": len(entity_records),
            "source_reference_records": sum(item["source_reference_count"] for item in entity_records),
            "ids_with_observed_url": sum(bool(item["observed_urls"]) for item in entity_records),
            "acquisition_status_counts": dict(sorted(status_counts.items())),
        }

    coverage = club_meta.get("competition_crosscheck_source", {})
    selection = coverage.get("selection", {}) if isinstance(coverage, dict) else {}
    crosscheck_document = _read_gzip_json(club_path / "sports/embedded_match_competition_crosscheck.json.gz")
    crosscheck = crosscheck_document.get("status")
    player_metadata = _read_gzip_json(player_path / "dataset_metadata.json.gz")
    inventory = {
        "schema_version": "football_data_hub.offline_entity_inventory.v1",
        "generator_version": GENERATOR_VERSION,
        "network_access": "NOT_USED",
        "generated_from": {
            "club_export": {"path": _source_path(str(club_path), repo_root), "parser_version": club_meta.get("parser_version"), "extraction_key": club_meta.get("extraction_key"), "schema_version": club_meta.get("schema_version")},
            "player_export": {"path": _source_path(str(player_path), repo_root), "parser_version": player_metadata.get("parser_version"), "schema_version": player_metadata.get("schema_version")},
            "raw_root": _source_path(str(raw_root), repo_root),
        },
        "competition_reference_state": {
            "selection_status": selection.get("selection_status"),
            "crosscheck_status": crosscheck,
            "candidate_conflict_count": sum(len(item.get("conflicts", [])) for item in selection.get("candidate_conflicts", [])),
            "candidate_extraction_keys": sorted({
                str(key)
                for candidate in selection.get("valid_candidates", [])
                if isinstance(candidate, dict)
                for key in [candidate.get("extraction_key")]
                if key
            }),
            "candidate_conflicts": selection.get("candidate_conflicts", []),
            "no_source_selected": selection.get("selection_status") == "AMBIGUOUS_VALID_SOURCES",
        },
        "raw_metadata_page_counts_by_url_family": dict(sorted(raw_page_counts.items())),
        "source_row_counts": {
            "club_relationship_rows_by_type": dict(sorted(relation_counts.items())),
            "club_people_rows_by_type": dict(sorted(people_counts.items())),
            "current_club_profile_pages_parsed": profile_count,
            "current_roster_rows": len(rosters),
            "current_coach_rows": len(coaches),
            "club_unique_match_ids": unique_match_count,
            "club_match_source_observations": observation_count,
            "club_match_rows_with_referee_id": referee_reference_count,
            "player_export": {key: value for key, value in player_stats.items() if key != "position_catalog"},
            "player_position_code_catalog": player_stats["position_catalog"],
        },
        "entity_field_coverage": FIELD_COVERAGE,
        "url_pattern_policy": {
            "match": "/es/p/p.php?id={match_id} (URL observada en cada fila de partido)",
            "player_profile": "/es/j/j{numeric_id}.html (observada en roster/export)",
            "coach": "/es/l/l{numeric_id}.html (observada en relaciones)",
            "referee": "/es/r/r{numeric_id}.html (confirmada con una ficha capturada; otros IDs son solo candidatos)",
            "stadium": "/es/s/{numeric_id}.html (observada en relaciones de club)",
            "club": "URLs /es/e/e{id}.html y /es/p/e{id}.html observadas; se conservan por separado",
            "team_season": "/es/t/t{year}-{suffix}.html observada en referencias de trayectoria; no implica identidad histórica de partido",
        },
        "entities_summary": summary,
        "entities": records,
    }
    return inventory


def main() -> int:
    parser = argparse.ArgumentParser(description="Genera catálogo de entidades desde exports y snapshots locales; no usa red.")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=None, help="Destino gzip JSON (por defecto data/analysis/bdfutbol/entity_coverage_audit/entity_inventory.json.gz)")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    output = args.output or repo_root / "data/analysis/bdfutbol/entity_coverage_audit/entity_inventory.json.gz"
    inventory = build_inventory(repo_root)
    _write_gzip_json(output, inventory)
    print(f"Inventario offline: {output}")
    for entity_type, values in inventory["entities_summary"].items():
        print(entity_type, values)
    print(f"Entidades: {len(inventory['entities'])}; comprobación de red: {inventory['network_access']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
