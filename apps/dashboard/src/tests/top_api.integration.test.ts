import { describe, expect, it } from "vitest";
import { TopBootstrapSchema } from "../api/contracts";

const apiBaseUrl = process.env.FDH_TEST_API_BASE_URL?.replace(/\/$/, "");

describe("live TOP API contract", () => {
  it.skipIf(!apiBaseUrl)("serves valid v3 bootstraps for both groups with current validators", async () => {
    for (const group of ["1", "2"] as const) {
      const response = await fetch(`${apiBaseUrl}/api/v1/groups/${group}/top/bootstrap`);
      expect(response.status).toBe(200);
      const payload: unknown = await response.json();
      const parsed = TopBootstrapSchema.safeParse(payload);
      if (!parsed.success) {
        throw new Error(JSON.stringify(parsed.error.issues.map((issue) => ({
          path: issue.path,
          code: issue.code,
          message: issue.message,
        }))));
      }

      const groupLabel = group === "1" ? "I" : "II";
      expect(parsed.data.metadata.group).toBe(groupLabel);
      expect(response.headers.get("etag")).toMatch(new RegExp(`^\\"group-${group}-top-v3-`));
      expect(parsed.data.foreigners_summary).toMatchObject(
        group === "1"
          ? { source_count: 60, available_count: 59, missing_count: 1, coverage_status: "documented_discrepancy" }
          : { source_count: 101, available_count: 101, missing_count: 0, coverage_status: "complete" },
      );

      const freshValidator = response.headers.get("etag");
      expect(freshValidator).toBeTruthy();
      const cached = await fetch(`${apiBaseUrl}/api/v1/groups/${group}/top/bootstrap`, {
        headers: { "If-None-Match": freshValidator! },
      });
      expect(cached.status).toBe(304);
    }
  });
});
