import { BootstrapSchema, type Bootstrap } from "./contracts";

const configuredBase = import.meta.env.VITE_API_BASE_URL?.trim() ?? "";
const apiBase = configuredBase.replace(/\/$/, "");

export async function loadGroup2Bootstrap(signal?: AbortSignal): Promise<Bootstrap> {
  let response: Response;
  try {
    response = await fetch(`${apiBase}/api/v1/group2/bootstrap`, {
      headers: { Accept: "application/json" },
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new Error("No se pudo conectar con la API de FootballDataHub.");
  }

  if (!response.ok) {
    throw new Error(
      response.status === 503
        ? "La API todavía no tiene un dataset preparado."
        : `La API respondió con un error (${response.status}).`,
    );
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new Error("La API devolvió una respuesta que no es JSON válido.");
  }

  const parsed = BootstrapSchema.safeParse(payload);
  if (!parsed.success) {
    throw new Error("La respuesta de la API no coincide con el contrato del dashboard.");
  }
  return parsed.data;
}
