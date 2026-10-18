import { describe, expect, it } from "vitest";
import { formatMatchDateTime, matchDateTimeAttribute } from "./match-date-time";

describe("match date and kickoff formatting", () => {
  it("shows an observed time and keeps the calendar date timezone-neutral", () => {
    expect(formatMatchDateTime("2026-08-29", "19:15")).toBe("29 de agosto de 2026 · 19:15");
    expect(matchDateTimeAttribute("2026-08-29", "19:15")).toBe("2026-08-29T19:15");
  });

  it("does not invent a time when the source did not provide one", () => {
    expect(formatMatchDateTime("2026-08-29", null)).toBe("29 de agosto de 2026");
    expect(matchDateTimeAttribute("2026-08-29", undefined)).toBe("2026-08-29");
  });

  it("supports compact calendar labels", () => {
    expect(formatMatchDateTime("2026-08-29", "19:15", "compact")).toMatch(/29.*ago.*2026 · 19:15/);
  });
});
