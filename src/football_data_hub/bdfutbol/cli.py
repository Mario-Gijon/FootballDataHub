from __future__ import annotations

from .models import Fixture, StandingRow


def _assessment_diagnostic(assessment: dict[str, object]) -> tuple[str, ...]:
    missing_expected = [
        text
        for text, found in assessment.get("expected_texts", {}).items()
        if not found
    ]
    lines = (
        "title_looks_real={title_looks_real} "
        "structural_content={structural_content} "
        "expected_texts_ok={expected_texts_ok}"
    ).format(
        title_looks_real=assessment.get("title_looks_real"),
        structural_content=assessment.get("structural_content"),
        expected_texts_ok=assessment.get("expected_texts_ok"),
    )
    if missing_expected:
        return (lines, f"missing_expected={missing_expected!r}")
    return (lines,)


def _value(value: int | None) -> str:
    return "-" if value is None else str(value)


def _format_fixture(fixture: Fixture) -> str:
    prefix = f"J{fixture.round_number} {fixture.match_date} "
    suffix = f" (match_id={fixture.match.provider_id})"

    if fixture.played:
        return (
            f"{prefix}{fixture.home_team_name} {fixture.home_goals} - "
            f"{fixture.away_goals} {fixture.away_team_name}{suffix}"
        )

    return f"{prefix}{fixture.home_team_name} - {fixture.away_team_name}{suffix}"


def _print_standings(rows: tuple[StandingRow, ...]) -> None:
    if not rows:
        return

    print("\n=== CLASIFICACIÓN ===")
    print(
        f"{'Pos':>3}  {'Equipo':<30} {'team_id':>8} "
        f"{'Pts':>3} {'PJ':>3} {'PG':>3} {'PE':>3} {'PP':>3} "
        f"{'GF':>3} {'GC':>3} {'TA':>3} {'TR':>3}"
    )
    print("-" * 91)

    ordered = sorted(
        rows,
        key=lambda row: (
            row.position is None,
            row.position if row.position is not None else 10_000,
            row.team_name.casefold(),
        ),
    )

    for row in ordered:
        print(
            f"{_value(row.position):>3}  "
            f"{row.team_name:<30.30} "
            f"{row.team.provider_id:>8} "
            f"{_value(row.points):>3} "
            f"{_value(row.played):>3} "
            f"{_value(row.won):>3} "
            f"{_value(row.drawn):>3} "
            f"{_value(row.lost):>3} "
            f"{_value(row.goals_for):>3} "
            f"{_value(row.goals_against):>3} "
            f"{_value(row.yellow_cards):>3} "
            f"{_value(row.red_cards):>3}"
        )
