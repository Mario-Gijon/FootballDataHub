import {
  BootstrapSchema,
  RefereeBootstrapSchema,
  StatisticsBootstrapSchema,
  TeamRosterSchema,
  TeamFollowSchema,
  TeamTransfersSchema,
  MatchResultsBootstrapSchema,
  MatchPageSchema,
  PlayerDirectorySchema,
  PlayerDetailSchema,
  TopBootstrapSchema,
  type Bootstrap,
  type RefereeBootstrap,
  type StatisticsBootstrap,
  type TeamRoster,
  type TeamFollow,
  type TeamTransfers,
  type MatchResultsBootstrap,
  type MatchPage,
  type PlayerDirectory,
  type PlayerDetail,
  type TopBootstrap,
} from "./contracts";
import type { ZodType } from "zod";

export type CompetitionGroup = "1" | "2";

const apiBase = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

export type TeamRosterLoadResult =
  | { status: "available"; roster: TeamRoster }
  | { status: "not_captured" };

export class TeamRosterApiError extends Error {
  constructor(message: string, readonly code: string, readonly statusCode: number) {
    super(message);
    this.name = "TeamRosterApiError";
  }
}

const teamProfileCache = new Map<string, Promise<TeamRosterLoadResult>>();
export type TeamFollowLoadResult =
  | { status: "available"; follow: TeamFollow }
  | { status: "not_captured" };

export class TeamFollowApiError extends Error {
  constructor(message: string, readonly code: string, readonly statusCode: number) {
    super(message);
    this.name = "TeamFollowApiError";
  }
}

const teamFollowCache = new Map<string, Promise<TeamFollowLoadResult>>();
export type TeamTransfersLoadResult =
  | { status: "available"; transfers: TeamTransfers }
  | { status: "not_captured" };

export class TeamTransfersApiError extends Error {
  constructor(message: string, readonly code: string, readonly statusCode: number) {
    super(message);
    this.name = "TeamTransfersApiError";
  }
}

const teamTransfersCache = new Map<string, Promise<TeamTransfersLoadResult>>();

export function loadTeamRoster(teamId: number, season: string): Promise<TeamRosterLoadResult> {
  const key = `${teamId}:${season}:roster`;
  const cached = teamProfileCache.get(key);
  if (cached) return cached;
  const pending = requestTeamRoster(teamId, season).catch((error: unknown) => {
    teamProfileCache.delete(key);
    throw error;
  });
  teamProfileCache.set(key, pending);
  return pending;
}

export function clearTeamProfileCache(): void {
  teamProfileCache.clear();
  teamFollowCache.clear();
  teamTransfersCache.clear();
}

export function loadTeamTransfers(teamId: number, season: string): Promise<TeamTransfersLoadResult> {
  const key = `${teamId}:${season}:transfers`;
  const cached = teamTransfersCache.get(key);
  if (cached) return cached;
  const pending = requestTeamTransfers(teamId, season).catch((error: unknown) => {
    teamTransfersCache.delete(key);
    throw error;
  });
  teamTransfersCache.set(key, pending);
  return pending;
}

async function requestTeamTransfers(teamId: number, season: string): Promise<TeamTransfersLoadResult> {
  let response: Response;
  try {
    response = await fetch(`${apiBase}/api/v1/teams/${teamId}/seasons/${season}/transfers`, {
      headers: { Accept: "application/json" },
    });
  } catch {
    throw new TeamTransfersApiError("No se pudo conectar con la API de FootballDataHub.", "connection_error", 0);
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new TeamTransfersApiError("La API devolvió una respuesta que no es JSON válido.", "invalid_json", response.status);
  }
  if (!response.ok) {
    const detail = typeof body === "object" && body !== null && "detail" in body
      ? (body as { detail?: unknown }).detail : undefined;
    const errorBody = typeof detail === "object" && detail !== null ? detail as { code?: unknown; message?: unknown } : {};
    if (response.status === 404 && errorBody.code === "transfers_not_captured") return { status: "not_captured" };
    throw new TeamTransfersApiError(
      typeof errorBody.message === "string" ? errorBody.message : `La API respondió con un error (${response.status}).`,
      typeof errorBody.code === "string" ? errorBody.code : "request_failed",
      response.status,
    );
  }
  const parsed = TeamTransfersSchema.safeParse(body);
  if (!parsed.success) {
    throw new TeamTransfersApiError("La respuesta de Traspasos no coincide con su contrato.", "contract_error", response.status);
  }
  if (parsed.data.metadata.team_id !== teamId || parsed.data.metadata.season !== season) {
    throw new TeamTransfersApiError("Los Traspasos devueltos no coinciden con el equipo o temporada solicitados.", "scope_mismatch", response.status);
  }
  return { status: "available", transfers: parsed.data };
}

