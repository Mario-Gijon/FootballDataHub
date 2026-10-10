"""Compara el motor local con una referencia observada de BDFutbol."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from football_data_hub.domain.classification.engine import calculate_standings
from football_data_hub.domain.classification.models import ClassificationFilter
from football_data_hub.providers.bdfutbol.classification.match_io import load_match_dataset

FIELDS = (
    "position",
    "points",
    "matches_played",
    "wins",
    "draws",
    "losses",
    "goals_for",
    "goals_against",
    "yellow_cards",
    "red_cards",
)


def _filters(payload: dict[str, Any]) -> ClassificationFilter:
    item = payload["filters"]
    return ClassificationFilter(
        classification_type=item["classification_type"],
        matchday_cap=item["matchday_cap"],
        include_postponed=item["include_postponed"],
        range_type=item["range_type"],
        date_start=date.fromisoformat(item["date_start"]) if item["date_start"] else None,
        date_end=date.fromisoformat(item["date_end"]) if item["date_end"] else None,
        round_start=item["round_start"],
        round_end=item["round_end"],
    )


def compare_reference(
    teams,
    matches,
    metadata: dict[str, Any],
    reference: dict[str, Any],
) -> dict[str, Any]:
    scenarios: list[dict[str, Any]] = []
    for reference_scenario in reference["scenarios"]:
        filters = _filters(reference_scenario)
        table = calculate_standings(
            teams,
            matches,
            filters,
            source_capture_id=metadata.get("source_capture_id"),
            source_snapshot=metadata.get("source_snapshot"),
        )
        expected_rows = {row["team_id"]: row for row in reference_scenario["rows"]}
        calculated_rows = {row.team.team_id: row for row in table.rows}
        differences: list[dict[str, Any]] = []
        identical_fields = 0
        for team_id in sorted(set(expected_rows) | set(calculated_rows)):
            expected = expected_rows.get(team_id)
            calculated = calculated_rows.get(team_id)
            if expected is None or calculated is None:
                differences.append(
                    {
                        "team_id": team_id,
                        "field": "team_presence",
                        "expected": expected is not None,
                        "calculated": calculated is not None,
                    }
                )
                continue
            for field in FIELDS:
                actual_value = getattr(calculated, field)
                expected_value = expected.get(field)
                if actual_value == expected_value:
                    identical_fields += 1
                else:
                    differences.append(
                        {
                            "team_id": team_id,
                            "field": field,
                            "expected": expected_value,
                            "calculated": actual_value,
                            "possible_explanation": (
                                "Revisar regla de desempate, resultado fuente o ajuste oficial; "
                                "el informe no corrige valores automáticamente."
                            ),
                        }
                    )
        team_set_complete = set(expected_rows) == set(calculated_rows) and len(calculated_rows) == 20
        status = "correct" if not differences and team_set_complete else "pending"
        scenarios.append(
            {
                "name": reference_scenario["name"],
                "filters": asdict(filters),
                "status": status,
                "teams_compared": len(set(expected_rows) & set(calculated_rows)),
                "fields_compared": len(expected_rows) * len(FIELDS),
                "fields_identical": identical_fields,
                "differences": differences,
                "matches_counted": table.matches_counted,
                "unplayed_matches_skipped": table.unplayed_matches_skipped,
                "warnings": list(table.warnings),
            }
        )

    return {
        "schema_version": 1,
        "source_capture_id": metadata.get("source_capture_id"),
        "source_snapshot": metadata.get("source_snapshot"),
        "reference": reference.get("metadata"),
        "engine_version": "0.1.0",
        "scenario_count": len(scenarios),
        "correct_scenarios": sum(item["status"] == "correct" for item in scenarios),
        "pending_scenarios": sum(item["status"] == "pending" for item in scenarios),
        "scenarios": scenarios,
    }


def compare_published_standings(teams, matches, metadata, published) -> dict[str, Any]:
    source_context = published.get("context", {})
    matchday = int(source_context.get("matchday") or metadata.get("played_matchdays_in_source", 1))
    table = calculate_standings(
        teams,
        matches,
        ClassificationFilter(classification_type="general", matchday_cap=matchday),
        source_capture_id=metadata.get("source_capture_id"),
        source_snapshot=metadata.get("source_snapshot"),
    )
    expected_rows = {row["team_id"]: row for row in published["standings"]}
    calculated_rows = {row.team.team_id: row for row in table.rows}
    differences: list[dict[str, Any]] = []
    identical_fields = 0
    for team_id in sorted(set(expected_rows) | set(calculated_rows)):
        expected = expected_rows.get(team_id)
        calculated = calculated_rows.get(team_id)
        if expected is None or calculated is None:
            differences.append(
                {
                    "team_id": team_id,
                    "field": "team_presence",
                    "expected": expected is not None,
                    "calculated": calculated is not None,
                }
            )
            continue
        for field in FIELDS:
            actual = getattr(calculated, field)
            published_value = expected.get(field)
            if actual == published_value:
                identical_fields += 1
            else:
                differences.append(
                    {
                        "team_id": team_id,
                        "field": field,
                        "expected": published_value,
                        "calculated": actual,
                        "possible_explanation": (
                            "La tabla publicada puede conservar desempates o ajustes oficiales; "
                            "los valores no se modifican automáticamente."
                        ),
                    }
                )
    return {
        "source_type": "published_source_standings",
        "source_context": source_context,
        "status": "correct" if not differences and len(expected_rows) == 20 else "pending",
        "teams_compared": len(set(expected_rows) & set(calculated_rows)),
        "fields_compared": len(expected_rows) * len(FIELDS),
        "fields_identical": identical_fields,
        "differences": differences,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matches", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--official", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    metadata, teams, matches = load_match_dataset(args.matches)
    reference = json.loads(args.reference.read_text(encoding="utf-8"))
    report = compare_reference(teams, matches, metadata, reference)
    if args.official:
        official = json.loads(args.official.read_text(encoding="utf-8"))
        report["published_source_standings_comparison"] = compare_published_standings(
            teams, matches, metadata, official
        )
    output = args.output.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, default=str)
        stream.write("\n")
    print(
        f"Escenarios: {report['scenario_count']}; correctos: {report['correct_scenarios']}; "
        f"pendientes: {report['pending_scenarios']}; informe: {output}"
    )
    return 0 if report["pending_scenarios"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
