import { afterEach, describe, expect, it, vi } from "vitest";
import { loadGroup2Bootstrap } from "./client";

afterEach(() => vi.unstubAllGlobals());

describe("cliente del bootstrap", () => {
  it("rechaza respuestas que no respetan el contrato", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ teams: [] }),
    }));
    await expect(loadGroup2Bootstrap()).rejects.toThrow("no coincide con el contrato");
  });

  it("presenta un error concreto ante un problema de red", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    await expect(loadGroup2Bootstrap()).rejects.toThrow("No se pudo conectar");
  });
});
