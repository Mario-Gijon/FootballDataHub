import type { Match, ProgressRecord, Team } from "../api/contracts";

export type TeamMatchVenue = "home" | "away";
export type TeamMatchResult = "win" | "draw" | "loss" | null;

export interface TeamMatchEntry {
  match: Match;
  homeTeam: Team;
  awayTeam: Team;
  venue: TeamMatchVenue;
  result: TeamMatchResult;
}

export interface TeamMatchCalendar {
  team: Team;
  matches: TeamMatchEntry[];
  progress: ProgressRecord[];
  playedCount: number;
  pendingCount: number;
  incompleteCount: number;
}

export interface TeamScoreRecord {
  kind: "score";
  id: string;
  label: string;
  value: number | null;
  matches: TeamMatchEntry[];
}

export interface TeamStreakRecord {
  kind: "streak";
  id: string;
  label: string;
  value: number | null;
  runs: TeamMatchEntry[][];
}

export type TeamRecord = TeamScoreRecord | TeamStreakRecord;

export function buildTeamMatchCalendar(
  teamId: number,
  teams: Team[],
  matches: Match[],
  progress: ProgressRecord[],
): TeamMatchCalendar {
  const teamById = new Map<number, Team>();
  for (const team of teams) {
    if (teamById.has(team.team_id)) throw new Error(`team_id duplicado: ${team.team_id}`);
    teamById.set(team.team_id, team);
  }
  const team = teamById.get(teamId);
  if (!team) throw new Error(`El equipo ${teamId} no existe en el catálogo recibido.`);

  const seenMatchIds = new Set<string>();
  const entries: TeamMatchEntry[] = [];
  for (const match of matches) {
    if (seenMatchIds.has(match.match_id)) throw new Error(`match_id duplicado: ${match.match_id}`);
    seenMatchIds.add(match.match_id);
    const homeTeam = teamById.get(match.home_team_id);
    const awayTeam = teamById.get(match.away_team_id);
    if (!homeTeam || !awayTeam) {
      throw new Error(`El partido ${match.match_id} referencia un equipo desconocido.`);
    }
    if (match.home_team_id !== teamId && match.away_team_id !== teamId) continue;
    if (match.status === "played" && (match.home_goals === null || match.away_goals === null)) {
      throw new Error(`El partido disputado ${match.match_id} carece de marcador completo.`);
    }
    entries.push({
      match,
      homeTeam,
      awayTeam,
      venue: match.home_team_id === teamId ? "home" : "away",
      result: resultForTeam(match, teamId),
    });
  }

  entries.sort(compareTeamFixtures);
  const seenProgress = new Set<string>();
  const teamProgress = progress.filter((record) => {
    if (!teamById.has(record.team_id)) {
      throw new Error(`El progreso de la jornada ${record.matchday} referencia un equipo desconocido.`);
    }
    const key = `${record.team_id}:${record.matchday}`;
    if (seenProgress.has(key)) throw new Error(`Progreso duplicado para equipo y jornada: ${key}`);
    seenProgress.add(key);
    return record.team_id === teamId;
  }).sort((left, right) => left.matchday - right.matchday);

  return {
    team,
    matches: entries,
    progress: teamProgress,
    playedCount: entries.filter(({ match }) => match.status === "played").length,
    pendingCount: entries.filter(({ match }) => match.status === "unplayed").length,
    incompleteCount: entries.filter(({ match }) => match.status === "incomplete").length,
  };
}

export function resultForTeam(match: Match, teamId: number): TeamMatchResult {
  if (match.status !== "played" || match.home_goals === null || match.away_goals === null) return null;
  const ownGoals = match.home_team_id === teamId ? match.home_goals : match.away_goals;
  const opponentGoals = match.home_team_id === teamId ? match.away_goals : match.home_goals;
  return ownGoals > opponentGoals ? "win" : ownGoals < opponentGoals ? "loss" : "draw";
}

