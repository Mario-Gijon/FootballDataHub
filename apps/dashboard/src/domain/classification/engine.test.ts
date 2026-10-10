import { describe, expect, it, vi } from "vitest";
import matchesSource from "../../../../../data/exports/bdfutbol/group2_classification/derived-clas01b-20261010T102656Z/normalized/matches.json";
import jsReference from "./fixtures/bdfutbol-js-reference.json";
import type { Match, Team } from "../../api/contracts";
import {
  calculateStandings,
  createClassificationIndexes,
  type StandingsFilters,
} from "./engine";

const teams: Team[] = matchesSource.teams.map((team) => ({
  team_id: team.team_id,
  name: team.name,
  team_url: team.team_url,
  crest_url: team.crest_url,
}));

const matches: Match[] = matchesSource.matches.map((match) => ({
  match_id: match.match_id,
  matchday: match.matchday,
  matchday_date: match.matchday_date,
  source_match_date: match.source_match_date,
  home_team_id: match.home_team_id,
  away_team_id: match.away_team_id,
  home_goals: match.home_goals,
  away_goals: match.away_goals,
  home_yellow_cards: match.home_yellow_cards,
  away_yellow_cards: match.away_yellow_cards,
  home_red_cards: match.home_red_cards,
  away_red_cards: match.away_red_cards,
  status: match.status as Match["status"],
  unplayed_state: match.unplayed_state as Match["unplayed_state"],
  postponed_by_source_rule: match.postponed_by_source_rule,
}));

const baseFilters: StandingsFilters = {
  classificationType: "general",
  matchdayCap: 6,
  includePostponed: true,
  rangeType: "all",
  dateStart: null,
  dateEnd: null,
  roundStart: null,
  roundEnd: null,
};

type JsReference = {
  scenarios: Array<{
    name: string;
    filters: {
      classification_type: StandingsFilters["classificationType"];
      matchday_cap: number;
      include_postponed: boolean;
      range_type: StandingsFilters["rangeType"];
      date_start: string | null;
      date_end: string | null;
      round_start: number | null;
      round_end: number | null;
    };
    rows: Array<{
      team_id: number;
      position: number;
      points: number;
      matches_played: number;
      wins: number;
      draws: number;
      losses: number;
      goals_for: number;
      goals_against: number;
      yellow_cards: number;
      red_cards: number;
    }>;
  }>;
};

const reference = jsReference as JsReference;

function filtersFromReference(filters: JsReference["scenarios"][number]["filters"]): StandingsFilters {
  return {
    classificationType: filters.classification_type,
    matchdayCap: filters.matchday_cap,
    includePostponed: filters.include_postponed,
    rangeType: filters.range_type,
    dateStart: filters.date_start,
    dateEnd: filters.date_end,
    roundStart: filters.round_start,
    roundEnd: filters.round_end,
  };
}

function testTeam(id: number, name = `Equipo ${id}`): Team {
  return { team_id: id, name, team_url: null, crest_url: null };
}

function testMatch(
  matchId: string,
  homeId: number,
  awayId: number,
  homeGoals: number | null,
  awayGoals: number | null,
  options: Partial<Match> = {},
): Match {
  const played = homeGoals !== null && awayGoals !== null;
  return {
    match_id: matchId,
    matchday: 1,
    matchday_date: "2026-08-30",
    source_match_date: "2026-08-29",
    home_team_id: homeId,
    away_team_id: awayId,
    home_goals: homeGoals,
    away_goals: awayGoals,
    home_yellow_cards: 0,
    away_yellow_cards: 0,
    home_red_cards: 0,
    away_red_cards: 0,
    status: played ? "played" : "unplayed",
    unplayed_state: played ? null : "scheduled",
    postponed_by_source_rule: false,
    ...options,
  };
}

describe("equivalencia con la referencia JavaScript de BDFutbol", () => {
  it("construye índices de equipos y partidos por sus IDs estables", () => {
    const indexes = createClassificationIndexes(teams, matches);
    expect(indexes.teamsById.get(49)?.name).toBe("Jaén");
    expect(indexes.matchesById.get("272516")?.home_team_id).toBe(55);
    expect(indexes.teamOrderById.get(49)).toBe(teams.findIndex((team) => team.team_id === 49));
  });

  it("reproduce los nueve escenarios y los 1.800 campos observados", () => {
    let comparedFields = 0;

    for (const scenario of reference.scenarios) {
      const calculated = calculateStandings(teams, matches, filtersFromReference(scenario.filters));
      expect(calculated.rows).toHaveLength(20);
      const rowsById = new Map(calculated.rows.map((row) => [row.team.team_id, row]));

      for (const expected of scenario.rows) {
        const actual = rowsById.get(expected.team_id);
        expect(actual, `${scenario.name}: team ${expected.team_id}`).toBeDefined();
        expect({
          position: actual!.position,
          points: actual!.points,
          matches_played: actual!.matchesPlayed,
          wins: actual!.wins,
          draws: actual!.draws,
          losses: actual!.losses,
          goals_for: actual!.goalsFor,
          goals_against: actual!.goalsAgainst,
          yellow_cards: actual!.yellowCards,
          red_cards: actual!.redCards,
        }, `${scenario.name}: team ${expected.team_id}`).toEqual({
          position: expected.position,
          points: expected.points,
          matches_played: expected.matches_played,
          wins: expected.wins,
          draws: expected.draws,
          losses: expected.losses,
          goals_for: expected.goals_for,
          goals_against: expected.goals_against,
          yellow_cards: expected.yellow_cards,
          red_cards: expected.red_cards,
        });
        comparedFields += 10;
      }
    }

    expect(reference.scenarios).toHaveLength(9);
    expect(comparedFields).toBe(1800);
  });
});

