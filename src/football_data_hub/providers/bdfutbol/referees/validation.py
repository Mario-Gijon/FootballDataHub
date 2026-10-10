"""Validación de integridad y cruce exacto con el export de Resultados."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any
from urllib.parse import urlsplit

from .models import ParsedReferees, RefereeStatistics

_REFEREE_ID = re.compile(r"^r\d+$")
_SCOPES = ("all", "group1", "group2")
_STAT_FIELDS = ("matches_officiated", "yellow_cards", "red_cards")


def _profile_id(url: str) -> str | None:
    match = re.search(r"/r/(r\d+)\.html(?:$|[?#])", url)
    return match.group(1) if match else None


def validate_referee_data(parsed: ParsedReferees) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    ids = [referee.referee_id for referee in parsed.referees]
    if len(ids) != len(set(ids)):
        issues.append({"code": "duplicate_referee_id", "message": "El catálogo contiene IDs duplicados."})
    catalog = {referee.referee_id: referee for referee in parsed.referees}
    for referee in parsed.referees:
        parts = urlsplit(referee.profile_url)
        if not _REFEREE_ID.fullmatch(referee.referee_id):
            issues.append({"code": "invalid_referee_id", "message": referee.referee_id})
        if parts.scheme != "https" or parts.hostname != "www.bdfutbol.com":
            issues.append({"code": "invalid_profile_url", "message": referee.referee_id})
        elif _profile_id(referee.profile_url) != referee.referee_id:
            issues.append({"code": "profile_id_mismatch", "message": referee.referee_id})
        if not referee.display_name.strip():
            issues.append({"code": "missing_display_name", "message": referee.referee_id})
        if referee.age_years is not None and not 0 <= referee.age_years <= 120:
            issues.append({"code": "invalid_age", "message": referee.referee_id})
        if referee.photo_url is not None:
            photo = urlsplit(referee.photo_url)
            if photo.scheme != "https" or photo.hostname != "www.bdfutbol.com":
                issues.append({"code": "invalid_photo_url", "message": referee.referee_id})

    stat_keys: set[tuple[str, str, str]] = set()
    stats_by_scope: dict[str, dict[str, RefereeStatistics]] = {scope: {} for scope in _SCOPES}
    for item in parsed.statistics:
        key = (item.referee_id, item.season, item.group_scope)
        if key in stat_keys:
            issues.append({"code": "duplicate_scope_statistics", "message": repr(key)})
        stat_keys.add(key)
        if item.referee_id not in catalog:
            issues.append({"code": "orphan_statistics", "message": item.referee_id})
        if item.season != "2026-27":
            issues.append({"code": "unsupported_season", "message": item.season})
        if item.group_scope not in stats_by_scope:
            issues.append({"code": "unknown_group_scope", "message": str(item.group_scope)})
            continue
        stats_by_scope[item.group_scope][item.referee_id] = item
        for field in _STAT_FIELDS:
            value = getattr(item, field)
            if value is not None and value < 0:
                issues.append({"code": "negative_statistic", "message": f"{item.referee_id}:{field}"})

    if set(parsed.scope_counts) != set(_SCOPES) or any(
        parsed.scope_counts.get(scope, 0) <= 0 for scope in _SCOPES
    ):
        issues.append({"code": "missing_scope_capture", "message": "Falta uno o más ámbitos de temporada."})
    if any(parsed.scope_counts.get(scope) != len(stats_by_scope[scope]) for scope in _SCOPES):
        issues.append({"code": "scope_count_mismatch", "message": "El recuento no coincide con las filas normalizadas."})
    if parsed.identity_conflicts:
        issues.append({"code": "identity_conflict_across_scopes", "message": f"{len(parsed.identity_conflicts)} conflicto(s)."})

    additive_checks = {field: {"compared": 0, "mismatches": []} for field in _STAT_FIELDS}
    all_ids = set(stats_by_scope["all"])
    for referee_id in all_ids:
        all_record = stats_by_scope["all"][referee_id]
        first = stats_by_scope["group1"].get(referee_id)
        second = stats_by_scope["group2"].get(referee_id)
        for field in _STAT_FIELDS:
            actual = getattr(all_record, field)
            one = getattr(first, field) if first else 0
            two = getattr(second, field) if second else 0
            if actual is None or (first and one is None) or (second and two is None):
                warnings.append({
                    "code": "aggregate_check_missing_value",
                    "message": f"{referee_id}:{field} no permite reconciliar todos los ámbitos.",
                })
                continue
            additive_checks[field]["compared"] += 1
            expected = (one or 0) + (two or 0)
            if actual != expected:
                additive_checks[field]["mismatches"].append({
                    "referee_id": referee_id,
                    "all": actual,
                    "group1": one,
                    "group2": two,
                    "group_sum": expected,
                })
    for field, result in additive_checks.items():
        if result["mismatches"]:
            issues.append({
                "code": "scope_aggregate_mismatch",
                "message": f"{field}: {len(result['mismatches'])} discrepancia(s) entre Todos y los grupos.",
            })

    return {
        "valid": not issues,
        "issues": issues,
        "warnings": warnings,
        "summary": {
            "referees": len(parsed.referees),
            "statistics": len(parsed.statistics),
            "scope_counts": parsed.scope_counts,
            "unique_ids": len(set(ids)),
        },
        "checks": {
            "ids_unique": len(ids) == len(set(ids)),
            "profile_ids_match": all(_profile_id(item.profile_url) == item.referee_id for item in parsed.referees),
            "statistics_keys_unique": len(stat_keys) == len(parsed.statistics),
            "all_scopes_present": set(stats_by_scope) == set(_SCOPES)
            and all(stats_by_scope[scope] for scope in _SCOPES),
            "all_equals_group_sum": {
                field: {
                    "compared": values["compared"],
                    "mismatches": values["mismatches"],
                }
                for field, values in additive_checks.items()
            },
        },
    }


def _sum_complete(matches: list[dict[str, Any]], field_names: tuple[str, ...]) -> int | None:
    values = [match.get(field) for match in matches for field in field_names]
    if not values or any(value is None for value in values):
        return None
    if any(not isinstance(value, int) or value < 0 for value in values):
        return None
    return sum(values)


def build_match_reference_report(
    parsed: ParsedReferees,
    matches_payload: dict[str, Any],
    *,
    reference_path: str,
    reference_sha256: str,
    group_scope: str = "group2",
) -> dict[str, Any]:
    """Compara IDs exactos; el informe nunca une por nombre aproximado."""
    if group_scope not in {"group1", "group2"}:
        raise ValueError("group_scope debe ser group1 o group2")
    matches = matches_payload.get("matches")
    if not isinstance(matches, list):
        raise ValueError("El JSON de Resultados no contiene una lista matches")
    played = [match for match in matches if match.get("status") == "played"]
    unplayed = [match for match in matches if match.get("status") != "played"]
    played_with_referee = [match for match in played if match.get("referee_id")]
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for match in played_with_referee:
        referee_id = str(match["referee_id"])
        if not _REFEREE_ID.fullmatch(referee_id):
            continue
        groups[referee_id].append(match)

    scope_statistics = {
        item.referee_id: item
        for item in parsed.statistics
        if item.group_scope == group_scope
    }
    match_ids = set(groups)
    referee_ids = set(scope_statistics)
    identity_conflicts: list[dict[str, Any]] = []
    statistic_differences: list[dict[str, Any]] = []
    for referee_id in sorted(match_ids & referee_ids):
        referee = next(item for item in parsed.referees if item.referee_id == referee_id)
        referee_matches = groups[referee_id]
        for match in referee_matches:
            match_name = match.get("referee_name")
            match_url = match.get("referee_url")
            if match_name and match_name != referee.display_name:
                identity_conflicts.append({
                    "referee_id": referee_id,
                    "field": "display_name",
                    "match_value": match_name,
                    "referee_table_value": referee.display_name,
                    "match_id": match.get("match_id"),
                })
            if match_url and _profile_id(str(match_url)) != referee_id:
                identity_conflicts.append({
                    "referee_id": referee_id,
                    "field": "profile_url_id",
                    "match_value": match_url,
                    "referee_table_value": referee.profile_url,
                    "match_id": match.get("match_id"),
                })
            elif match_url and str(match_url).rstrip("/") != referee.profile_url.rstrip("/"):
                identity_conflicts.append({
                    "referee_id": referee_id,
                    "field": "profile_url",
                    "match_value": match_url,
                    "referee_table_value": referee.profile_url,
                    "match_id": match.get("match_id"),
                })

        expected: dict[str, int | None] = {
            "matches_officiated": len(referee_matches),
            "yellow_cards": _sum_complete(
                referee_matches, ("home_yellow_cards", "away_yellow_cards")
            ),
            "red_cards": _sum_complete(
                referee_matches, ("home_red_cards", "away_red_cards")
            ),
        }
        for field, expected_value in expected.items():
            actual_value = getattr(scope_statistics[referee_id], field)
            if expected_value is not None and actual_value is not None and expected_value != actual_value:
                statistic_differences.append({
                    "referee_id": referee_id,
                    "display_name": referee.display_name,
                    "field": field,
                    "matches_dataset": expected_value,
                    "referees_table": actual_value,
                })

    catalog_only = sorted(referee_ids - match_ids)
    matches_only = sorted(match_ids - referee_ids)
    total_yellow = _sum_complete(played, ("home_yellow_cards", "away_yellow_cards"))
    total_red = _sum_complete(played, ("home_red_cards", "away_red_cards"))
    status = "consistent" if not (catalog_only or matches_only or identity_conflicts or statistic_differences) else "discrepancies"
    reference_metadata = matches_payload.get("metadata", {})
    counts = {
        "source_matches": len(matches),
        "played_matches": len(played),
        "played_matches_with_referee_id": len(played_with_referee),
        "played_matches_without_referee_id": len(played) - len(played_with_referee),
        "unplayed_matches": len(unplayed),
        "unplayed_matches_with_referee_id": sum(bool(match.get("referee_id")) for match in unplayed),
        "unique_match_referee_ids": len(match_ids),
        f"{group_scope}_table_referee_ids": len(referee_ids),
        "matched_referee_ids": len(match_ids & referee_ids),
        f"{group_scope}_table_referees_without_played_match": len(catalog_only),
        f"played_match_referees_missing_from_{group_scope}_table": len(matches_only),
        "played_matches_with_card_data": sum(
            all(match.get(field) is not None for field in (
                "home_yellow_cards", "away_yellow_cards", "home_red_cards", "away_red_cards"
            )) for match in played
        ),
        "played_yellow_cards": total_yellow,
        "played_red_cards": total_red,
    }
    if group_scope == "group2":
        counts.update({
            "group2_table_referee_ids": len(referee_ids),
            "group2_table_referees_without_played_match": len(catalog_only),
            "played_match_referees_missing_from_group2_table": len(matches_only),
        })
    return {
        "status": status,
        "reference_dataset": {
            "path": reference_path,
            "sha256": reference_sha256,
            "source_capture_id": reference_metadata.get("source_capture_id"),
            "source_captured_at_utc": reference_metadata.get("source_captured_at_utc"),
        },
        "method": "exact referee_id; no name-based matching",
        "group_scope": group_scope,
        "counts": counts,
        "matched_referee_ids": sorted(match_ids & referee_ids),
        f"{group_scope}_table_referees_without_played_match_ids": catalog_only,
        f"played_match_referees_missing_from_{group_scope}_table_ids": matches_only,
        "identity_conflicts": identity_conflicts,
        "statistic_differences": statistic_differences,
        "limitations": [
            "Las capturas de árbitros y Resultados pueden haberse tomado en instantes diferentes.",
            "Un valor ausente en los campos de tarjetas de un partido no se convierte en cero.",
        ],
    }