export function loadTeamFollow(teamId: number, season: string): Promise<TeamFollowLoadResult> {
  const key = `${teamId}:${season}:follow`;
  const cached = teamFollowCache.get(key);
  if (cached) return cached;
  const pending = requestTeamFollow(teamId, season).catch((error: unknown) => {
    teamFollowCache.delete(key);
    throw error;
  });
  teamFollowCache.set(key, pending);
  return pending;
}

async function requestTeamFollow(teamId: number, season: string): Promise<TeamFollowLoadResult> {
  let response: Response;
  try {
    response = await fetch(`${apiBase}/api/v1/teams/${teamId}/seasons/${season}/follow`, {
      headers: { Accept: "application/json" },
    });
  } catch {
    throw new TeamFollowApiError("No se pudo conectar con la API de FootballDataHub.", "connection_error", 0);
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new TeamFollowApiError("La API devolvió una respuesta que no es JSON válido.", "invalid_json", response.status);
  }
  if (!response.ok) {
    const detail = typeof body === "object" && body !== null && "detail" in body
      ? (body as { detail?: unknown }).detail : undefined;
    const errorBody = typeof detail === "object" && detail !== null ? detail as { code?: unknown; message?: unknown } : {};
    if (response.status === 404 && errorBody.code === "follow_not_captured") return { status: "not_captured" };
    throw new TeamFollowApiError(
      typeof errorBody.message === "string" ? errorBody.message : `La API respondió con un error (${response.status}).`,
      typeof errorBody.code === "string" ? errorBody.code : "request_failed",
      response.status,
    );
  }
  const parsed = TeamFollowSchema.safeParse(body);
  if (!parsed.success) {
    throw new TeamFollowApiError("La respuesta de Seguimiento no coincide con su contrato.", "contract_error", response.status);
  }
  if (parsed.data.team.team_id !== teamId || parsed.data.metadata.season !== season) {
    throw new TeamFollowApiError("El Seguimiento devuelto no coincide con el equipo o temporada solicitados.", "scope_mismatch", response.status);
  }
  return { status: "available", follow: parsed.data };
}

async function requestTeamRoster(teamId: number, season: string): Promise<TeamRosterLoadResult> {
  let response: Response;
  try {
    response = await fetch(`${apiBase}/api/v1/teams/${teamId}/seasons/${season}/roster`, {
      headers: { Accept: "application/json" },
    });
  } catch {
    throw new TeamRosterApiError("No se pudo conectar con la API de FootballDataHub.", "connection_error", 0);
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new TeamRosterApiError("La API devolvió una respuesta que no es JSON válido.", "invalid_json", response.status);
  }
  if (!response.ok) {
    const detail = typeof body === "object" && body !== null && "detail" in body
      ? (body as { detail?: unknown }).detail
      : undefined;
    const errorBody = typeof detail === "object" && detail !== null ? detail as { code?: unknown; message?: unknown } : {};
    if (response.status === 404 && errorBody.code === "profile_not_captured") {
      return { status: "not_captured" };
    }
    throw new TeamRosterApiError(
      typeof errorBody.message === "string" ? errorBody.message : `La API respondió con un error (${response.status}).`,
      typeof errorBody.code === "string" ? errorBody.code : "request_failed",
      response.status,
    );
  }
  const parsed = TeamRosterSchema.safeParse(body);
  if (!parsed.success) {
    throw new TeamRosterApiError("La respuesta de Plantilla no coincide con su contrato.", "contract_error", response.status);
  }
  if (parsed.data.team.team_id !== teamId || parsed.data.metadata.season !== season) {
    throw new TeamRosterApiError("La Plantilla devuelta no coincide con el equipo o temporada solicitados.", "scope_mismatch", response.status);
  }
  return { status: "available", roster: parsed.data };
}