describe("motor local sin dependencias de red", () => {
  it("calcula General, Local y Visitante e ignora fixtures sin marcador", () => {
    const sampleTeams = [testTeam(1, "Local"), testTeam(2, "Visitante"), testTeam(3, "Libre")];
    const sampleMatches = [
      testMatch("won", 1, 2, 2, 0),
      testMatch("pending", 2, 3, null, null),
    ];
    const general = calculateStandings(sampleTeams, sampleMatches, baseFilters);
    const local = calculateStandings(sampleTeams, sampleMatches, {
      ...baseFilters,
      classificationType: "local",
    });
    const visitor = calculateStandings(sampleTeams, sampleMatches, {
      ...baseFilters,
      classificationType: "visitor",
    });

    expect(general.matchesCounted).toBe(1);
    expect(general.unplayedMatchesSkipped).toBe(1);
    expect(general.rows.find((row) => row.team.team_id === 1)?.points).toBe(3);
    expect(general.rows.find((row) => row.team.team_id === 2)?.losses).toBe(1);
    expect(general.rows.find((row) => row.team.team_id === 3)?.matchesPlayed).toBe(0);
    expect(local.rows.find((row) => row.team.team_id === 1)?.wins).toBe(1);
    expect(local.rows.find((row) => row.team.team_id === 2)?.matchesPlayed).toBe(0);
    expect(visitor.rows.find((row) => row.team.team_id === 2)?.losses).toBe(1);
    expect(visitor.rows.find((row) => row.team.team_id === 1)?.matchesPlayed).toBe(0);
  });

  it("aplica límites inclusivos de fecha y jornada, combinados con el tope", () => {
    const sampleTeams = [testTeam(1), testTeam(2), testTeam(3)];
    const sampleMatches = [
      testMatch("r1", 1, 2, 1, 0, { matchday: 1, source_match_date: "2026-08-29" }),
      testMatch("r2", 2, 3, 1, 0, { matchday: 2, source_match_date: "2026-09-05" }),
      testMatch("r3", 3, 1, 1, 0, { matchday: 3, source_match_date: "2026-09-12" }),
    ];
    const rounds = calculateStandings(sampleTeams, sampleMatches, {
      ...baseFilters,
      matchdayCap: 3,
      rangeType: "rounds",
      roundStart: 2,
      roundEnd: 3,
    });
    const dates = calculateStandings(sampleTeams, sampleMatches, {
      ...baseFilters,
      matchdayCap: 3,
      rangeType: "dates",
      dateStart: "2026-09-05",
      dateEnd: "2026-09-12",
    });
    const capped = calculateStandings(sampleTeams, sampleMatches, {
      ...baseFilters,
      matchdayCap: 2,
      rangeType: "rounds",
      roundStart: 1,
      roundEnd: 2,
    });

    expect(rounds.matchesCounted).toBe(2);
    expect(dates.matchesCounted).toBe(2);
    expect(capped.matchesCounted).toBe(2);
  });

  it("incluye o excluye solo los encuentros marcados por la regla de fuente", () => {
    const sampleTeams = [testTeam(1), testTeam(2)];
    const match = testMatch("postponed", 1, 2, 1, 0, { postponed_by_source_rule: true });
    const included = calculateStandings(sampleTeams, [match], baseFilters);
    const excluded = calculateStandings(sampleTeams, [match], {
      ...baseFilters,
      includePostponed: false,
    });
    const unknown = calculateStandings(sampleTeams, [
      { ...match, postponed_by_source_rule: null },
    ], { ...baseFilters, includePostponed: false });

    expect(included.matchesCounted).toBe(1);
    expect(excluded.matchesCounted).toBe(0);
    expect(unknown.matchesCounted).toBe(1);
    expect(unknown.warnings.join(" ")).toContain("regla de aplazamiento");
  });

  it("usa disciplina para desempatar y conserva el orden si las tarjetas son incompletas", () => {
    const sampleTeams = [testTeam(1, "A"), testTeam(2, "B"), testTeam(3, "C"), testTeam(4, "D")];
    const decisive = [
      testMatch("a", 1, 2, 1, 0, { home_yellow_cards: 4 }),
      testMatch("b", 3, 4, 1, 0, { home_yellow_cards: 1 }),
    ];
    const disciplined = calculateStandings(sampleTeams, decisive, baseFilters);
    expect(disciplined.rows.slice(0, 2).map((row) => row.team.team_id)).toEqual([3, 1]);

    const catalogueOrder = [sampleTeams[1]!, sampleTeams[0]!];
    const incomplete = [testMatch("draw", 1, 2, 1, 1, { home_yellow_cards: null })];
    const stable = calculateStandings(catalogueOrder, incomplete, baseFilters);
    expect(stable.rows.map((row) => row.team.team_id)).toEqual([2, 1]);
    expect(stable.rows.find((row) => row.team.team_id === 1)?.yellowCards).toBeNull();
    expect(stable.warnings.join(" ")).toContain("Faltan tarjetas");
  });

  it("rechaza IDs duplicados o equipos fuera del catálogo y no necesita fetch", () => {
    const sampleTeams = [testTeam(1), testTeam(2)];
    const match = testMatch("one", 1, 2, 1, 0);
    const fetchMock = vi.fn(() => {
      throw new Error("No debe hacer peticiones.");
    });
    vi.stubGlobal("fetch", fetchMock);

    expect(() => calculateStandings(sampleTeams, [match, match], baseFilters)).toThrow("match_id duplicados");
    expect(() => calculateStandings(sampleTeams, [testMatch("unknown", 1, 99, 1, 0)], baseFilters)).toThrow("equipo desconocido");
    expect(calculateStandings(sampleTeams, [match], baseFilters).matchesCounted).toBe(1);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
