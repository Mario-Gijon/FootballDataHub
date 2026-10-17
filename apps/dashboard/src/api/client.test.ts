import { afterEach, describe, expect, it, vi } from "vitest";
import { loadGroup2Bootstrap, loadPlayerDetail } from "./client";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe("cliente del bootstrap", () => {
  it("rechaza respuestas que no respetan el contrato", async () => {
    vi.stubEnv("DEV", true);
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ teams: [] }),
    }));
    await expect(loadGroup2Bootstrap()).rejects.toThrow("no coincide con el contrato");
    expect(consoleError).toHaveBeenCalledWith(
      "FootballDataHub: respuesta incompatible con el contrato",
      expect.objectContaining({
        path: "/api/v1/groups/2/bootstrap",
        group: "2",
        section: "bootstrap",
        issues: expect.arrayContaining([
          expect.objectContaining({ path: "metadata", code: "invalid_type" }),
        ]),
      }),
    );
  });

  it("presenta un error concreto ante un problema de red", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    await expect(loadGroup2Bootstrap()).rejects.toThrow("No se pudo conectar");
  });

  it("descarta una respuesta de jugador cancelada mientras se lee su JSON", async () => {
    let resolveJson!: (value: unknown) => void;
    let jsonStarted!: () => void;
    const started = new Promise<void>((resolve) => { jsonStarted = resolve; });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => {
        jsonStarted();
        return new Promise((resolve) => { resolveJson = resolve; });
      },
    }));
    const controller = new AbortController();
    const pending = loadPlayerDetail(28577, controller.signal);
    await started;
    controller.abort();
    resolveJson({});
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  });
});
