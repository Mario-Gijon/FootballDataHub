import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearTeamProfileCache, loadTeamRoster } from "../api/client";

describe("team roster request timeout", () => {
  beforeEach(() => {
    clearTeamProfileCache();
  });

  afterEach(() => {
    clearTeamProfileCache();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("ends a stalled request and removes its rejected promise from the roster cache", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn()
      .mockImplementationOnce((_input: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
      }))
      .mockImplementationOnce((_input: RequestInfo | URL, init?: RequestInit) => Promise.resolve({
        ok: true,
        status: 200,
        json: () => new Promise<unknown>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => reject(new Error("body aborted")), { once: true });
        }),
      } as Response))
      .mockResolvedValueOnce({
        ok: false,
        status: 404,
        json: async () => ({ detail: { code: "profile_not_captured" } }),
      } as Response);
    vi.stubGlobal("fetch", fetchMock);

    const firstRequest = loadTeamRoster(48, "2026-27");
    const firstRequestExpectation = expect(firstRequest).rejects.toMatchObject({ code: "timeout", statusCode: 0 });
    await vi.advanceTimersByTimeAsync(15_000);
    await firstRequestExpectation;

    const bodyRequest = loadTeamRoster(48, "2026-27");
    const bodyRequestExpectation = expect(bodyRequest).rejects.toMatchObject({ code: "timeout", statusCode: 0 });
    await vi.advanceTimersByTimeAsync(15_000);
    await bodyRequestExpectation;

    await expect(loadTeamRoster(48, "2026-27")).resolves.toEqual({ status: "not_captured" });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[0]?.[1]?.signal).toBeInstanceOf(AbortSignal);
  });
});
