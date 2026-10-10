"""Motor puro para agregados, récords, rachas y series por jornada."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence

from football_data_hub.domain.classification.models import MatchResult, Team

from .models import (
    CompetitionContext,
    CompetitionRecords,
    CompetitionStatistics,
    CompetitionStatisticsReport,
    MatchRecord,
    MetricCoverage,
    RecordSet,
    RoundStatistics,
    StreakKind,
    StreakRecord,
)

STATISTICS_ENGINE_VERSION = "0.1.0"


def calculate_competition_statistics(
    teams: Sequence[Team],
    matches: Sequence[MatchResult],
    context: CompetitionContext,
) -> CompetitionStatisticsReport:
    """Calcula estadísticas deterministas sin I/O ni JavaScript de la fuente.

    Solo cuenta registros ``played``. Fixtures programados e incompletos nunca
    se convierten en marcadores o empates. Una métrica de tarjetas queda en
    ``None`` si falta cualquiera de sus datos en al menos un partido disputado.
    """
    if not teams:
        raise ValueError("Se requiere el catálogo de equipos participantes")
    team_ids = [team.team_id for team in teams]
    if len(team_ids) != len(set(team_ids)):
        raise ValueError("team_id duplicado en el catálogo")
    team_by_id = {team.team_id: team for team in teams}
    match_ids = [match.match_id for match in matches]
    if len(match_ids) != len(set(match_ids)):
        raise ValueError("match_id duplicado; se rechaza el doble cómputo")

    rounds: dict[int, list[MatchResult]] = defaultdict(list)
    for match in matches:
        if match.home_team_id not in team_by_id or match.away_team_id not in team_by_id:
            raise ValueError(f"El partido {match.match_id} referencia un equipo desconocido")
        rounds[match.matchday].append(match)

    played = [match for match in matches if match.status == "played"]
    home_wins = sum(match.home_goals > match.away_goals for match in played)
    away_wins = sum(match.home_goals < match.away_goals for match in played)
    draws = sum(match.home_goals == match.away_goals for match in played)
    goals = sum(match.home_goals + match.away_goals for match in played)

    yellow_coverage = _card_coverage(
        played, ("home_yellow_cards", "away_yellow_cards")
    )
    red_coverage = _card_coverage(played, ("home_red_cards", "away_red_cards"))
    yellow_cards = (
        sum(match.home_yellow_cards + match.away_yellow_cards for match in played)
        if yellow_coverage.complete
        else None
    )
    red_cards = (
        sum(match.home_red_cards + match.away_red_cards for match in played)
        if red_coverage.complete
        else None
    )
    scheduled = len(matches)

    round_statistics = tuple(
        _round_statistics(matchday, rounds[matchday])
        for matchday in sorted(rounds)
    )
    stats = CompetitionStatistics(
        context=context,
        team_count=len(teams),
        scheduled_matches=scheduled,
        played_matches=len(played),
        unplayed_matches=sum(match.status == "unplayed" for match in matches),
        incomplete_matches=sum(match.status == "incomplete" for match in matches),
        home_wins=home_wins,
        away_wins=away_wins,
        draws=draws,
        goals=goals if played else None,
        goals_per_match=goals / len(played) if played else None,
        yellow_cards=yellow_cards,
        yellow_cards_per_match=(yellow_cards / len(played) if yellow_cards is not None and played else None),
        red_cards=red_cards,
        red_cards_per_match=(red_cards / len(played) if red_cards is not None and played else None),
        yellow_card_coverage=yellow_coverage,
        red_card_coverage=red_coverage,
        rounds=round_statistics,
    )
    records = _calculate_records(teams, matches)
    return CompetitionStatisticsReport(statistics=stats, records=records)


def _card_coverage(
    matches: Sequence[MatchResult], fields: tuple[str, str]
) -> MetricCoverage:
    missing = tuple(
        sorted(
            match.match_id
            for match in matches
            if any(getattr(match, field) is None for field in fields)
        )
    )
    return MetricCoverage(
        matches_played=len(matches),
        matches_with_value=len(matches) - len(missing),
        missing_match_ids=missing,
    )


def _round_statistics(matchday: int, fixtures: Sequence[MatchResult]) -> RoundStatistics:
    played = [match for match in fixtures if match.status == "played"]
    unplayed_count = sum(match.status == "unplayed" for match in fixtures)
    incomplete_count = sum(match.status == "incomplete" for match in fixtures)
    if not played:
        coverage = "not_started"
    elif incomplete_count:
        coverage = "incomplete"
    elif len(played) < len(fixtures):
        coverage = "partial"
    else:
        coverage = "complete"

    yellow_coverage = _card_coverage(played, ("home_yellow_cards", "away_yellow_cards"))
    red_coverage = _card_coverage(played, ("home_red_cards", "away_red_cards"))
    if not played:
        goals = yellows = reds = None
    else:
        goals = sum(match.home_goals + match.away_goals for match in played)
        yellows = (
            sum(match.home_yellow_cards + match.away_yellow_cards for match in played)
            if yellow_coverage.complete
            else None
        )
        reds = (
            sum(match.home_red_cards + match.away_red_cards for match in played)
            if red_coverage.complete
            else None
        )
    return RoundStatistics(
        matchday=matchday,
        scheduled_matches=len(fixtures),
        played_matches=len(played),
        unplayed_matches=unplayed_count,
        incomplete_matches=incomplete_count,
        coverage=coverage,
        goals=goals,
        yellow_cards=yellows,
        red_cards=reds,
        yellow_card_coverage=yellow_coverage,
        red_card_coverage=red_coverage,
    )


def _calculate_records(
    teams: Sequence[Team], matches: Sequence[MatchResult]
) -> CompetitionRecords:
    played = [match for match in matches if match.status == "played"]
    if not played:
        return CompetitionRecords(match_records=(), streaks=())

    specifications = (
        ("largest_home_win", [m for m in played if m.home_goals > m.away_goals], lambda m: m.home_goals - m.away_goals),
        ("largest_away_win", [m for m in played if m.away_goals > m.home_goals], lambda m: m.away_goals - m.home_goals),
        ("most_goals", played, lambda m: m.home_goals + m.away_goals),
    )
    match_records: list[RecordSet] = []
    for kind, candidates, measure in specifications:
        if not candidates:
            continue
        best = max(measure(match) for match in candidates)
        selected = sorted(
            (match for match in candidates if measure(match) == best),
            key=_match_sort_key,
        )
        match_records.append(
            RecordSet(
                kind=kind,
                measure=best,
                matches=tuple(_record_match(match) for match in selected),
            )
        )

    streaks: list[StreakRecord] = []
    for team in teams:
        team_matches = sorted(
            (
                match
                for match in played
                if team.team_id in (match.home_team_id, match.away_team_id)
            ),
            key=_match_sort_key,
        )
        outcomes = [(_outcome(match, team.team_id), match) for match in team_matches]
        for kind, predicate in _STREAK_PREDICATES:
            current: list[MatchResult] = []
            runs: list[tuple[MatchResult, ...]] = []
            for outcome, match in outcomes:
                if predicate(outcome):
                    current.append(match)
                else:
                    if current:
                        runs.append(tuple(current))
                    current = []
            if current:
                runs.append(tuple(current))
            if not runs:
                continue
            longest = max(len(run) for run in runs)
            for run in runs:
                if len(run) != longest:
                    continue
                ordered = tuple(sorted(run, key=_match_sort_key))
                streaks.append(
                    StreakRecord(
                        team_id=team.team_id,
                        kind=kind,
                        match_count=len(ordered),
                        matchday_start=ordered[0].matchday,
                        matchday_end=ordered[-1].matchday,
                        match_ids=tuple(match.match_id for match in ordered),
                    )
                )
    streaks.sort(key=lambda item: (item.kind, item.matchday_start, item.team_id, item.match_ids))
    return CompetitionRecords(match_records=tuple(match_records), streaks=tuple(streaks))


def _outcome(match: MatchResult, team_id: int) -> str:
    goals_for = match.home_goals if team_id == match.home_team_id else match.away_goals
    goals_against = match.away_goals if team_id == match.home_team_id else match.home_goals
    if goals_for > goals_against:
        return "W"
    if goals_for < goals_against:
        return "L"
    return "D"


_STREAK_PREDICATES: tuple[tuple[StreakKind, Callable[[str], bool]], ...] = (
    ("winning", lambda outcome: outcome == "W"),
    ("losing", lambda outcome: outcome == "L"),
    ("unbeaten", lambda outcome: outcome in {"W", "D"}),
    ("winless", lambda outcome: outcome in {"D", "L"}),
)


def _match_sort_key(match: MatchResult) -> tuple[int, str, tuple[int, int | str]]:
    if match.match_id.isdecimal():
        identity: tuple[int, int | str] = (0, int(match.match_id))
    else:
        identity = (1, match.match_id.casefold())
    return match.matchday, match.source_match_date.isoformat() if match.source_match_date else "", identity


def _record_match(match: MatchResult) -> MatchRecord:
    return MatchRecord(
        match_id=match.match_id,
        matchday=match.matchday,
        home_team_id=match.home_team_id,
        away_team_id=match.away_team_id,
        home_goals=match.home_goals,
        away_goals=match.away_goals,
    )
