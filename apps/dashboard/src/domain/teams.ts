import type { Bootstrap, Team } from "../api/contracts";
import type { CompetitionGroup } from "../api/client";

export interface CatalogTeam extends Team {
  group: CompetitionGroup;
  season: string;
  captureId: string;
}

export type GroupBootstraps = Partial<Record<CompetitionGroup, Bootstrap | null>>;

export function teamPath(teamId: number): string {
  if (!Number.isSafeInteger(teamId) || teamId <= 0) {
    throw new RangeError("El identificador del equipo debe ser un entero positivo.");
  }
  return `/teams/${teamId}`;
}

export function teamRosterPath(teamId: number): string {
  return `${teamPath(teamId)}/roster`;
}

export function teamFollowPath(teamId: number): string {
  return `${teamPath(teamId)}/follow`;
}

export function normalizeTeamSearch(value: string): string {
  return value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("es-ES").trim();
}

export function buildTeamCatalog(bootstraps: GroupBootstraps): CatalogTeam[] {
  const ids = new Set<number>();
  const catalog: CatalogTeam[] = [];
  for (const group of ["1", "2"] as const) {
    const bootstrap = bootstraps[group];
    if (!bootstrap) continue;
    for (const team of bootstrap.teams) {
      if (ids.has(team.team_id)) {
        throw new Error(`El catálogo contiene el team_id ${team.team_id} en más de un grupo.`);
      }
      ids.add(team.team_id);
      catalog.push({
        ...team,
        group,
        season: bootstrap.metadata.season,
        captureId: bootstrap.metadata.capture_id,
      });
    }
  }
  return catalog.sort((left, right) => left.name.localeCompare(right.name, "es", { sensitivity: "base" }) || left.team_id - right.team_id);
}

export function findTeamGroup(bootstraps: GroupBootstraps, teamId: number): CompetitionGroup | null {
  const matches = (["1", "2"] as const).filter((group) =>
    bootstraps[group]?.teams.some((team) => team.team_id === teamId),
  );
  if (matches.length > 1) throw new Error(`El team_id ${teamId} aparece en más de un grupo.`);
  return matches[0] ?? null;
}

export function searchTeams(teams: readonly CatalogTeam[], query: string): CatalogTeam[] {
  const normalizedQuery = normalizeTeamSearch(query);
  if (!normalizedQuery) return [...teams];
  return teams.filter((team) => normalizeTeamSearch(team.name).includes(normalizedQuery));
}
