"""Motor puro de clasificación: recibe datos normalizados y no hace I/O."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .models import (
    CalculatedStanding,
    CalculatedTable,
    ClassificationFilter,
    MatchResult,
    Team,
)

ENGINE_VERSION = "0.1.0"


@dataclass(slots=True)
class _Totals:
    points: int = 0
    matches_played: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    goals_for: int = 0
    goals_against: int = 0
    yellow_cards: int = 0
    red_cards: int = 0
    cards_complete: bool = True


def _matches_filter(
    match: MatchResult, filters: ClassificationFilter, selected_matchday: int
) -> tuple[bool, str | None]:
    if match.matchday > selected_matchday:
        return False, None
    if not filters.include_postponed and match.postponed_by_source_rule is True:
        return False, None
    if filters.range_type == "dates":
        if match.source_match_date is None:
            return False, "Se omitió un registro sin fecha al aplicar el rango de fechas."
        assert filters.date_start is not None and filters.date_end is not None
        if not filters.date_start <= match.source_match_date <= filters.date_end:
            return False, None
    elif filters.range_type == "rounds":
        assert filters.round_start is not None and filters.round_end is not None
        if not filters.round_start <= match.matchday <= filters.round_end:
            return False, None
    return True, None


def calculate_standings(
    teams: Sequence[Team],
    matches: Sequence[MatchResult],
    filters: ClassificationFilter = ClassificationFilter(),
    *,
    source_capture_id: str | None = None,
    source_snapshot: str | None = None,
) -> CalculatedTable:
    """Calcula una tabla completa sin navegador, peticiones HTTP ni mutaciones.

    ``matchday_cap`` es un límite superior inclusivo. Si se omite, se usa la
    jornada más alta con al menos un resultado disputado. Los rangos también
    son inclusivos y se combinan con ese límite, tal como hace la página fuente.
    """
    if not teams:
        raise ValueError("Se requiere al menos un equipo participante")
    team_ids = [team.team_id for team in teams]
    if len(team_ids) != len(set(team_ids)):
        raise ValueError("Hay team_id duplicados en el catálogo")
    known_ids = set(team_ids)
    match_ids = [match.match_id for match in matches]
    if len(match_ids) != len(set(match_ids)):
        raise ValueError("Hay match_id duplicados; se rechaza el doble cómputo")
    for match in matches:
        if match.home_team_id not in known_ids or match.away_team_id not in known_ids:
            raise ValueError(f"{match.match_id} referencia un equipo fuera del catálogo")
        if match.status == "played" and (
            match.home_goals is None or match.away_goals is None
        ):
            raise ValueError(f"{match.match_id} está marcado disputado sin marcador")

    played_rounds = [match.matchday for match in matches if match.status == "played"]
    available_rounds = [match.matchday for match in matches]
    if filters.matchday_cap is not None:
        selected_matchday = filters.matchday_cap
    elif played_rounds:
        selected_matchday = max(played_rounds)
    elif available_rounds:
        selected_matchday = max(available_rounds)
    else:
        raise ValueError("No hay jornadas en el conjunto de partidos")

    selected_date = next(
        (
            match.matchday_date
            for match in matches
            if match.matchday == selected_matchday and match.matchday_date is not None
        ),
        None,
    )
    totals = {team.team_id: _Totals() for team in teams}
    eligible_records = 0
    counted_matches = 0
    unplayed_skipped = 0
    incomplete_skipped = 0
    warnings: list[str] = []
    has_unknown_postponement = False

    for match in matches:
        eligible, warning = _matches_filter(match, filters, selected_matchday)
        if warning:
            warnings.append(warning)
        if not eligible:
            continue
        if not filters.include_postponed and match.postponed_by_source_rule is None:
            has_unknown_postponement = True
        eligible_records += 1
        if match.status == "unplayed":
            unplayed_skipped += 1
            continue
        if match.status == "incomplete":
            incomplete_skipped += 1
            continue
        counted_matches += 1

        assert match.home_goals is not None and match.away_goals is not None
        if filters.classification_type in {"general", "local"}:
            _add_result(
                totals[match.home_team_id],
                goals_for=match.home_goals,
                goals_against=match.away_goals,
                yellow=match.home_yellow_cards,
                red=match.home_red_cards,
            )
        if filters.classification_type in {"general", "visitor"}:
            _add_result(
                totals[match.away_team_id],
                goals_for=match.away_goals,
                goals_against=match.home_goals,
                yellow=match.away_yellow_cards,
                red=match.away_red_cards,
            )

    if has_unknown_postponement:
        warnings.append(
            "Hay partidos cuya fecha no permite evaluar la regla de aplazamiento; "
            "se conservaron en el cálculo."
        )
    if incomplete_skipped:
        warnings.append(
            f"Se omitieron {incomplete_skipped} partidos con estado o marcador incompleto."
        )
    if any(not row.cards_complete for row in totals.values()):
        warnings.append("Faltan tarjetas en al menos un partido disputado incluido.")

    order = {team.team_id: index for index, team in enumerate(teams)}
    tie_groups: dict[tuple[int, int, int], list[Team]] = {}
    for team in teams:
        row = totals[team.team_id]
        primary_key = (
            -row.points,
            -(row.goals_for - row.goals_against),
            -row.goals_for,
        )
        tie_groups.setdefault(primary_key, []).append(team)
    sorted_teams: list[Team] = []
    for primary_key in sorted(tie_groups):
        group = tie_groups[primary_key]
        if all(totals[team.team_id].cards_complete for team in group):
            group.sort(
                key=lambda team: (
                    totals[team.team_id].red_cards * 2
                    + totals[team.team_id].yellow_cards,
                    order[team.team_id],
                )
            )
        else:
            # Con tarjetas incompletas no se inventa un valor disciplinario.
            group.sort(key=lambda team: order[team.team_id])
        sorted_teams.extend(group)
    rows: list[CalculatedStanding] = []
    for position, team in enumerate(sorted_teams, start=1):
        row = totals[team.team_id]
        yellow = row.yellow_cards if row.cards_complete else None
        red = row.red_cards if row.cards_complete else None
        discipline = yellow + 2 * red if yellow is not None and red is not None else None
        rows.append(
            CalculatedStanding(
                team=team,
                position=position,
                points=row.points,
                matches_played=row.matches_played,
                wins=row.wins,
                draws=row.draws,
                losses=row.losses,
                goals_for=row.goals_for,
                goals_against=row.goals_against,
                yellow_cards=yellow,
                red_cards=red,
                goal_difference=row.goals_for - row.goals_against,
                disciplinary_score=discipline,
            )
        )

    return CalculatedTable(
        source_capture_id=source_capture_id,
        source_snapshot=source_snapshot,
        algorithm_version=ENGINE_VERSION,
        classification_type=filters.classification_type,
        selected_matchday=selected_matchday,
        selected_matchday_date=selected_date,
        include_postponed=filters.include_postponed,
        range_type=filters.range_type,
        date_start=filters.date_start,
        date_end=filters.date_end,
        round_start=filters.round_start,
        round_end=filters.round_end,
        matches_available=eligible_records,
        matches_counted=counted_matches,
        unplayed_matches_skipped=unplayed_skipped,
        incomplete_matches_skipped=incomplete_skipped,
        rows=tuple(rows),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _add_result(
    totals: _Totals,
    *,
    goals_for: int,
    goals_against: int,
    yellow: int | None,
    red: int | None,
) -> None:
    totals.matches_played += 1
    totals.goals_for += goals_for
    totals.goals_against += goals_against
    if goals_for > goals_against:
        totals.wins += 1
        totals.points += 3
    elif goals_for == goals_against:
        totals.draws += 1
        totals.points += 1
    else:
        totals.losses += 1
    if yellow is None or red is None:
        totals.cards_complete = False
    else:
        totals.yellow_cards += yellow
        totals.red_cards += red