export function loadGroupBootstrap(group: CompetitionGroup, signal?: AbortSignal): Promise<Bootstrap> {
  const expectedLabel = group === "1" ? "I" : "II";
  return loadEndpoint(
    `/api/v1/groups/${group}/bootstrap`, BootstrapSchema, signal,
    "No se pudo conectar con la API de FootballDataHub.",
    "La respuesta de la API no coincide con el contrato del dashboard.",
    (payload) => payload.metadata.group === expectedLabel,
  );
}

export function loadGroupTopBootstrap(group: CompetitionGroup, signal?: AbortSignal): Promise<TopBootstrap> {
  const expectedLabel = group === "1" ? "I" : "II";
  return loadEndpoint(
    `/api/v1/groups/${group}/top/bootstrap`, TopBootstrapSchema, signal,
    "No se pudieron cargar los datos de Destacados.",
    "La respuesta de Destacados no coincide con el contrato del dashboard.",
    (payload) => payload.metadata.group === expectedLabel,
  );
}

export function loadGroupRefereesBootstrap(group: CompetitionGroup, signal?: AbortSignal): Promise<RefereeBootstrap> {
  const scope = group === "1" ? "I" : "II";
  return loadEndpoint(
    `/api/v1/groups/${group}/referees/bootstrap`, RefereeBootstrapSchema, signal,
    "No se pudieron cargar los datos de Árbitros.",
    "La respuesta de Árbitros no coincide con el contrato del dashboard.",
    (payload) => payload.metadata.group === "I/II" && scope in payload.metadata.related_match_datasets,
  );
}

export function loadGroupStatisticsBootstrap(group: CompetitionGroup, signal?: AbortSignal): Promise<StatisticsBootstrap> {
  const expectedLabel = group === "1" ? "I" : "II";
  return loadEndpoint(
    `/api/v1/groups/${group}/statistics/bootstrap`, StatisticsBootstrapSchema, signal,
    "No se pudieron cargar las estadísticas.",
    "La respuesta de Estadísticas no coincide con el contrato del dashboard.",
    (payload) => payload.metadata.group === expectedLabel && payload.statistics.group === expectedLabel,
  );
}

// Group II aliases remain available for consumers migrating from the original API.
export const loadGroup2Bootstrap = (signal?: AbortSignal) => loadGroupBootstrap("2", signal);
export const loadGroup2TopBootstrap = (signal?: AbortSignal) => loadGroupTopBootstrap("2", signal);
export const loadGroup2RefereesBootstrap = (signal?: AbortSignal) => loadGroupRefereesBootstrap("2", signal);
export const loadGroup2StatisticsBootstrap = (signal?: AbortSignal) => loadGroupStatisticsBootstrap("2", signal);

export function loadMatchResultsBootstrap(signal?: AbortSignal): Promise<MatchResultsBootstrap> {
  return loadEndpoint(
    "/api/v1/matches/bootstrap", MatchResultsBootstrapSchema, signal,
    "No se pudo conectar con la API de Resultados.",
    "La generación de Resultados no coincide con el contrato del dashboard.",
  );
}

export class MatchPageApiError extends Error {
  constructor(message: string, readonly code: string, readonly statusCode: number) {
    super(message);
    this.name = "MatchPageApiError";
  }
}

const matchPageCache = new Map<string, Promise<MatchPage>>();

export function clearMatchPageCache(): void {
  matchPageCache.clear();
}

export function loadMatchPage(internalId: string): Promise<MatchPage> {
  const cached = matchPageCache.get(internalId);
  if (cached) return cached;
  const pending = requestMatchPage(internalId).catch((error: unknown) => {
    matchPageCache.delete(internalId);
    throw error;
  });
  matchPageCache.set(internalId, pending);
  return pending;
}

async function requestMatchPage(internalId: string): Promise<MatchPage> {
  let response: Response;
  try {
    response = await fetch(`${apiBase}/api/v1/matches/${encodeURIComponent(internalId)}`, {
      headers: { Accept: "application/json" },
    });
  } catch {
    throw new MatchPageApiError("No se pudo conectar con la API de FootballDataHub.", "connection_error", 0);
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new MatchPageApiError("La API devolvió una respuesta que no es JSON válido.", "invalid_json", response.status);
  }
  if (!response.ok) {
    const detail = typeof body === "object" && body !== null && "detail" in body
      ? (body as { detail?: unknown }).detail : undefined;
    const errorBody = typeof detail === "object" && detail !== null
      ? detail as { code?: unknown; message?: unknown } : {};
    throw new MatchPageApiError(
      typeof errorBody.message === "string" ? errorBody.message : `La API respondió con un error (${response.status}).`,
      typeof errorBody.code === "string" ? errorBody.code : "request_failed",
      response.status,
    );
  }
  const parsed = MatchPageSchema.safeParse(body);
  if (!parsed.success) {
    throw new MatchPageApiError("La ficha del partido no coincide con el contrato de la aplicación.", "contract_error", response.status);
  }
  if (parsed.data.match.internal_id !== internalId) {
    throw new MatchPageApiError("La API devolvió otro encuentro.", "identity_mismatch", response.status);
  }
  return parsed.data;
}

