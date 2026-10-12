import { describe, expect, it } from "vitest";
import group1MatchSource from "../../../../data/exports/bdfutbol/group1_classification/20261010T202500.293648Z-b770724f/normalized/matches.json";
import group1ProgressSource from "../../../../data/exports/bdfutbol/group1_classification/20261010T202500.293648Z-b770724f/normalized/progress.json";
import group2MatchSource from "../../../../data/exports/bdfutbol/group2_classification/derived-res01-20261010T102656Z/normalized/matches.json";
import group2ProgressSource from "../../../../data/exports/bdfutbol/group2_classification/20261010T102656.252222Z-72f200ad/normalized/progress.json";
import type { Match, ProgressRecord, Team } from "../api/contracts";
import { buildTeamMatchCalendar, calculateTeamRecords, resultForTeam } from "./team-matches";

const group1 = {
  teams: group1MatchSource.teams as unknown as Team[],
  matches: group1MatchSource.matches as unknown as Match[],
  progress: group1ProgressSource.records as ProgressRecord[],
};
const group2 = {
  teams: group2MatchSource.teams as unknown as Team[],
  matches: group2MatchSource.matches as unknown as Match[],
  progress: group2ProgressSource.records as ProgressRecord[],
};

function match(overrides: Partial<Match> = {}): Match {
  return {
    match_id: "m1",
    matchday: 1,
    matchday_date: "2026-08-30",
    source_match_date: "2026-08-29",
    home_team_id: 1,
    away_team_id: 2,
    home_goals: 0,
    away_goals: 3,
    home_yellow_cards: null,
    away_yellow_cards: null,
    home_red_cards: null,
    away_red_cards: null,
    status: "played",
    unplayed_state: null,
    postponed_by_source_rule: false,
    source_match_url: "https://www.bdfutbol.com/es/p/p.php?id=m1",
    stadium_id: null,
    stadium_name: null,
    stadium_url: null,
    referee_id: null,
    referee_name: null,
    referee_url: null,
    ...overrides,
  };
}

const teams: Team[] = [
  { team_id: 1, name: "Local", team_url: null, crest_url: null },
  { team_id: 2, name: "Visitante", team_url: null, crest_url: null },
];

