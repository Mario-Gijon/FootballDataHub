"""Invariantes deportivas para conjuntos normalizados de resultados."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Any

from .models import MatchResult, Team


def validate_match_set(
    teams: Sequence[Team],
    matches: Sequence[MatchResult],
    *,
    expected_teams: int | None = None,
    expected_rounds: int | None = None,
    fixtures_per_round: int | None = None,
) -> dict[str, Any]:
    team_ids = [team.team_id for team in teams]
    match_ids = [match.match_id for match in matches]
    duplicate_ids = sorted(value for value, count in Counter(match_ids).items() if count > 1)
    fixture_counts = Counter(match.matchday for match in matches)
    fixture_keys = [
        (match.matchday, match.home_team_id, match.away_team_id) for match in matches
    ]
    duplicate_fixtures = sorted(
        value for value, count in Counter(fixture_keys).items() if count > 1
    )
    known_ids = set(team_ids)
    unknown_teams = sorted(
        {
            team_id
            for match in matches
            for team_id in (match.home_team_id, match.away_team_id)
            if team_id not in known_ids
        }
    )
    played = [match for match in matches if match.status == "played"]
    unplayed = [match for match in matches if match.status == "unplayed"]
    incomplete = [match for match in matches if match.status == "incomplete"]
    unplayed_states = Counter(
        match.unplayed_state for match in unplayed if match.unplayed_state is not None
    )
    totals_by_team: Counter[tuple[int, str]] = Counter()
    for match in played:
        assert match.home_goals is not None and match.away_goals is not None
        totals_by_team[(match.home_team_id, "goals_for")] += match.home_goals
        totals_by_team[(match.home_team_id, "goals_against")] += match.away_goals
        totals_by_team[(match.away_team_id, "goals_for")] += match.away_goals
        totals_by_team[(match.away_team_id, "goals_against")] += match.home_goals
    total_goals_for = sum(
        value for (team_id, metric), value in totals_by_team.items() if metric == "goals_for"
    )
    total_goals_against = sum(
        value for (team_id, metric), value in totals_by_team.items() if metric == "goals_against"
    )
    all_complete_scores = all(
        match.home_goals is not None and match.away_goals is not None for match in played
    )
    expected_round_numbers = set(range(1, expected_rounds + 1)) if expected_rounds else None
    round_coverage_ok = (
        expected_round_numbers is None
        or set(fixture_counts) == expected_round_numbers
    )
    fixture_shape_ok = (
        fixtures_per_round is None
        or all(fixture_counts[round_number] == fixtures_per_round for round_number in fixture_counts)
    )
    participant_accounting_ok = sum(
        match.home_team_id != match.away_team_id for match in played
    ) == len(played)
    checks = [
        _check("team_count", expected_teams is None or len(teams) == expected_teams, expected=expected_teams, actual=len(teams)),
        _check("unique_team_ids", len(team_ids) == len(set(team_ids)), actual=len(team_ids)),
        _check("unique_match_ids", not duplicate_ids, duplicates=duplicate_ids),
        _check("unique_fixtures", not duplicate_fixtures, duplicates=duplicate_fixtures),
        _check("known_team_references", not unknown_teams, unknown_team_ids=unknown_teams),
        _check("round_coverage", round_coverage_ok, rounds=sorted(fixture_counts)),
        _check("fixtures_per_round", fixture_shape_ok, counts=dict(fixture_counts)),
        _check("played_scores_complete", all_complete_scores, played=len(played)),
        _check("one_home_and_away_participant_per_match", participant_accounting_ok, played=len(played)),
        _check(
            "goals_for_against_balance",
            total_goals_for == total_goals_against,
            goals_for=total_goals_for,
            goals_against=total_goals_against,
        ),
    ]
    return {
        "valid": all(check["status"] == "pass" for check in checks),
        "counts": {
            "teams": len(teams),
            "matches": len(matches),
            "played": len(played),
            "unplayed": len(unplayed),
            "incomplete": len(incomplete),
            "unplayed_states": dict(unplayed_states),
            "postponed_by_source_rule": sum(
                match.postponed_by_source_rule is True for match in matches
            ),
            "matchdays": len(fixture_counts),
        },
        "totals": {
            "goals_for_across_matches": total_goals_for,
            "goals_against_across_matches": total_goals_against,
            "participant_rows_in_played_matches": len(played) * 2,
        },
        "checks": checks,
    }


def _check(name: str, passed: bool, **details: Any) -> dict[str, Any]:
    return {"name": name, "status": "pass" if passed else "fail", **details}
