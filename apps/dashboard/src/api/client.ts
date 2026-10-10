import { BootstrapSchema, RefereeBootstrapSchema, TopBootstrapSchema, type Bootstrap, type RefereeBootstrap, type TopBootstrap } from "./contracts";

const configuredBase = import.meta.env.VITE_API_BASE_URL?.trim() ?? "";
const apiBase = configuredBase.replace(/\/$/, "");

export async function loadGroup2Bootstrap(signal?: AbortSignal): Promise<Bootstrap> {
  return loadEndpoint("/api/v1/group2/bootstrap", BootstrapSchema, signal, "No se pudo conectar con la API de FootballDataHub.", "La respuesta de la API no coincide con el contrato del dashboard.");
}

export async function loadGroup2TopBootstrap(signal?: AbortSignal): Promise<TopBootstrap> {
  return loadEndpoint("/api/v1/group2/top/bootstrap", TopBootstrapSchema, signal, "No se pudieron cargar los datos de Destacados.", "La respuesta de Destacados no coincide con el contrato del dashboard.");
}

export async function loadGroup2RefereesBootstrap(signal?: AbortSignal): Promise<RefereeBootstrap> {
  return loadEndpoint("/api/v1/group2/referees/bootstrap", RefereeBootstrapSchema, signal, "No se pudieron cargar los datos de Árbitros.", "La respuesta de Árbitros no coincide con el contrato del dashboard.");
}

async function loadEndpoint<T>(
  path: string,
  schema: { safeParse: (value: unknown) => { success: true; data: T } | { success: false } },
  signal: AbortSignal | undefined,
  connectionError: string,
  contractError: string,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${apiBase}${path}`, { headers: { Accept: "application/json" }, signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new Error(connectionError);
  }
  if (!response.ok) {
    const detail = response.status === 503 && path.includes("/top/")
      ? "Destacados no está disponible: su captura independiente no superó la validación."
      : response.status === 503 && path.includes("/referees/")
        ? "Árbitros no está disponible: su captura independiente no superó la validación."
        : response.status === 503
          ? "La API todavía no tiene un dataset preparado."
          : `La API respondió con un error (${response.status}).`;
    throw new Error(detail);
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new Error("La API devolvió una respuesta que no es JSON válido.");
  }
  const parsed = schema.safeParse(payload);
  if (!parsed.success) throw new Error(contractError);
  return parsed.data;
}
