import type { Match, Team } from "../../api/contracts";

export type ClassificationType = "general" | "local" | "visitor";
export type RangeType = "all" | "dates" | "rounds";

export interface StandingsFilters {
  classificationType: ClassificationType;
  matchdayCap: number;
  includePostponed: boolean;
  rangeType: RangeType;
  dateStart: string | null;
  dateEnd: string | null;
  roundStart: number | null;
  roundEnd: number | null;
}

export interface StandingRow {
  team: Team;
  position: number;
  points: number;
  matchesPlayed: number;
  wins: number;
  draws: number;
  losses: number;
  goalsFor: number;
  goalsAgainst: number;
  yellowCards: number | null;
  redCards: number | null;
  goalDifference: number;
  disciplinaryScore: number | null;
}

export interface CalculatedTable {
  classificationType: ClassificationType;
  selectedMatchday: number;
  selectedMatchdayDate: string | null;
  includePostponed: boolean;
  rangeType: RangeType;
  dateStart: string | null;
  dateEnd: string | null;
  roundStart: number | null;
  roundEnd: number | null;
  matchesAvailable: number;
  matchesCounted: number;
  unplayedMatchesSkipped: number;
  incompleteMatchesSkipped: number;
  rows: StandingRow[];
  warnings: string[];
}

export interface ClassificationIndexes {
  teamsById: ReadonlyMap<number, Team>;
  matchesById: ReadonlyMap<string, Match>;
  teamOrderById: ReadonlyMap<number, number>;
}

interface TeamTotals {
  points: number;
  matchesPlayed: number;
  wins: number;
  draws: number;
  losses: number;
  goalsFor: number;
  goalsAgainst: number;
  yellowCards: number;
  redCards: number;
  cardsComplete: boolean;
}

const createTotals = (): TeamTotals => ({
  points: 0,
  matchesPlayed: 0,
  wins: 0,
  draws: 0,
  losses: 0,
  goalsFor: 0,
  goalsAgainst: 0,
  yellowCards: 0,
  redCards: 0,
  cardsComplete: true,
});

