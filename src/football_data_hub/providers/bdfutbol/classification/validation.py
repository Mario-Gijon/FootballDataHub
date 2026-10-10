"""Validaciones deportivas que nunca reescriben valores de la fuente."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from typing import Any

from .models import ProgressRecord, TeamStanding

_COUNT_FIELDS = (
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


def validate_classification(
    standings: tuple[TeamStanding, ...] | list[TeamStanding],
    progress: tuple[ProgressRecord, ...] | list[ProgressRecord],
    *,
    played_matchdays: int,
    expected_teams: int = 20,
) -> dict[str, Any]:
    """Return a JSON-ready report; points anomalies are exceptions, not repairs."""
    checks: list[dict[str, Any]] = []

    def add(name: str, status: str, message: str, **details: Any) -> None:
        checks.append({"name": name, "status": status, "message": message, **details})

    team_ids = [row.team_id for row in standings]
    positions = [row.position for row in standings if row.position is not None]
    add(
        "team_count",
        "pass" if len(standings) == expected_teams else "fail",
        f"Se encontraron {len(standings)} filas; se esperaban {expected_teams}.",
        expected=expected_teams,
        actual=len(standings),
    )
    add(
        "unique_team_ids",
        "pass" if len(set(team_ids)) == len(team_ids) else "fail",
        "Los identificadores BDFutbol son únicos." if len(set(team_ids)) == len(team_ids)
        else "Hay identificadores BDFutbol duplicados.",
    )
    add(
        "unique_positions",
        "pass" if len(set(positions)) == len(positions) else "fail",
        "Los puestos son únicos." if len(set(positions)) == len(positions)
        else "Hay puestos duplicados.",
    )

    matches_incomplete: list[int] = []
    matches_mismatch: list[dict[str, int]] = []
    points_mismatch: list[dict[str, int]] = []
    points_incomplete: list[int] = []
    null_field_counts: Counter[str] = Counter()
    for row in standings:
        row_values = asdict(row)
        for field in _COUNT_FIELDS:
            if row_values[field] is None:
                null_field_counts[field] += 1
        values = (row.matches_played, row.wins, row.draws, row.losses)
        if any(value is None for value in values):
            matches_incomplete.append(row.team_id)
        else:
            played = row.matches_played
            assert played is not None and row.wins is not None and row.draws is not None and row.losses is not None
            expected_played = row.wins + row.draws + row.losses
            if played != expected_played:
                matches_mismatch.append({"team_id": row.team_id, "actual": played, "expected": expected_played})

        if row.points is None or row.wins is None or row.draws is None:
            points_incomplete.append(row.team_id)
        else:
            expected_points = row.wins * 3 + row.draws
            if row.points != expected_points:
                points_mismatch.append(
                    {"team_id": row.team_id, "actual": row.points, "ordinary_formula": expected_points}
                )

    if matches_mismatch:
        matches_status = "fail"
    elif matches_incomplete:
        matches_status = "warning"
    else:
        matches_status = "pass"
    add(
        "matches_played_equation",
        matches_status,
        "PJ = PG + PE + PP" if matches_status == "pass"
        else "Falta algún valor para comprobar PJ = PG + PE + PP."
        if matches_status == "warning"
        else "Hay equipos que no cumplen PJ = PG + PE + PP.",
        mismatches=matches_mismatch,
        incomplete_team_ids=matches_incomplete,
    )
    if points_mismatch:
        points_status = "exception"
        points_message = "La fuente difiere de 3 × PG + PE; conservar los puntos publicados y revisar sanciones/ajustes."
    elif points_incomplete:
        points_status = "warning"
        points_message = "Falta algún valor para comprobar PTS = 3 × PG + PE."
    else:
        points_status = "pass"
        points_message = "PTS = 3 × PG + PE en todas las filas completas."
    add(
        "ordinary_points_formula",
        points_status,
        points_message,
        differences=points_mismatch,
        incomplete_team_ids=points_incomplete,
        auto_corrected=False,
    )
    add(
        "null_source_values",
        "warning" if null_field_counts else "pass",
        "Los campos ausentes se conservan como null; no se sustituyen por cero."
        if null_field_counts
        else "No faltan valores numéricos en las filas observadas.",
        counts=dict(null_field_counts),
    )

    expected_progress = expected_teams * played_matchdays
    progress_keys = [(record.team_id, record.matchday) for record in progress]
    known_ids = set(team_ids)
    progress_valid = (
        len(progress) == expected_progress
        and len(set(progress_keys)) == len(progress_keys)
        and all(team_id in known_ids for team_id, _ in progress_keys)
        and all(1 <= matchday <= played_matchdays for _, matchday in progress_keys)
    )
    add(
        "progress_series_shape",
        "pass" if progress_valid else "fail",
        "Las series cubren cada equipo y jornada una sola vez."
        if progress_valid
        else "Las series tienen jornadas, equipos o claves duplicadas/incompletas.",
        expected_records=expected_progress,
        actual_records=len(progress),
    )
    missing_progress_position = [
        {"team_id": row.team_id, "matchday": row.matchday}
        for row in progress
        if row.position is None
    ]
    missing_progress_metrics = [
        {"team_id": row.team_id, "matchday": row.matchday, "field": field}
        for row in progress
        for field in ("points", "goals_for", "goals_against")
        if getattr(row, field) is None
    ]
    add(
        "progress_values_present",
        "fail" if missing_progress_position else "warning" if missing_progress_metrics else "pass",
        "Falta una posición de jornada." if missing_progress_position
        else "Los valores ausentes de la fuente se conservan como null en las series."
        if missing_progress_metrics
        else "Las métricas de progreso están presentes para todas las jornadas.",
        missing_positions=missing_progress_position,
        missing_metrics=missing_progress_metrics,
    )

    fail_count = sum(check["status"] == "fail" for check in checks)
    warning_count = sum(check["status"] in {"warning", "exception"} for check in checks)
    return {
        "valid": fail_count == 0,
        "summary": {"checks": len(checks), "failures": fail_count, "warnings_or_exceptions": warning_count},
        "checks": checks,
    }