export interface PlayerDirectoryQuery {
  q?: string;
  group?: "I" | "II";
  teamId?: number;
  page?: number;
  pageSize?: number;
}

export async function loadPlayerDirectory(query: PlayerDirectoryQuery = {}, signal?: AbortSignal): Promise<PlayerDirectory> {
  const params = new URLSearchParams();
  if (query.q?.trim()) params.set("q", query.q.trim());
  if (query.group) params.set("group", query.group);
  if (query.teamId) params.set("team_id", String(query.teamId));
  params.set("page", String(query.page ?? 1));
  params.set("page_size", String(query.pageSize ?? 25));
  const suffix = params.toString();
  return loadEndpoint(
    `/api/v1/players${suffix ? `?${suffix}` : ""}`, PlayerDirectorySchema, signal,
    "No se pudo conectar con la API de jugadores.",
    "El inventario de jugadores no coincide con el contrato del dashboard.",
  );
}

export async function loadPlayerDetail(playerId: number, signal?: AbortSignal): Promise<PlayerDetail> {
  return loadEndpoint(
    `/api/v1/players/${playerId}`, PlayerDetailSchema, signal,
    "No se pudo conectar con la API de jugadores.",
    "La ficha del jugador no coincide con el contrato del dashboard.",
  );
}

async function loadEndpoint<T>(
  path: string,
  schema: ZodType<T>,
  signal: AbortSignal | undefined,
  connectionError: string,
  contractError: string,
  verifyGroup?: (payload: T) => boolean,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${apiBase}${path}`, { headers: { Accept: "application/json" }, signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new Error(connectionError);
  }
  if (signal?.aborted) throw new DOMException("La solicitud fue cancelada.", "AbortError");
  if (!response.ok) {
    const detail = response.status === 503 && path.includes("/statistics/")
      ? "Estadísticas no está disponible: su captura no coincide con Resultados o no superó la validación."
      : response.status === 503 && path.includes("/top/")
      ? "Destacados no está disponible: su captura independiente no superó la validación."
      : response.status === 503 && path.includes("/referees/")
        ? "Árbitros no está disponible: su captura independiente no superó la validación."
        : response.status === 503
          ? "La API todavía no tiene un dataset preparado para este grupo."
          : `La API respondió con un error (${response.status}).`;
    throw new Error(detail);
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    if (signal?.aborted) throw new DOMException("La solicitud fue cancelada.", "AbortError");
    throw new Error("La API devolvió una respuesta que no es JSON válido.");
  }
  if (signal?.aborted) throw new DOMException("La solicitud fue cancelada.", "AbortError");
  const parsed = schema.safeParse(payload);
  if (!parsed.success) {
    if (import.meta.env.DEV) {
      const requested = path.match(/^\/api\/v1\/groups\/([^/]+)\/([^/]+)/);
      console.error("FootballDataHub: respuesta incompatible con el contrato", {
        path,
        group: requested?.[1] ?? "legacy",
        section: requested?.[2] ?? "unknown",
        issues: parsed.error.issues.map((issue) => ({
          path: issue.path.length ? issue.path.join(".") : "(root)",
          code: issue.code,
          message: issue.message,
          expected: "expected" in issue ? issue.expected : undefined,
          received: "received" in issue ? issue.received : undefined,
        })),
      });
    }
    throw new Error(contractError);
  }
  if (verifyGroup && !verifyGroup(parsed.data)) {
    if (import.meta.env.DEV) {
      const requested = path.match(/^\/api\/v1\/groups\/([^/]+)\/([^/]+)/);
      console.error("FootballDataHub: el grupo de la respuesta no coincide", {
        path,
        group: requested?.[1] ?? "legacy",
        section: requested?.[2] ?? "unknown",
      });
    }
    throw new Error(contractError);
  }
  return parsed.data;
}
