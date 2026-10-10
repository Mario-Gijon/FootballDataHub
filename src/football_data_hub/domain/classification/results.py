"""Pure local queries for competition results and matchup matrices."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from .models import MatchResult, MatchStatus, Team

MatchOutcome = Literal["home_win", "draw", "home_loss"]
MatrixCellState = Literal["diagonal", "fixture", "missing"]


@dataclass(frozen=True, slots=True)
class MatchListEntry:
    """A match joined to its catalog teams for a results-list presentation."""

    match: MatchResult
    home_team: Team
    away_team: Team


@dataclass(frozen=True, slots=True)
class ResultsMatrixCell:
    """One directed home-team/away-team pairing in the local matrix model.

    ``outcome`` is computed from the home team's perspective. Its eventual
    visual color is a frontend choice; BDFutbol's matrix palette was not
    observable in the saved capture.
    """

    row_team_id: int
    column_team_id: int
    state: MatrixCellState
    match_id: str | None
    match_status: MatchStatus | None
    home_goals: int | None
    away_goals: int | None
    outcome: MatchOutcome | None


@dataclass(frozen=True, slots=True)
class ResultsMatrixRow:
    team: Team
    cells: tuple[ResultsMatrixCell, ...]


@dataclass(frozen=True, slots=True)
class ResultsMatrix:
    """Square matrix; row and column order follow the supplied team catalog."""

    teams: tuple[Team, ...]
    rows: tuple[ResultsMatrixRow, ...]


def list_competition_results(
    teams: tuple[Team, ...] | list[Team],
    matches: tuple[MatchResult, ...] | list[MatchResult],
    *,
    matchday: int | None = None,
) -> tuple[MatchListEntry, ...]:
    """Return all matches or one matchday, joined by stable team IDs.

    Results are sorted by source match date, matchday, then numeric BDFutbol
    match ID (or lexicographic ID when it is not numeric). ``matchday=None``
    is the local query meaning “all fixtures in this stored dataset”.
    """

    if matchday is not None and not 1 <= matchday <= 38:
        raise ValueError("matchday debe estar entre 1 y 38")
    team_by_id = _team_index(teams)
    match_ids: set[str] = set()
    entries: list[MatchListEntry] = []
    for match in matches:
        if match.match_id in match_ids:
            raise ValueError(f"match_id duplicado: {match.match_id}")
        match_ids.add(match.match_id)
        try:
            home_team = team_by_id[match.home_team_id]
            away_team = team_by_id[match.away_team_id]
        except KeyError as exc:
            raise ValueError(f"El partido {match.match_id} referencia un equipo desconocido") from exc
        if matchday is None or match.matchday == matchday:
            entries.append(MatchListEntry(match, home_team, away_team))
    return tuple(sorted(entries, key=lambda entry: _match_sort_key(entry.match)))


def build_results_matrix(
    teams: tuple[Team, ...] | list[Team],
    matches: tuple[MatchResult, ...] | list[MatchResult],
) -> ResultsMatrix:
    """Build a matrix from existing results without persisting duplicate scores.

    This model follows the project's conceptual orientation: rows are home
    teams and columns are away teams. Missing pairs are explicitly ``missing``
    and are not treated as pending fixtures. A future source comparison may
    still revise whether this orientation matches BDFutbol's own presentation.
    """

    team_catalog = tuple(teams)
    team_by_id = _team_index(team_catalog)
    match_by_pair: dict[tuple[int, int], MatchResult] = {}
    match_ids: set[str] = set()
    for match in matches:
        if match.match_id in match_ids:
            raise ValueError(f"match_id duplicado: {match.match_id}")
        match_ids.add(match.match_id)
        if match.home_team_id not in team_by_id or match.away_team_id not in team_by_id:
            raise ValueError(f"El partido {match.match_id} referencia un equipo desconocido")
        pair = (match.home_team_id, match.away_team_id)
        if pair in match_by_pair:
            raise ValueError(f"Fixture local/visitante duplicado: {pair}")
        match_by_pair[pair] = match

    rows: list[ResultsMatrixRow] = []
    for row_team in team_catalog:
        cells: list[ResultsMatrixCell] = []
        for column_team in team_catalog:
            if row_team.team_id == column_team.team_id:
                cells.append(
                    ResultsMatrixCell(
                        row_team_id=row_team.team_id,
                        column_team_id=column_team.team_id,
                        state="diagonal",
                        match_id=None,
                        match_status=None,
                        home_goals=None,
                        away_goals=None,
                        outcome=None,
                    )
                )
                continue
            match = match_by_pair.get((row_team.team_id, column_team.team_id))
            if match is None:
                cells.append(
                    ResultsMatrixCell(
                        row_team_id=row_team.team_id,
                        column_team_id=column_team.team_id,
                        state="missing",
                        match_id=None,
                        match_status=None,
                        home_goals=None,
                        away_goals=None,
                        outcome=None,
                    )
                )
                continue
            outcome = None
            if match.status == "played":
                assert match.home_goals is not None and match.away_goals is not None
                outcome = (
                    "home_win"
                    if match.home_goals > match.away_goals
                    else "draw"
                    if match.home_goals == match.away_goals
                    else "home_loss"
                )
            cells.append(
                ResultsMatrixCell(
                    row_team_id=row_team.team_id,
                    column_team_id=column_team.team_id,
                    state="fixture",
                    match_id=match.match_id,
                    match_status=match.status,
                    home_goals=match.home_goals,
                    away_goals=match.away_goals,
                    outcome=outcome,
                )
            )
        rows.append(ResultsMatrixRow(team=row_team, cells=tuple(cells)))
    return ResultsMatrix(teams=team_catalog, rows=tuple(rows))


def list_group2_results(
    teams: tuple[Team, ...] | list[Team],
    matches: tuple[MatchResult, ...] | list[MatchResult],
    *,
    matchday: int | None = None,
) -> tuple[MatchListEntry, ...]:
    """Backward-compatible alias for the former Group II query name."""
    return list_competition_results(teams, matches, matchday=matchday)


def build_group2_results_matrix(
    teams: tuple[Team, ...] | list[Team],
    matches: tuple[MatchResult, ...] | list[MatchResult],
) -> ResultsMatrix:
    """Backward-compatible alias for the former Group II matrix name."""
    return build_results_matrix(teams, matches)


def _team_index(teams: tuple[Team, ...] | list[Team]) -> dict[int, Team]:
    team_by_id: dict[int, Team] = {}
    for team in teams:
        if team.team_id in team_by_id:
            raise ValueError(f"team_id duplicado: {team.team_id}")
        team_by_id[team.team_id] = team
    return team_by_id


def _match_sort_key(match: MatchResult) -> tuple[date, int, tuple[int, int | str]]:
    source_date = match.source_match_date or date.max
    if match.match_id.isdecimal():
        stable_id: tuple[int, int | str] = (0, int(match.match_id))
    else:
        stable_id = (1, match.match_id.casefold())
    return source_date, match.matchday, stable_id