describe("calendario de partidos por equipo", () => {
  it("selecciona por ID y conserva los 38 partidos de cada equipo en ambos grupos", () => {
    for (const source of [group1, group2]) {
      expect(source.teams).toHaveLength(20);
      expect(source.matches).toHaveLength(380);
      for (const team of source.teams) {
        const calendar = buildTeamMatchCalendar(team.team_id, source.teams, source.matches, source.progress);
        expect(calendar.matches).toHaveLength(38);
        expect(calendar.matches.every(({ match: item }) => item.home_team_id === team.team_id || item.away_team_id === team.team_id)).toBe(true);
        expect(calendar.matches.map(({ match: item }) => item.matchday)).toEqual([...Array(38)].map((_, index) => index + 1));
      }
    }
    expect(buildTeamMatchCalendar(48, group1.teams, group1.matches, group1.progress).team.name).toBe("Racing de Ferrol");
    expect(buildTeamMatchCalendar(49, group2.teams, group2.matches, group2.progress).team.name).toBe("Jaén");
  });

  it("determina victorias, empates y derrotas desde el equipo seleccionado", () => {
    const awayWin = match();
    const homeWin = match({ match_id: "m2", home_goals: 3, away_goals: 0 });
    const draw = match({ match_id: "m3", home_goals: 2, away_goals: 2 });
    expect(resultForTeam(awayWin, 2)).toBe("win");
    expect(resultForTeam(awayWin, 1)).toBe("loss");
    expect(resultForTeam(homeWin, 1)).toBe("win");
    expect(resultForTeam(homeWin, 2)).toBe("loss");
    expect(resultForTeam(draw, 1)).toBe("draw");
    expect(resultForTeam(draw, 2)).toBe("draw");
  });

  it("conserva partidos pendientes e incompletos sin convertirlos en empates", () => {
    const pending = match({ match_id: "m2", matchday: 2, source_match_date: null, home_goals: null, away_goals: null, status: "unplayed", unplayed_state: "scheduled", stadium_name: "Campo", stadium_url: "https://example.com/stadium", referee_name: null });
    const incomplete = match({ match_id: "m3", matchday: 3, home_goals: 1, away_goals: null, status: "incomplete" });
    const calendar = buildTeamMatchCalendar(2, teams, [match(), pending, incomplete], []);
    expect(calendar.matches.map(({ match: item }) => [item.status, item.matchday_date, item.source_match_date])).toEqual([
      ["played", "2026-08-30", "2026-08-29"],
      ["unplayed", "2026-08-30", null],
      ["incomplete", "2026-08-30", "2026-08-29"],
    ]);
    expect(calendar.matches[1]?.venue).toBe("away");
    expect(calendar.matches[1]?.match.stadium_name).toBe("Campo");
    expect(calendar.matches[1]?.match.stadium_url).toBe("https://example.com/stadium");
    expect(calendar.matches[1]?.match.referee_name).toBeNull();
    expect(calendar.matches[1]?.result).toBeNull();
    expect(calendar.matches[2]?.result).toBeNull();
    expect(calendar.playedCount).toBe(1);
    expect(calendar.pendingCount).toBe(1);
    expect(calendar.incompleteCount).toBe(1);
    const recordValues = new Map(calculateTeamRecords(calendar.matches).map((record) => [record.id, record.value]));
    expect(recordValues.get("largest-away-win")).toBe(3);
    expect(recordValues.get("largest-home-loss")).toBeNull();
    expect(recordValues.get("best-winning-streak")).toBe(1);
  });

  it("rechaza IDs duplicados y referencias a equipos desconocidos", () => {
    expect(() => buildTeamMatchCalendar(1, teams, [match(), match()], [])).toThrow(/match_id duplicado/);
    expect(() => buildTeamMatchCalendar(1, teams, [match({ away_team_id: 99 })], [])).toThrow(/equipo desconocido/);
    expect(() => buildTeamMatchCalendar(99, teams, [], [])).toThrow(/no existe/);
  });

  it("preserva valores null del progreso y no crea jornadas posteriores a la captura", () => {
    const records = group2.progress.filter((item) => item.team_id === 49);
    const calendar = buildTeamMatchCalendar(49, group2.teams, group2.matches, group2.progress);
    expect(calendar.progress).toEqual(records);
    expect(calendar.progress.map((item) => item.matchday)).toEqual([1, 2, 3, 4, 5, 6]);
    expect(calendar.progress.every((item) => item.position !== null)).toBe(true);
    const withNull: ProgressRecord = { team_id: 49, matchday: 7, matchday_date: null, position: null, points: null, goals_for: null, goals_against: null };
    const withNullCalendar = buildTeamMatchCalendar(49, group2.teams, group2.matches, [...group2.progress, withNull]);
    expect(withNullCalendar.progress.at(-1)).toEqual(withNull);
  });

  it("calcula los récords del Jaén y conserva los empates entre marcas", () => {
    const calendar = buildTeamMatchCalendar(49, group2.teams, group2.matches, group2.progress);
    const records = calculateTeamRecords(calendar.matches);
    const byId = new Map(records.map((record) => [record.id, record]));
    expect(byId.get("largest-home-win")).toMatchObject({ value: 1 });
    expect((byId.get("largest-home-win") as { matches: Array<{ match: Match; homeTeam: Team; awayTeam: Team }> }).matches.map(({ awayTeam }) => awayTeam.name)).toContain("UD Ibiza");
    expect(byId.get("largest-away-win")).toMatchObject({ value: 3 });
    expect(byId.get("largest-away-loss")).toMatchObject({ value: 2 });
    expect(byId.get("best-winning-streak")).toMatchObject({ value: 2 });
    expect(byId.get("worst-losing-streak")).toMatchObject({ value: 1 });
    expect(byId.get("best-unbeaten-streak")).toMatchObject({ value: 4 });
    expect(byId.get("worst-winless-streak")).toMatchObject({ value: 2 });
    expect(byId.get("longest-draw-streak")).toMatchObject({ value: 1 });
    expect(byId.get("longest-no-draw-streak")).toMatchObject({ value: 3 });
    const drawRecord = byId.get("longest-draw-streak");
    expect(drawRecord?.kind === "streak" ? drawRecord.runs : []).toHaveLength(2);
  });

  it("interrumpe rachas en jornadas sin partido disputado o cuando falta una jornada", () => {
    const played1 = match({ matchday: 1, match_id: "1" });
    const pending2 = match({ matchday: 2, match_id: "2", home_goals: null, away_goals: null, status: "unplayed", unplayed_state: "scheduled" });
    const played3 = match({ matchday: 3, match_id: "3" });
    const played5 = match({ matchday: 5, match_id: "5" });
    const calendar = buildTeamMatchCalendar(2, teams, [played1, pending2, played3, played5], []);
    const winning = calculateTeamRecords(calendar.matches).find((record) => record.id === "best-winning-streak");
    expect(winning?.value).toBe(1);
    expect(winning?.kind === "streak" ? winning.runs : []).toHaveLength(3);
  });
});
