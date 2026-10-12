import { describe, expect, it } from "vitest";
import group1Matches from "../../../../data/exports/bdfutbol/group1_classification/20261010T202500.293648Z-b770724f/normalized/matches.json";
import group2Matches from "../../../../data/exports/bdfutbol/group2_classification/derived-res01-20261010T102656Z/normalized/matches.json";
import type { Bootstrap } from "../api/contracts";
import { buildTeamCatalog, findTeamGroup, normalizeTeamSearch, searchTeams, teamMatchesPath, teamPath } from "./teams";

const group1 = {
  metadata: { season: "2026/27", capture_id: "fixture-group1" },
  teams: group1Matches.teams,
} as unknown as Bootstrap;
const group2 = {
  metadata: { season: "2026/27", capture_id: "fixture-group2" },
  teams: group2Matches.teams,
} as unknown as Bootstrap;

describe("catálogo de equipos", () => {
  it("reúne 20 equipos por grupo con identificadores únicos y procedencia propia", () => {
    const catalog = buildTeamCatalog({ "1": group1, "2": group2 });
    expect(catalog).toHaveLength(40);
    expect(catalog.filter((team) => team.group === "1")).toHaveLength(20);
    expect(catalog.filter((team) => team.group === "2")).toHaveLength(20);
    expect(new Set(catalog.map((team) => team.team_id)).size).toBe(40);
    expect(catalog.find((team) => team.team_id === 48)).toMatchObject({ name: "Racing de Ferrol", group: "1", captureId: "fixture-group1" });
    expect(catalog.find((team) => team.team_id === 49)).toMatchObject({ name: "Jaén", group: "2", captureId: "fixture-group2" });
  });

  it("rechaza IDs duplicados en grupos distintos", () => {
    const duplicated = { ...group1, teams: [...group1.teams, group2.teams[0]!] } as Bootstrap;
    expect(() => buildTeamCatalog({ "1": duplicated, "2": group2 })).toThrow(/team_id/);
  });

  it("resuelve grupo y construye solo rutas con IDs válidos", () => {
    expect(findTeamGroup({ "1": group1, "2": group2 }, 48)).toBe("1");
    expect(findTeamGroup({ "1": group1, "2": group2 }, 49)).toBe("2");
    expect(findTeamGroup({ "1": group1, "2": group2 }, 99999)).toBeNull();
    expect(teamPath(49)).toBe("/teams/49");
    expect(teamMatchesPath(49)).toBe("/teams/49/matches");
    expect(() => teamPath(0)).toThrow(RangeError);
  });

  it("normaliza tildes y busca por fragmentos publicados", () => {
    const catalog = buildTeamCatalog({ "1": group1, "2": group2 });
    expect(normalizeTeamSearch("  JAÉN  ")).toBe("jaen");
    expect(searchTeams(catalog, "jaen").map((team) => team.name)).toEqual(["Jaén"]);
    expect(searchTeams(catalog, "RACING DE FERROL").map((team) => team.team_id)).toEqual([48]);
    expect(searchTeams(catalog, "club inventado")).toEqual([]);
  });
});