export function calculateStandings(
  teams: readonly Team[],
  matches: readonly Match[],
  filters: StandingsFilters,
  indexes: ClassificationIndexes = createClassificationIndexes(teams, matches),
): CalculatedTable {
  validateInput(teams, matches, filters, indexes);

  const teamOrder = indexes.teamOrderById;
  const totals = new Map(teams.map((team) => [team.team_id, createTotals()]));
  const selectedMatchday = filters.matchdayCap;
  const selectedMatchdayDate =
    [...indexes.matchesById.values()].find((match) => match.matchday === selectedMatchday && match.matchday_date)
      ?.matchday_date ?? null;
  const warnings = new Set<string>();
  let matchesAvailable = 0;
  let matchesCounted = 0;
  let unplayedMatchesSkipped = 0;
  let incompleteMatchesSkipped = 0;
  let hasUnknownPostponement = false;

  for (const match of indexes.matchesById.values()) {
    const { eligible, warning } = matchesFilter(match, filters, selectedMatchday);
    if (warning) warnings.add(warning);
    if (!eligible) continue;

    if (!filters.includePostponed && match.postponed_by_source_rule === null) {
      hasUnknownPostponement = true;
    }
    matchesAvailable += 1;
    if (match.status === "unplayed") {
      unplayedMatchesSkipped += 1;
      continue;
    }
    if (match.status === "incomplete") {
      incompleteMatchesSkipped += 1;
      continue;
    }

    // The API contract guarantees both goals for a played match.
    const homeGoals = match.home_goals as number;
    const awayGoals = match.away_goals as number;
    matchesCounted += 1;
    if (filters.classificationType === "general" || filters.classificationType === "local") {
      addResult(
        totals.get(match.home_team_id)!,
        homeGoals,
        awayGoals,
        match.home_yellow_cards,
        match.home_red_cards,
      );
    }
    if (filters.classificationType === "general" || filters.classificationType === "visitor") {
      addResult(
        totals.get(match.away_team_id)!,
        awayGoals,
        homeGoals,
        match.away_yellow_cards,
        match.away_red_cards,
      );
    }
  }

  if (hasUnknownPostponement) {
    warnings.add(
      "Hay partidos cuya fecha no permite evaluar la regla de aplazamiento; se conservaron en el cálculo.",
    );
  }

  const primaryGroups = new Map<string, Team[]>();
  for (const team of teams) {
    const row = totals.get(team.team_id)!;
    const primaryKey = `${row.points}:${row.goalsFor - row.goalsAgainst}:${row.goalsFor}`;
    const group = primaryGroups.get(primaryKey) ?? [];
    group.push(team);
    primaryGroups.set(primaryKey, group);
  }

  const orderedTeams: Team[] = [];
  const groups = [...primaryGroups.values()].sort((left, right) => {
    const a = totals.get(left[0]!.team_id)!;
    const b = totals.get(right[0]!.team_id)!;
    return (
      b.points - a.points ||
      (b.goalsFor - b.goalsAgainst) - (a.goalsFor - a.goalsAgainst) ||
      b.goalsFor - a.goalsFor
    );
  });

  for (const group of groups) {
    const cardsComplete = group.every((team) => totals.get(team.team_id)!.cardsComplete);
    if (cardsComplete) {
      group.sort((left, right) => {
        const a = totals.get(left.team_id)!;
        const b = totals.get(right.team_id)!;
        return (
          a.redCards * 2 + a.yellowCards - (b.redCards * 2 + b.yellowCards) ||
          teamOrder.get(left.team_id)! - teamOrder.get(right.team_id)!
        );
      });
    } else {
      group.sort((left, right) => teamOrder.get(left.team_id)! - teamOrder.get(right.team_id)!);
    }
    orderedTeams.push(...group);
  }

  const rows = orderedTeams.map((team, index): StandingRow => {
    const row = totals.get(team.team_id)!;
    const yellowCards = row.cardsComplete ? row.yellowCards : null;
    const redCards = row.cardsComplete ? row.redCards : null;
    return {
      team,
      position: index + 1,
      points: row.points,
      matchesPlayed: row.matchesPlayed,
      wins: row.wins,
      draws: row.draws,
      losses: row.losses,
      goalsFor: row.goalsFor,
      goalsAgainst: row.goalsAgainst,
      yellowCards,
      redCards,
      goalDifference: row.goalsFor - row.goalsAgainst,
      disciplinaryScore:
        yellowCards === null || redCards === null ? null : yellowCards + redCards * 2,
    };
  });

  if (rows.some((row) => row.yellowCards === null || row.redCards === null)) {
    warnings.add("Faltan tarjetas en al menos un partido disputado incluido.");
  }
  if (incompleteMatchesSkipped > 0) {
    warnings.add(`Se omitieron ${incompleteMatchesSkipped} partidos incompletos.`);
  }

  return {
    classificationType: filters.classificationType,
    selectedMatchday,
    selectedMatchdayDate,
    includePostponed: filters.includePostponed,
    rangeType: filters.rangeType,
    dateStart: filters.dateStart,
    dateEnd: filters.dateEnd,
    roundStart: filters.roundStart,
    roundEnd: filters.roundEnd,
    matchesAvailable,
    matchesCounted,
    unplayedMatchesSkipped,
    incompleteMatchesSkipped,
    rows,
    warnings: [...warnings],
  };
}

