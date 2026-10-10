"""Validación del recurso y reconciliación con el motor local."""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from football_data_hub.domain.classification.models import MatchResult, Team
from football_data_hub.domain.statistics.models import CompetitionStatisticsReport

from .models import ParsedBDFutbolStatistics


def validate_statistics(parsed: ParsedBDFutbolStatistics) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    summary = parsed.source_summary
    values = {
        "teams": summary.teams,
        "matches": summary.matches,
        "home_wins": summary.home_wins,
        "away_wins": summary.away_wins,
        "draws": summary.draws,
        "goals": summary.goals,
        "yellow_cards": summary.yellow_cards,
        "expulsions": summary.expulsions,
        "penalties_awarded": parsed.exclusive_penalties.penalties_awarded,
        "penalties_scored": parsed.exclusive_penalties.penalties_scored,
        "penalties_missed": parsed.exclusive_penalties.penalties_missed,
    }
    if any(value < 0 for value in values.values()):
        issues.append({"code": "negative_source_value", "message": repr(values)})
    if summary.teams != 20:
        issues.append({"code": "unexpected_team_count", "message": str(summary.teams)})
    if summary.matches != summary.home_wins + summary.away_wins + summary.draws:
        issues.append({"code": "source_result_counts_inconsistent", "message": repr(values)})
    penalty = parsed.exclusive_penalties
    if penalty.penalties_scored + penalty.penalties_missed != penalty.penalties_awarded:
        issues.append({"code": "penalty_totals_inconsistent", "message": repr(asdict(penalty))})
    match_kinds = [item.kind for item in parsed.match_records]
    streak_kinds = [item.kind for item in parsed.streaks]
    if len(match_kinds) != len(set(match_kinds)) or len(match_kinds) != 3:
        issues.append({"code": "source_match_record_set_invalid", "message": repr(match_kinds)})
    if len(streak_kinds) != len(set(streak_kinds)) or len(streak_kinds) != 4:
        issues.append({"code": "source_streak_set_invalid", "message": repr(streak_kinds)})
    match_ids = [item.match_id for item in parsed.match_records]
    if len(match_ids) != len(set(match_ids)):
        issues.append({"code": "duplicate_source_record_match", "message": repr(match_ids)})
    round_ids = [item.matchday for item in parsed.chart.points]
    if not round_ids or len(round_ids) != len(set(round_ids)):
        issues.append({"code": "chart_rounds_missing_or_duplicate", "message": repr(round_ids)})
    if set(round_ids) != set(range(1, 39)):
        issues.append({"code": "chart_round_coverage_incomplete", "message": repr(round_ids)})
    if any(value is not None and value < 0 for point in parsed.chart.points for value in (
        point.goals, point.yellow_cards, point.red_cards
    )):
        issues.append({"code": "negative_chart_value", "message": "La serie contiene valores negativos"})
    return {
        "schema_version": 1,
        "valid": not issues,
        "summary": {
            "season": parsed.season,
            "group": parsed.group,
            "source_matches": summary.matches,
            "source_records": len(parsed.match_records),
            "source_streaks": len(parsed.streaks),
            "chart_rounds": len(parsed.chart.points),
            "penalty_equation_valid": penalty.penalties_scored + penalty.penalties_missed == penalty.penalties_awarded,
        },
        "checks": {
            "nonnegative_source_values": not any(value < 0 for value in values.values()),
            "expected_20_teams": summary.teams == 20,
            "match_outcomes_sum_to_matches": summary.matches == summary.home_wins + summary.away_wins + summary.draws,
            "penalties_awarded_equal_scored_plus_missed": penalty.penalties_scored + penalty.penalties_missed == penalty.penalties_awarded,
            "unique_match_record_categories": len(match_kinds) == len(set(match_kinds)) == 3,
            "unique_streak_categories": len(streak_kinds) == len(set(streak_kinds)) == 4,
            "unique_chart_rounds": len(round_ids) == len(set(round_ids)),
            "chart_rounds_1_to_38": set(round_ids) == set(range(1, 39)),
        },
        "issues": issues,
    }


