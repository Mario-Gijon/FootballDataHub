import type { Match, Team } from "../api/contracts";

export type MatchOutcome = "home_win" | "draw" | "home_loss";
export type MatrixCellState = "diagonal" | "fixture" | "missing";

export interface ListedMatch {
  match: Match;
  homeTeam: Team;
  awayTeam: Team;
}

export interface ResultsMatrixCell {
  rowTeamId: number;
  columnTeamId: number;
  state: MatrixCellState;
  match: Match | null;
  outcome: MatchOutcome | null;
}

export interface ResultsMatrixRow {
  team: Team;
  cells: ResultsMatrixCell[];
}

export function listResults(
  teams: Team[],
  matches: Match[],
  matchday: number | null,
): ListedMatch[] {
  if (matchday !== null && (!Number.isInteger(matchday) || matchday < 1 || matchday > 38)) {
    throw new RangeError("La jornada debe estar entre 1 y 38.");
  }
  const teamById = new Map<number, Team>();
  for (const team of teams) {
    if (teamById.has(team.team_id)) throw new Error(`team_id duplicado: ${team.team_id}`);
    teamById.set(team.team_id, team);
  }

  const seenMatchIds = new Set<string>();
  for (const match of matches) {
    if (seenMatchIds.has(match.match_id)) throw new Error(`match_id duplicado: ${match.match_id}`);
    seenMatchIds.add(match.match_id);
    if (!teamById.has(match.home_team_id) || !teamById.has(match.away_team_id)) {
      throw new Error(`El partido ${match.match_id} referencia un equipo desconocido.`);
    }
  }
  return matches
    .filter((match) => matchday === null || match.matchday === matchday)
    .map((match) => {
      const homeTeam = teamById.get(match.home_team_id);
      const awayTeam = teamById.get(match.away_team_id);
      if (!homeTeam || !awayTeam) throw new Error(`El partido ${match.match_id} referencia un equipo desconocido.`);
      return { match, homeTeam, awayTeam };
    })
    .sort((left, right) => {
      const dateOrder = (left.match.source_match_date ?? "9999-12-31")
        .localeCompare(right.match.source_match_date ?? "9999-12-31");
      if (dateOrder !== 0) return dateOrder;
      if (left.match.matchday !== right.match.matchday) return left.match.matchday - right.match.matchday;
      return compareMatchIds(left.match.match_id, right.match.match_id);
    });
}

export function buildResultsMatrix(teams: Team[], matches: Match[]): ResultsMatrixRow[] {
  const teamIds = new Set<number>();
  for (const team of teams) {
    if (teamIds.has(team.team_id)) throw new Error(`team_id duplicado: ${team.team_id}`);
    teamIds.add(team.team_id);
  }
  const matchByPair = new Map<string, Match>();
  const matchIds = new Set<string>();
  for (const match of matches) {
    if (matchIds.has(match.match_id)) throw new Error(`match_id duplicado: ${match.match_id}`);
    matchIds.add(match.match_id);
    if (!teamIds.has(match.home_team_id) || !teamIds.has(match.away_team_id)) {
      throw new Error(`El partido ${match.match_id} referencia un equipo desconocido.`);
    }
    const pair = `${match.home_team_id}:${match.away_team_id}`;
    if (matchByPair.has(pair)) throw new Error(`Fixture local/visitante duplicado: ${pair}`);
    matchByPair.set(pair, match);
  }

  return teams.map((rowTeam) => ({
    team: rowTeam,
    cells: teams.map((columnTeam): ResultsMatrixCell => {
      if (rowTeam.team_id === columnTeam.team_id) {
        return { rowTeamId: rowTeam.team_id, columnTeamId: columnTeam.team_id, state: "diagonal", match: null, outcome: null };
      }
      const match = matchByPair.get(`${rowTeam.team_id}:${columnTeam.team_id}`) ?? null;
      if (!match) {
        return { rowTeamId: rowTeam.team_id, columnTeamId: columnTeam.team_id, state: "missing", match: null, outcome: null };
      }
      const outcome = match.status !== "played"
        ? null
        : match.home_goals! > match.away_goals!
          ? "home_win"
          : match.home_goals === match.away_goals
            ? "draw"
            : "home_loss";
      return { rowTeamId: rowTeam.team_id, columnTeamId: columnTeam.team_id, state: "fixture", match, outcome };
    }),
  }));
}

function compareMatchIds(left: string, right: string): number {
  if (/^\d+$/.test(left) && /^\d+$/.test(right)) return Number(left) - Number(right);
  return left.localeCompare(right, "en", { numeric: true });
}