export function createClassificationIndexes(
  teams: readonly Team[],
  matches: readonly Match[],
): ClassificationIndexes {
  if (teams.length === 0) throw new Error("Se requiere un catálogo de equipos.");

  const teamsById = new Map(teams.map((team) => [team.team_id, team]));
  if (teamsById.size !== teams.length) throw new Error("Hay team_id duplicados.");

  const matchesById = new Map(matches.map((match) => [match.match_id, match]));
  if (matchesById.size !== matches.length) {
    throw new Error("Hay match_id duplicados; se rechaza el doble cómputo.");
  }
  for (const match of matchesById.values()) {
    if (!teamsById.has(match.home_team_id) || !teamsById.has(match.away_team_id)) {
      throw new Error(`El partido ${match.match_id} referencia un equipo desconocido.`);
    }
  }

  return {
    teamsById,
    matchesById,
    teamOrderById: new Map(teams.map((team, index) => [team.team_id, index])),
  };
}

function validateInput(
  teams: readonly Team[],
  matches: readonly Match[],
  filters: StandingsFilters,
  indexes: ClassificationIndexes,
): void {
  if (teams.length === 0) throw new Error("Se requiere un catálogo de equipos.");
  if (indexes.teamsById.size !== teams.length) throw new Error("Hay team_id duplicados.");
  if (indexes.matchesById.size !== matches.length) {
    throw new Error("Hay match_id duplicados; se rechaza el doble cómputo.");
  }
  for (const match of matches) {
    if (!indexes.teamsById.has(match.home_team_id) || !indexes.teamsById.has(match.away_team_id)) {
      throw new Error(`El partido ${match.match_id} referencia un equipo desconocido.`);
    }
  }
  if (!Number.isInteger(filters.matchdayCap) || filters.matchdayCap < 1 || filters.matchdayCap > 38) {
    throw new Error("La jornada debe estar entre 1 y 38.");
  }
  if (filters.rangeType === "dates") {
    if (!filters.dateStart || !filters.dateEnd || filters.dateStart > filters.dateEnd) {
      throw new Error("El rango de fechas requiere límites válidos e inclusivos.");
    }
  }
  if (filters.rangeType === "rounds") {
    if (
      filters.roundStart === null ||
      filters.roundEnd === null ||
      filters.roundStart < 1 ||
      filters.roundStart > filters.roundEnd ||
      filters.roundEnd > filters.matchdayCap
    ) {
      throw new Error("El rango de jornadas debe ser válido y no superar la jornada seleccionada.");
    }
  }
}

function matchesFilter(
  match: Match,
  filters: StandingsFilters,
  selectedMatchday: number,
): { eligible: boolean; warning: string | null } {
  if (match.matchday > selectedMatchday) return { eligible: false, warning: null };
  if (!filters.includePostponed && match.postponed_by_source_rule === true) {
    return { eligible: false, warning: null };
  }
  if (filters.rangeType === "dates") {
    if (match.source_match_date === null) {
      return {
        eligible: false,
        warning: "Se omitió un registro sin fecha al aplicar el rango de fechas.",
      };
    }
    if (match.source_match_date < filters.dateStart! || match.source_match_date > filters.dateEnd!) {
      return { eligible: false, warning: null };
    }
  } else if (filters.rangeType === "rounds") {
    if (match.matchday < filters.roundStart! || match.matchday > filters.roundEnd!) {
      return { eligible: false, warning: null };
    }
  }
  return { eligible: true, warning: null };
}

function addResult(
  totals: TeamTotals,
  goalsFor: number,
  goalsAgainst: number,
  yellowCards: number | null,
  redCards: number | null,
): void {
  totals.matchesPlayed += 1;
  totals.goalsFor += goalsFor;
  totals.goalsAgainst += goalsAgainst;
  if (goalsFor > goalsAgainst) {
    totals.wins += 1;
    totals.points += 3;
  } else if (goalsFor === goalsAgainst) {
    totals.draws += 1;
    totals.points += 1;
  } else {
    totals.losses += 1;
  }
  if (yellowCards === null || redCards === null) {
    totals.cardsComplete = false;
  } else {
    totals.yellowCards += yellowCards;
    totals.redCards += redCards;
  }
}
