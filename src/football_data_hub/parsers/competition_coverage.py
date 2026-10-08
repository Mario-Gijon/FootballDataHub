"""Cobertura y controles de calidad para el primer extractor de competición."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from football_data_hub.parsers.match_status import normalized_match_state
from football_data_hub.providers.bdfutbol.competition import PARSER_VERSION

EXPECTED_GROUPS = ("I", "II")
EXPECTED_TEAMS_PER_GROUP = 20
EXPECTED_ROUNDS_PER_GROUP = 38
EXPECTED_MATCHES_PER_ROUND = 10
EXPECTED_MATCHES_PER_GROUP = 380


def _duplicates(values: list[str | None]) -> dict[str, int]:
    counts = Counter(value for value in values if value is not None)
    return {value: count for value, count in counts.items() if count > 1}


def _duplicate_fixture_keys(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = Counter(
        (match.get("round"), match.get("home_team_name"), match.get("away_team_name"))
        for match in matches
    )
    return [
        {"round": round_number, "home_team_name": home, "away_team_name": away, "count": count}
        for (round_number, home, away), count in keys.items()
        if count > 1
    ]


def _group_report(parsed: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    competition = parsed["competition"]
    group = str(competition["group"])
    standings = parsed["standings"]
    matches = parsed["matches"]
    diagnostics = parsed["diagnostics"]
    rounds: dict[int, int] = defaultdict(int)
    for match in matches:
        round_number = match.get("round")
        if isinstance(round_number, int):
            rounds[round_number] += 1
    expected_round_numbers = set(range(1, EXPECTED_ROUNDS_PER_GROUP + 1))
    observed_round_numbers = set(rounds)
    wrong_rounds = {
        str(round_number): count
        for round_number, count in sorted(rounds.items())
        if count != EXPECTED_MATCHES_PER_ROUND
    }

    team_ids = [team.get("team_season_id") for team in standings]
    match_ids = [match.get("match_id") for match in matches]
    duplicate_team_ids = _duplicates(team_ids)
    duplicate_match_ids = _duplicates(match_ids)
    duplicate_fixtures = _duplicate_fixture_keys(matches)
    group_mismatch_count = sum(match.get("group") != group for match in matches)
    unresolved_team_refs = sum(
        not match.get("home_team_season_id") or not match.get("away_team_season_id")
        for match in matches
    )
    missing_match_ids = sum(match_id is None for match_id in match_ids)
    states = [normalized_match_state(match) for match in matches]
    played_count = sum(state == "played" for state in states)
    scheduled_count = sum(state == "scheduled" for state in states)
    unresolved_count = sum(state == "unresolved" for state in states)
    inconsistent_count = sum(state == "inconsistent" for state in states)
    unconfirmed_count = sum(match.get("fixture_status") == "unconfirmed" for match in matches)
    played_missing_match_ids = sum(
        normalized_match_state(match) == "played" and not match.get("match_id")
        for match in matches
    )
    scheduled_without_published_id = sum(
        normalized_match_state(match) == "scheduled" and not match.get("match_id")
        for match in matches
    )
    unresolved_without_published_id = sum(
        normalized_match_state(match) == "unresolved" and not match.get("match_id")
        for match in matches
    )
    unknown_result_count = sum(match.get("result_status") == "unknown" for match in matches)
    missing_date_count = sum(match.get("date") is None for match in matches)
    fixture_names = {
        str(match.get(field))
        for match in matches
        for field in ("home_team_name", "away_team_name")
        if match.get(field)
    }
    standing_names = {str(team.get("team_name")) for team in standings if team.get("team_name")}
    fixture_names_without_standing = sorted(fixture_names - standing_names)
    standing_names_without_fixture = sorted(standing_names - fixture_names)
    positions = [team.get("position") for team in standings]
    standings_statistics_valid = all(
        value is not None
        for team in standings
        for value in team.get("stats", {}).values()
    )
    parser_issues = diagnostics.get("issues", [])
    rounds_missing = sorted(expected_round_numbers - observed_round_numbers)
    rounds_outside_expected = sorted(observed_round_numbers - expected_round_numbers)

    coverage_checks = {
        "competition_group_matches_source_title": competition.get("group_source") == group,
        "competition_season_matches_source_title": competition.get("season_source") == "2026-27",
        "standings_headers_valid": bool(diagnostics.get("standings_headers_valid")),
        "expected_team_count": len(standings) == EXPECTED_TEAMS_PER_GROUP,
        "expected_standing_positions": set(positions) == set(range(1, EXPECTED_TEAMS_PER_GROUP + 1)),
        "team_season_ids_present_and_unique": (
            all(team_ids) and len(set(team_ids)) == len(team_ids)
        ),
        "standing_team_names_unique": len(standing_names) == len(standings),
        "standing_statistics_parse_as_integers": standings_statistics_valid,
        "expected_round_count": observed_round_numbers == expected_round_numbers,
        "expected_matches_per_round": not wrong_rounds,
        "expected_match_count": len(matches) == EXPECTED_MATCHES_PER_GROUP,
        "match_ids_present_and_unique": (
            played_missing_match_ids == 0 and not duplicate_match_ids
        ),
        "fixture_round_home_away_keys_unique": not duplicate_fixtures,
        "all_fixture_teams_in_standings": (
            not fixture_names_without_standing and not standing_names_without_fixture
        ),
        "fixture_team_references_resolved": unresolved_team_refs == 0,
        "fixtures_not_mixed_between_groups": group_mismatch_count == 0,
        "no_unparsed_results": unknown_result_count == 0,
        "no_inconsistent_match_evidence": inconsistent_count == 0,
        "no_unexpected_parser_diagnostics": not parser_issues,
    }
    return {
        "group": group,
        "source_url": competition.get("url"),
        "access_status": metadata.get("access_status"),
        "snapshot_sha256": metadata.get("rendered_html_sha256"),
        "snapshot_captured_at_utc": metadata.get("captured_at_utc"),
        "observed": {
            "teams": len(standings),
            "rounds": len(observed_round_numbers),
            "matches": len(matches),
            "played_matches": played_count,
            "scheduled_matches": scheduled_count,
            "unresolved_matches": unresolved_count,
            "inconsistent_matches": inconsistent_count,
            "unconfirmed_not_played_matches": unconfirmed_count,
            "unknown_result_matches": unknown_result_count,
            "results_not_available": sum(match.get("result_status") == "not_available" for match in matches),
            "missing_match_dates": missing_date_count,
            "unique_match_ids": len({value for value in match_ids if value is not None}),
            "matches_missing_id": missing_match_ids,
            "played_matches_missing_id": played_missing_match_ids,
            "scheduled_matches_without_published_id": scheduled_without_published_id,
            "unresolved_matches_without_published_id": unresolved_without_published_id,
            "duplicate_team_ids": duplicate_team_ids,
            "duplicate_match_ids": duplicate_match_ids,
            "duplicate_fixture_keys": duplicate_fixtures,
            "matches_per_round": {str(key): value for key, value in sorted(rounds.items())},
            "round_numbers_missing": rounds_missing,
            "round_numbers_outside_expected_range": rounds_outside_expected,
            "rounds_with_unexpected_match_count": wrong_rounds,
            "fixture_names_without_standing": fixture_names_without_standing,
            "standing_names_without_fixture": standing_names_without_fixture,
            "fixture_team_references_unresolved": unresolved_team_refs,
            "fixture_rows_with_wrong_group": group_mismatch_count,
        },
        "expected": {
            "teams": EXPECTED_TEAMS_PER_GROUP,
            "rounds": EXPECTED_ROUNDS_PER_GROUP,
            "matches_per_round": EXPECTED_MATCHES_PER_ROUND,
            "matches": EXPECTED_MATCHES_PER_GROUP,
        },
        "coverage_checks": coverage_checks,
        "fixture_coverage_complete": all(coverage_checks.values()),
        "field_coverage": {
            "dates_available": len(matches) - missing_date_count,
            "dates_missing": missing_date_count,
            "stadium_ids_available": sum(match.get("stadium_id") is not None for match in matches),
            "referee_ids_available": sum(match.get("referee_id") is not None for match in matches),
            "results_available": played_count,
            "results_not_yet_available": scheduled_count + unresolved_count,
        },
        "parser_diagnostics": parser_issues,
    }


def build_competition_coverage(
    parsed_groups: list[dict[str, Any]], metadata_by_group: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Calcula cobertura observada; las expectativas solo se comparan, no se rellenan."""
    by_group = {str(item["competition"]["group"]): item for item in parsed_groups}
    group_reports = [
        _group_report(by_group[group], metadata_by_group[group])
        for group in EXPECTED_GROUPS
        if group in by_group and group in metadata_by_group
    ]
    observed_group_names = sorted(by_group)
    group_count_complete = tuple(observed_group_names) == EXPECTED_GROUPS
    group_coverage_complete = (
        group_count_complete
        and len(group_reports) == len(EXPECTED_GROUPS)
        and all(item["fixture_coverage_complete"] for item in group_reports)
    )
    access_all_valid = (
        group_count_complete
        and all(metadata_by_group.get(group, {}).get("access_status") == "VALID" for group in EXPECTED_GROUPS)
    )
    match_groups: dict[str, set[str]] = defaultdict(set)
    for parsed in parsed_groups:
        group = str(parsed["competition"]["group"])
        for match in parsed["matches"]:
            if match.get("match_id") is not None:
                match_groups[str(match["match_id"])].add(group)
    duplicate_match_ids_across_groups = {
        match_id: sorted(groups)
        for match_id, groups in match_groups.items()
        if len(groups) > 1
    }
    group_coverage_complete = group_coverage_complete and not duplicate_match_ids_across_groups
    observed_match_count = sum(item["observed"]["matches"] for item in group_reports)
    played_match_count = sum(item["observed"]["played_matches"] for item in group_reports)
    season_outcomes_complete = (
        group_coverage_complete
        and observed_match_count == 2 * EXPECTED_MATCHES_PER_GROUP
        and played_match_count == observed_match_count
    )
    return {
        "schema_version": "football_data_hub.competition_coverage.v1",
        "parser_version": PARSER_VERSION,
        "scope": "fixture_structure_and_observed_competition_fields",
        "season": "2026/27",
        "expected": {
            "groups": 2,
            "teams_per_group": EXPECTED_TEAMS_PER_GROUP,
            "rounds_per_group": EXPECTED_ROUNDS_PER_GROUP,
            "matches_per_round": EXPECTED_MATCHES_PER_ROUND,
            "matches_per_group": EXPECTED_MATCHES_PER_GROUP,
            "matches_total": 2 * EXPECTED_MATCHES_PER_GROUP,
        },
        "observed": {
            "groups": len(observed_group_names),
            "group_names": observed_group_names,
            "teams_total": sum(item["observed"]["teams"] for item in group_reports),
            "matches_total": sum(item["observed"]["matches"] for item in group_reports),
            "unique_match_ids_total": len(match_groups),
            "duplicate_match_ids_across_groups": duplicate_match_ids_across_groups,
        },
        "access_valid_for_all_groups": access_all_valid,
        "coverage_complete": group_coverage_complete,
        "coverage_is_independent_of_access_validity": True,
        "season_outcomes_complete": season_outcomes_complete,
        "source_view_comparison": {
            "status": "NOT_COMPARED",
            "reason": "Esta entrega analiza un snapshot de clasificación/calendario por grupo; no se capturaron vistas alternativas.",
        },
        "groups": group_reports,
    }