def build_match_alignment_report(
    current_source_matches: tuple[MatchResult, ...],
    reference_matches: tuple[MatchResult, ...],
) -> dict[str, Any]:
    """Compara la tabla de fixtures embebida en la misma captura con RES-01.

    No exporta un segundo conjunto de partidos: devuelve solamente un resumen
    de igualdad por ID y por los campos deportivos que alimentan Estadísticas.
    """
    source_by_id = _unique_matches(current_source_matches, "página Estadísticas")
    reference_by_id = _unique_matches(reference_matches, "dataset Resultados")
    fields = (
        "matchday",
        "source_match_date",
        "home_team_id",
        "away_team_id",
        "home_goals",
        "away_goals",
        "home_yellow_cards",
        "away_yellow_cards",
        "home_red_cards",
        "away_red_cards",
        "status",
    )
    missing_reference = sorted(source_by_id.keys() - reference_by_id.keys(), key=_id_key)
    missing_source = sorted(reference_by_id.keys() - source_by_id.keys(), key=_id_key)
    differences: list[dict[str, Any]] = []
    for match_id in sorted(source_by_id.keys() & reference_by_id.keys(), key=_id_key):
        current, reference = source_by_id[match_id], reference_by_id[match_id]
        changed = {
            field: {
                "statistics_page": _json_value(getattr(current, field)),
                "results_dataset": _json_value(getattr(reference, field)),
            }
            for field in fields
            if getattr(current, field) != getattr(reference, field)
        }
        if changed:
            differences.append({"match_id": match_id, "fields": changed})
    identical = not (missing_reference or missing_source or differences)
    return {
        "status": "identical" if identical else "different",
        "current_source_match_count": len(source_by_id),
        "reference_match_count": len(reference_by_id),
        "matched_id_count": len(source_by_id.keys() & reference_by_id.keys()),
        "missing_from_reference": missing_reference,
        "missing_from_statistics_page": missing_source,
        "changed_records": differences,
        "compared_fields": list(fields),
    }


def build_reconciliation_report(
    parsed: ParsedBDFutbolStatistics,
    calculated: CompetitionStatisticsReport,
    teams: tuple[Team, ...],
    matches: tuple[MatchResult, ...],
    *,
    match_alignment: dict[str, Any],
    statistics_capture: dict[str, Any],
    match_dataset: dict[str, Any],
) -> dict[str, Any]:
    source = parsed.source_summary
    derived = calculated.statistics
    values = (
        ("teams", derived.team_count, source.teams, "count"),
        ("played_matches", derived.played_matches, source.matches, "count"),
        ("home_wins", derived.home_wins, source.home_wins, "count"),
        ("away_wins", derived.away_wins, source.away_wins, "count"),
        ("draws", derived.draws, source.draws, "count"),
        ("goals", derived.goals, source.goals, "count"),
        ("goals_per_match", _rounded(derived.goals_per_match), source.goals_per_match, "rounded_average"),
        ("yellow_cards", derived.yellow_cards, source.yellow_cards, "count"),
        ("yellow_cards_per_match", _rounded(derived.yellow_cards_per_match), source.yellow_cards_per_match, "rounded_average"),
        ("red_cards_vs_expulsions", derived.red_cards, source.expulsions, "aggregate_only"),
        ("red_cards_per_match_vs_expulsions_per_match", _rounded(derived.red_cards_per_match), source.expulsions_per_match, "rounded_aggregate_only"),
    )
    metrics = [_metric_comparison(name, actual, expected, basis) for name, actual, expected, basis in values]
    for item in metrics:
        if item["statistic"] in {
            "red_cards_vs_expulsions",
            "red_cards_per_match_vs_expulsions_per_match",
        } and item["status"] == "match":
            item["status"] = "numeric_match_semantics_unverified"
            item["cause"] = (
                "El recuento coincide, pero la equivalencia conceptual entre "
                "‘Expulsiones’ y tarjetas rojas del dataset no está demostrada."
            )
    match_by_id = {match.match_id: match for match in matches}
    record_comparisons = _compare_records(parsed, calculated, teams, match_by_id)
    series_comparisons = _compare_series(parsed, calculated)
    captures_differ = (
        statistics_capture.get("captured_at_utc") != match_dataset.get("source_captured_at_utc")
    )
    temporal_status = (
        "same_match_records_verified"
        if match_alignment.get("status") == "identical"
        else "not_conclusive_different_capture_windows"
        if captures_differ
        else "source_match_records_differ"
    )
    return {
        "schema_version": 1,
        "statistics_capture_id": statistics_capture.get("capture_id"),
        "statistics_captured_at_utc": statistics_capture.get("captured_at_utc"),
        "match_dataset_capture_id": match_dataset.get("source_capture_id"),
        "match_dataset_captured_at_utc": match_dataset.get("source_captured_at_utc"),
        "capture_windows_differ": captures_differ,
        "temporal_comparison_status": temporal_status,
        "match_data_alignment": match_alignment,
        "metrics": metrics,
        "exclusive_penalties": {
            "source": asdict(parsed.exclusive_penalties),
            "status": "source_only_not_derivable_from_match_contract",
            "equation_valid": parsed.exclusive_penalties.penalties_awarded
            == parsed.exclusive_penalties.penalties_scored + parsed.exclusive_penalties.penalties_missed,
        },
        "published_match_records": [
            {
                **asdict(record),
                "home_team_id": match_by_id.get(record.match_id).home_team_id
                if match_by_id.get(record.match_id)
                else None,
                "away_team_id": match_by_id.get(record.match_id).away_team_id
                if match_by_id.get(record.match_id)
                else None,
                "calculated_measure": _calculated_record_measure(calculated, record.kind),
                "calculated_match_ids": _calculated_record_ids(calculated, record.kind),
                "status": _record_status(calculated, record.kind, record.measure, record.match_id),
            }
            for record in parsed.match_records
        ],
        "published_streaks": _compare_streaks(parsed, calculated, teams),
        "round_series": series_comparisons,
        "summary": {
            "metric_count": len(metrics),
            "metric_matches": sum(item["status"] == "match" for item in metrics),
            "metric_differences": sum(item["status"] == "difference" for item in metrics),
            "metric_semantics_unverified": sum(
                item["status"] == "numeric_match_semantics_unverified" for item in metrics
            ),
            "record_statuses": {
                item["kind"]: item["status"] for item in record_comparisons
            },
            "round_series_differences": sum(
                item["status"] == "difference" for item in series_comparisons
            ),
        },
    }