export function calculateTeamRecords(entries: TeamMatchEntry[]): TeamRecord[] {
  const played = entries.filter(({ match }) =>
    match.status === "played" && match.home_goals !== null && match.away_goals !== null,
  );
  const scoreDefinitions = [
    { id: "largest-home-win", label: "Mayor victoria en casa", venue: "home", result: "win", margin: "own" },
    { id: "largest-away-win", label: "Mayor victoria fuera", venue: "away", result: "win", margin: "own" },
    { id: "largest-home-loss", label: "Mayor derrota en casa", venue: "home", result: "loss", margin: "opponent" },
    { id: "largest-away-loss", label: "Mayor derrota fuera", venue: "away", result: "loss", margin: "opponent" },
  ] as const;

  const scoreRecords: TeamScoreRecord[] = scoreDefinitions.map((definition) => {
    const candidates = played
      .filter((entry) => entry.venue === definition.venue && entry.result === definition.result)
      .map((entry) => ({ entry, margin: goalMargin(entry, definition.margin) }))
      .filter(({ margin }) => margin > 0);
    const bestMargin = candidates.reduce<number | null>(
      (best, candidate) => best === null || candidate.margin > best ? candidate.margin : best,
      null,
    );
    return {
      kind: "score",
      id: definition.id,
      label: definition.label,
      value: bestMargin,
      matches: bestMargin === null
        ? []
        : candidates.filter(({ margin }) => margin === bestMargin).map(({ entry }) => entry).sort(compareTeamFixtures),
    };
  });

  const segments = contiguousPlayedSegments(entries);
  const streakDefinitions: Array<{
    id: string;
    label: string;
    qualifies: (result: Exclude<TeamMatchResult, null>) => boolean;
  }> = [
    { id: "best-winning-streak", label: "Mejor racha de victorias", qualifies: (result) => result === "win" },
    { id: "worst-losing-streak", label: "Peor racha de derrotas", qualifies: (result) => result === "loss" },
    { id: "best-unbeaten-streak", label: "Mejor racha sin perder", qualifies: (result) => result !== "loss" },
    { id: "worst-winless-streak", label: "Peor racha sin ganar", qualifies: (result) => result !== "win" },
    { id: "longest-draw-streak", label: "Mayor racha de empates", qualifies: (result) => result === "draw" },
    { id: "longest-no-draw-streak", label: "Mayor racha sin empatar", qualifies: (result) => result !== "draw" },
  ];
  const streakRecords: TeamStreakRecord[] = streakDefinitions.map((definition) => {
    const runs = segments.flatMap((segment) => qualifyingRuns(segment, definition.qualifies));
    const longest = runs.reduce<number | null>(
      (best, run) => best === null || run.length > best ? run.length : best,
      null,
    );
    return {
      kind: "streak",
      id: definition.id,
      label: definition.label,
      value: longest,
      runs: longest === null
        ? []
        : runs.filter((run) => run.length === longest).sort(compareRuns),
    };
  });

  return [...scoreRecords, ...streakRecords];
}

function goalMargin(entry: TeamMatchEntry, perspective: "own" | "opponent"): number {
  const ownGoals = entry.venue === "home" ? entry.match.home_goals! : entry.match.away_goals!;
  const opponentGoals = entry.venue === "home" ? entry.match.away_goals! : entry.match.home_goals!;
  return perspective === "own" ? ownGoals - opponentGoals : opponentGoals - ownGoals;
}

function contiguousPlayedSegments(entries: TeamMatchEntry[]): TeamMatchEntry[][] {
  const segments: TeamMatchEntry[][] = [];
  let current: TeamMatchEntry[] = [];
  let lastMatchday: number | null = null;
  const flush = () => {
    if (current.length) segments.push(current);
    current = [];
  };

  for (const entry of [...entries].sort(compareTeamFixtures)) {
    const { match } = entry;
    const isPlayed = match.status === "played" && match.home_goals !== null && match.away_goals !== null;
    if (!isPlayed) {
      flush();
      lastMatchday = match.matchday;
      continue;
    }
    if (lastMatchday !== null && match.matchday !== lastMatchday + 1) flush();
    current.push(entry);
    lastMatchday = match.matchday;
  }
  flush();
  return segments;
}

function qualifyingRuns(
  segment: TeamMatchEntry[],
  qualifies: (result: Exclude<TeamMatchResult, null>) => boolean,
): TeamMatchEntry[][] {
  const runs: TeamMatchEntry[][] = [];
  let current: TeamMatchEntry[] = [];
  for (const entry of segment) {
    if (entry.result && qualifies(entry.result)) current.push(entry);
    else if (current.length) {
      runs.push(current);
      current = [];
    }
  }
  if (current.length) runs.push(current);
  return runs;
}

function compareTeamFixtures(left: TeamMatchEntry, right: TeamMatchEntry): number {
  if (left.match.matchday !== right.match.matchday) return left.match.matchday - right.match.matchday;
  const leftDate = left.match.source_match_date ?? left.match.matchday_date ?? "9999-12-31";
  const rightDate = right.match.source_match_date ?? right.match.matchday_date ?? "9999-12-31";
  const dateOrder = leftDate.localeCompare(rightDate);
  if (dateOrder !== 0) return dateOrder;
  return compareMatchIds(left.match.match_id, right.match.match_id);
}

function compareRuns(left: TeamMatchEntry[], right: TeamMatchEntry[]): number {
  return compareTeamFixtures(left[0]!, right[0]!);
}

function compareMatchIds(left: string, right: string): number {
  if (/^\d+$/.test(left) && /^\d+$/.test(right)) return Number(left) - Number(right);
  return left.localeCompare(right, "en", { numeric: true });
}