def _metric_comparison(
    name: str,
    calculated: int | float | None,
    published: int | float,
    basis: str,
) -> dict[str, Any]:
    if calculated is None:
        status = "unknown"
        difference = None
    else:
        difference = float(published) - float(calculated)
        status = "match" if difference == 0 else "difference"
    return {
        "statistic": name,
        "calculated": calculated,
        "published": published,
        "difference_published_minus_calculated": difference,
        "comparison_basis": basis,
        "status": status,
        "cause": None,
    }


def _compare_records(
    parsed: ParsedBDFutbolStatistics,
    calculated: CompetitionStatisticsReport,
    teams: tuple[Team, ...],
    matches_by_id: dict[str, MatchResult],
) -> list[dict[str, Any]]:
    team_names = {team.team_id: team.name for team in teams}
    return [
        {
            "kind": record.kind,
            "match_id": record.match_id,
            "home_team_name": team_names.get(
                matches_by_id[record.match_id].home_team_id
            )
            if record.match_id in matches_by_id
            else None,
            "away_team_name": team_names.get(
                matches_by_id[record.match_id].away_team_id
            )
            if record.match_id in matches_by_id
            else None,
            "published_measure": record.measure,
            "calculated_measure": _calculated_record_measure(calculated, record.kind),
            "calculated_match_ids": _calculated_record_ids(calculated, record.kind),
            "status": _record_status(calculated, record.kind, record.measure, record.match_id),
        }
        for record in parsed.match_records
    ]


def _compare_streaks(
    parsed: ParsedBDFutbolStatistics,
    calculated: CompetitionStatisticsReport,
    teams: tuple[Team, ...],
) -> list[dict[str, Any]]:
    by_name: dict[str, list[Team]] = {}
    for team in teams:
        by_name.setdefault(team.name, []).append(team)
    result: list[dict[str, Any]] = []
    for item in parsed.streaks:
        candidates = by_name.get(item.team_name, [])
        resolved_id = candidates[0].team_id if len(candidates) == 1 else None
        calculated_matches = [
            streak
            for streak in calculated.records.streaks
            if streak.kind == item.kind
        ]
        maxima = max((streak.match_count for streak in calculated_matches), default=None)
        same_team = [streak for streak in calculated_matches if streak.team_id == resolved_id]
        matching = [
            streak
            for streak in same_team
            if streak.match_count == item.match_count
            and streak.matchday_start == item.matchday_start
            and streak.matchday_end == item.matchday_end
        ]
        tied_team_ids = sorted(
            streak.team_id for streak in calculated_matches if streak.match_count == maxima
        )
        status = (
            "unresolved_team_name"
            if resolved_id is None
            else "source_team_among_calculated_ties"
            if matching and item.match_count == maxima and len(tied_team_ids) > 1
            else "match"
            if matching and item.match_count == maxima
            else "source_team_among_calculated_ties"
            if matching
            else "difference"
        )
        result.append(
            {
                "kind": item.kind,
                "published_team_name": item.team_name,
                "resolved_team_id": resolved_id,
                "published_match_count": item.match_count,
                "published_matchday_start": item.matchday_start,
                "published_matchday_end": item.matchday_end,
                "calculated_max_match_count": maxima,
                "calculated_tied_team_ids": tied_team_ids,
                "calculated_match_ids": [
                    list(streak.match_ids) for streak in matching
                ],
                "status": status,
            }
        )
    return result


def _compare_series(
    parsed: ParsedBDFutbolStatistics,
    calculated: CompetitionStatisticsReport,
) -> list[dict[str, Any]]:
    source = {point.matchday: point for point in parsed.chart.points}
    derived = {point.matchday: point for point in calculated.statistics.rounds}
    comparisons: list[dict[str, Any]] = []
    for matchday in sorted(source.keys() | derived.keys()):
        source_point = source.get(matchday)
        derived_point = derived.get(matchday)
        for metric in ("goals", "yellow_cards", "red_cards"):
            published = getattr(source_point, metric) if source_point else None
            calculated_value = getattr(derived_point, metric) if derived_point else None
            if published is None and calculated_value is None:
                status = "no_observation"
                difference = None
            elif published is None:
                status = "not_published"
                difference = None
            elif calculated_value is None:
                status = "calculated_coverage_unavailable"
                difference = None
            else:
                difference = published - calculated_value
                status = "match" if difference == 0 else "difference"
            comparisons.append(
                {
                    "matchday": matchday,
                    "statistic": metric,
                    "calculated": calculated_value,
                    "published": published,
                    "difference_published_minus_calculated": difference,
                    "played_matches": derived_point.played_matches if derived_point else 0,
                    "scheduled_matches": derived_point.scheduled_matches if derived_point else 0,
                    "coverage": derived_point.coverage if derived_point else "no_fixture_record",
                    "status": status,
                    "cause": None,
                }
            )
    return comparisons


def _calculated_record_measure(
    calculated: CompetitionStatisticsReport, kind: str
) -> int | None:
    item = next((row for row in calculated.records.match_records if row.kind == kind), None)
    return item.measure if item else None


def _calculated_record_ids(
    calculated: CompetitionStatisticsReport, kind: str
) -> list[str]:
    item = next((row for row in calculated.records.match_records if row.kind == kind), None)
    return [match.match_id for match in item.matches] if item else []


def _record_status(
    calculated: CompetitionStatisticsReport,
    kind: str,
    published_measure: int,
    published_match_id: str,
) -> str:
    item = next((row for row in calculated.records.match_records if row.kind == kind), None)
    if item is None:
        return "unknown"
    if item.measure != published_measure:
        return "difference"
    if published_match_id in {match.match_id for match in item.matches}:
        return "match" if len(item.matches) == 1 else "published_value_matches_calculated_tie"
    return "published_value_matches_calculated_tie"


def _unique_matches(matches: tuple[MatchResult, ...], source: str) -> dict[str, MatchResult]:
    result: dict[str, MatchResult] = {}
    for match in matches:
        if match.match_id in result:
            raise ValueError(f"match_id duplicado en {source}: {match.match_id}")
        result[match.match_id] = match
    return result


def _id_key(value: str) -> tuple[int, int | str]:
    return (0, int(value)) if value.isdecimal() else (1, value.casefold())


def _json_value(value: object) -> object:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _rounded(value: float | None) -> float | None:
    if value is None:
        return None
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
